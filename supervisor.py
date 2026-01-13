import websockets
import asyncio
import json
import subprocess
import re
import queue
import threading
import psutil
import pystray
from queries import version_comparison, players

CHUNK_RE = re.compile(r"Loading [0-9]+ persistent chunks")
DONE_RE = re.compile(r"Done \(\d+(?:\.\d+)?s\)!")

class Supervisor:
    def __init__(self, host: str, port: int, token: str, manager_process_args, tray_icon, debug_logs=False):
        self.host = host
        self.port = port
        self.token = token
        self.manager_process_args = manager_process_args
        self._debug_logs = debug_logs
        self._client: websockets.ServerConnection | None = None
        self._mc_server: subprocess.Popen | None = None
        self._mc_version: str = ""
        self._loading_complete = asyncio.Event()
        self._loading_started = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._listener_task: asyncio.Task | None = None
        self._error_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._ui_disconnection = asyncio.Event()
        self._waiting_for_feedback = asyncio.Event()
        self._set_feedback_value = asyncio.Event()
        self._expecting_close = asyncio.Event()
        self._stats_task = None
        self._feedback_value = False
        self._logs = []
        self._log_lock = asyncio.Lock()

        self.icon = pystray.Icon(
            "mc_supervisor",
            tray_icon,
            "Minecraft Server",
            menu=self.menu()
        )

        threading.Thread(target=self.icon.run, daemon=True).start()
    
    def close_icon(self, icon, item):
        icon.stop()
    
    def stop_server(self, icon, item):
        if self._client:
            AsyncRunner().submit(self.send_to_client({"type": "tray_close_server"}))
        else:
            AsyncRunner().submit(self.perform_server_shutdown("immediate"))
    
    def hide_manager(self, icon, item):
        AsyncRunner().submit(self.send_to_client({"type": "close_manager"}))
    
    def open_manager(self, icon, item):
        if not self._client:
            subprocess.Popen(
                self.manager_process_args,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True
            )
    
    def menu(self):
        items = []
        if self._mc_is_alive():
            items.append(pystray.MenuItem("Stop Server", self.stop_server))
            items.append(pystray.Menu.SEPARATOR)
        
        if self._client:
            label = "Close Manager"
            if self._mc_is_alive():
                label = "Hide Manager"
            items.append(pystray.MenuItem(label, self.hide_manager))
        else:
            items.append(pystray.MenuItem("Open Manager", self.open_manager))
        
        return pystray.Menu(*items)
    
    def create_mc_server_process(self, server_path, server_args):
        self._loading_complete.clear()
        self._loading_started.set()
        self._start_mc_server(server_args, server_path)
        self._listener_task = asyncio.create_task(self.server_listener())
        if self._debug_logs:
            self._error_task = asyncio.create_task(self.error_listener())
    
    def _start_mc_server(self, process_args, server_path):
        if self._mc_is_alive():
            return
        
        self._logs.clear()
        if self._debug_logs:
            self._mc_server = subprocess.Popen(
                process_args,
                cwd=server_path,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        else:
            self._mc_server = subprocess.Popen(
                process_args,
                cwd=server_path,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        
        self.icon.menu = self.menu()
    
    def _mc_is_alive(self):
        return self._mc_server and self._mc_server.poll() is None
    
    def get_mem_stats(self):
        vm = psutil.virtual_memory()
        ram_stats = {
            "total": vm.total / (1024 * 1024),
            "used": vm.used / (1024 * 1024),
            "available": vm.available / (1024 * 1024),
            "percent_used": vm.percent,
        }

        proc = psutil.Process(self._mc_server.pid)
        mem_percent = proc.memory_percent()
        return ram_stats.get("percent_used"), mem_percent

    async def stats_worker(self):
        try:
            while True:
                await asyncio.sleep(1)
                if not self._mc_is_alive():
                    break
                if self._client:
                    ram_used, mem_percent = self.get_mem_stats()
                    await self.send_to_client({"type": "stats", "percent_used": ram_used, "server_percent": mem_percent})
        except asyncio.CancelledError:
            raise

    async def wait_for_server_shutdown(self, process: subprocess.Popen):
        if not process or process.poll() is not None:
            return
        
        try:
            await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=10)
        except asyncio.TimeoutError:
            process.kill()
            await asyncio.to_thread(process.wait)
    
    async def error_listener(self):
        while self._mc_server and self._mc_server.stderr:
            line: str = await asyncio.to_thread(self._mc_server.stderr.readline)
            if not line:
                await asyncio.sleep(0.01)
                continue

            line = line.rstrip('\n')
            await self.send_to_client({"type": "server_error", "error": line})

    async def server_listener(self):
        try:
            server_loaded = False
            while self._mc_is_alive():
                line: str = await asyncio.to_thread(self._mc_server.stdout.readline)
                if not line:
                    await asyncio.sleep(0.01)
                    continue

                line = line.rstrip('\n')
                async with self._log_lock:
                    self._logs.append(line)
                
                if self._client is not None:
                    if not server_loaded:
                        if CHUNK_RE.search(line) is not None or "Preparing level" in line:
                            await self.send_to_client({"type": "loading", "state": "chunks"})
                        elif DONE_RE.search(line) is not None:
                            await self.send_to_client({"type": "loading", "state": "done"})
                            server_loaded = True
                            self._loading_complete.set()
                            self._loading_started.clear()
                            self._stats_task = asyncio.create_task(self.stats_worker())
                            
                    if self._waiting_for_feedback.is_set():
                        if "Gamerule send_command_feedback is currently set to: " in line:
                            self._feedback_value = line.split("currently set to: ")[-1] == "true"
                            self._set_feedback_value.set()
                            self._waiting_for_feedback.clear()
                            continue
                        elif "SendCommandFeedback = " in line:
                            self._feedback_value = line.split(" = ")[-1] == "true"
                            self._set_feedback_value.set()
                            self._waiting_for_feedback.clear()
                            continue
                    
                    if "Stopping server" in line:
                        await self.send_to_client({"type": "closing_server"})
                    elif "logged in with entity id" in line:
                        msg = line.split("INFO]")[-1].removeprefix(":")
                        name = msg.split("[/")[0].strip()
                        await self.send_to_client({"type": "player_joined", "name": name})
                    elif "lost connection" in line:
                        msg = line.split("INFO]")[-1].removeprefix(":")
                        name = msg.split("lost connection")[0].strip()
                        await self.send_to_client({"type": "player_left", "name": name})
                    elif "OutOfMemoryError" in line:
                        await self.send_to_client({"type": "out_of_memory"})

                    
                    await self.send_to_client({"type": "log", "msg": line})
            
            if not server_loaded:
                await self.send_to_client({"type": "loading", "state": "failed"})
                self._loading_complete.clear()
                self._loading_started.clear()
            elif self._expecting_close.is_set():
                self._expecting_close.clear()
            elif not self._expecting_close.is_set():
                if self._client:
                    self.icon.menu = self.menu()
                    await self.send_to_client({"type": "server_closed_unexpectedly"})
                else:
                    self._shutdown_event.set()
        finally:
            if self._stats_task and not self._stats_task.cancelled() and not self._stats_task.done():
                self._stats_task.cancel()
                try:
                    await self._stats_task
                except asyncio.CancelledError:
                    pass
    
    def send_server_cmd(self, cmd):
        if self._mc_is_alive():
            try:
                self._mc_server.stdin.write(cmd + '\n')
                self._mc_server.stdin.flush()
            except Exception:
                pass
    
    async def send_to_client(self, obj: dict):
        if self._client is None:
            return
        try:
            async with self._send_lock:
                await self._client.send(json.dumps(obj))
        except Exception:
            self._client = None
    
    async def turn_off_feedback(self, turn_back_on=None):
        if turn_back_on:
            cmd = "gamerule send_command_feedback"
            if version_comparison(self._mc_version, "25w44a", before=True):
                cmd = "gamerule sendCommandFeedback"
            self.send_server_cmd(f"{cmd} true")
            await asyncio.sleep(1)
        elif turn_back_on is None:
            self._waiting_for_feedback.set()
            cmd = "gamerule send_command_feedback"
            if version_comparison(self._mc_version, "25w44a", before=True):
                cmd = "gamerule sendCommandFeedback"
            self.send_server_cmd(cmd)
            try:
                await asyncio.wait_for(self._set_feedback_value.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                feedback = True
            else:
                feedback = self._feedback_value
            finally:
                self._set_feedback_value.clear()
            
            if feedback:
                self.send_server_cmd(f"{cmd} false")
            
            return feedback
    
    async def perform_server_shutdown(self, mode):
        self.icon.menu = self.menu()
        title_compatible = False if not self._mc_version else version_comparison(self._mc_version, "14w26a", after=True, equal=True)
        if mode == "immediate":
            self.send_server_cmd("stop")
            await self.wait_for_server_shutdown(self._mc_server)
        elif mode == "delayed":
            if not title_compatible:
                self.send_server_cmd("say Server Closed")
                self.send_server_cmd("say Closing in 10 seconds...")
                await asyncio.sleep(10)
            else:
                feedback_was_true = await self.turn_off_feedback()
                self.send_server_cmd('title @a subtitle {"text": "Closing in 10 seconds...", "color": "yellow"}')
                self.send_server_cmd('title @a title {"text": "Server Closed", "color": "red", "bold": true}')

                
                for i in range(10):
                    color = "red" if i > 6 else "white"
                    command = {
                        "text": str(10 - i),
                        "color": color
                    }
                    sec_command = {
                        "text": f"Closing in {str(10 - i)} seconds...",
                        "color": "yellow"
                    }
                    self.send_server_cmd(f'title @a subtitle {json.dumps(sec_command)}')
                    if version_comparison(self._mc_version, "16w32b", after=True, equal=True):
                        self.send_server_cmd(f"title @a actionbar {json.dumps(command)}")
                    await asyncio.sleep(1)

                await self.turn_off_feedback(turn_back_on=feedback_was_true)
            
            self.send_server_cmd("stop")
            await self.wait_for_server_shutdown(self._mc_server)
        elif mode == "keep alive":
            if not title_compatible:
                self.send_server_cmd("say Host app closed.")
                self.send_server_cmd("say Players cannot close the server.")
            else:
                feedback_was_true = await self.turn_off_feedback()
                self.send_server_cmd('title @a subtitle {"text": "Host app closed", "color": "white"}')
                self.send_server_cmd('title @a title {"text": ""}')
                self.send_server_cmd("say Players cannot close the server.")
                await self.turn_off_feedback(turn_back_on=feedback_was_true)
            self._ui_disconnection.set()
            self.icon.menu = self.menu()
    
    async def handler(self, wsocket: websockets.ServerConnection):
        if self._client is not None:
            await wsocket.close(code=1013, reason="busy")
            return

        try:
            raw = await asyncio.wait_for(wsocket.recv(), timeout=5)
            msg: dict = json.loads(raw)
        except Exception:
            await wsocket.close(code=1002, reason="bad handshake")
            return

        if msg.get("type") != "handshake" or msg.get("token") != self.token:
            await wsocket.close(code=1008, reason="unauthorized")
            return

        self._client = wsocket
        await self.send_to_client({"type": "handshake_ok"})
        self.icon.menu = self.menu()

        if self._ui_disconnection.is_set():
            self._ui_disconnection.clear()
            async with self._log_lock:
                await self.send_to_client({"type": "logs_list", "logs": self._logs})
            if self._mc_is_alive():
                self.send_server_cmd("say Host app reconnected.")
                self.send_server_cmd("say Players are able to close the server.")
                if version_comparison(self._mc_version, "1.8", after=True, equal=True):
                    feedback_was_true = await self.turn_off_feedback()
                    self.send_server_cmd('title @a subtitle {"text": "Host app reconnected", "color": "white"}')
                    self.send_server_cmd('title @a title {"text": ""}')
                    await self.turn_off_feedback(turn_back_on=feedback_was_true)

        try:
            async for raw in wsocket:
                msg = json.loads(raw)
                if msg.get("type") == "close":
                    mode = msg.get("mode")
                    await self.perform_server_shutdown(mode)
                    if mode == "keep alive":
                        return
                elif msg.get("type") == "command":
                    self.send_server_cmd(msg.get("cmd"))
                elif msg.get("type") == "loaded_status":
                    await self.send_to_client({"type": "loaded_status", "loaded": self._loading_complete.is_set()})
                elif msg.get("type") == "start_server":
                    path, args = msg.get("args")
                    self._mc_version = msg.get("version")
                    self.create_mc_server_process(path, args)
                elif msg.get("type") == "get_logs":
                    async with self._log_lock:
                        await self.send_to_client({"type": "logs_list", "logs": self._logs})
        except (websockets.ConnectionClosedOK, websockets.ConnectionClosedError, websockets.ConnectionClosed) as e:
            return

        except Exception as e:
            raise
        finally:
            if not self._ui_disconnection.is_set():
                self._shutdown_event.set()
            
            if self._client is wsocket:
                self._client = None
    
    async def startup(self):
        try:
            async with websockets.serve(self.handler, self.host, self.port):
                # print(f"Supervisor listening on ws://{self.host}:{self.port}")
                await self._shutdown_event.wait()
            
            if self._mc_is_alive():
                self.send_server_cmd("stop")
                await self.wait_for_server_shutdown(self._mc_server)

            if self._mc_server and self._mc_server.stdin:
                self._mc_server.stdin.close()
            if self._listener_task and not self._listener_task.done():
                self._listener_task.cancel()
                try:
                    await self._listener_task
                except asyncio.CancelledError:
                    pass
            if self._error_task and not self._error_task.done():
                self._error_task.cancel()
                try:
                    await self._error_task
                except asyncio.CancelledError:
                    pass
            if self._client is not None:
                await self._client.close()
        finally:
            self.icon.stop()


class SupervisorConnector:
    def __init__(self, msg_queue: queue.Queue, log_output_queue: queue.Queue, server_stopped_signal, add_player, remove_player, stats_signal, close_manager):
        self.msg_queue = msg_queue
        self.log_output_queue = log_output_queue
        self.add_player = add_player
        self.remove_player = remove_player
        self.server_stopped_signal = server_stopped_signal
        self.stats_signal = stats_signal
        self.close_manager = close_manager
        self._client: websockets.ClientConnection | None = None
        self.found_connection = threading.Event()
        self.spooling_up = threading.Event()
        self.loading_chunks = threading.Event()
        self.loading_complete = threading.Event()
        self.failed_to_load = threading.Event()
        self.closing_server = threading.Event()
        self.ip = ""
        self.port = None
    
    def set_info(self, ip, port):
        self.ip = ip
        self.port = port

    def connected(self):
        return self._client is not None
    
    async def close(self):
        if self._client is None:
            return
        
        ws = self._client
        self._client = None
        try:
            await ws.close()
        except Exception:
            pass

    async def connect(self):
        self.failed_to_load.clear()
        self.found_connection.clear()
        if self._client:
            return True

        uri = "ws://127.0.0.1:5675"

        try:
            wsocket = await websockets.connect(uri)
            await wsocket.send(json.dumps({"type": "handshake", "token": "dominion"}))

            response: dict = json.loads(await wsocket.recv())
            if response.get("type") != "handshake_ok":
                self.failed_to_load.set()
                return False

            self._client = wsocket
            self.found_connection.set()
            asyncio.create_task(self.handler())
            await wsocket.send(json.dumps({"type": "loaded_status"}))
            return True
        except Exception as e:
            print(e)
            self.failed_to_load.set()
            return False
    
    async def handler(self):
        try:
            async for raw in self._client:
                msg: dict = json.loads(raw)
                if msg.get("type") == "loading":
                    state = msg.get("state")
                    if state == "chunks" and not self.loading_chunks.is_set():
                        self.loading_chunks.set()
                    elif state == "done":
                        self.loading_complete.set()
                    elif state == "failed":
                        self.failed_to_load.set()
                elif msg.get("type") == "loaded_status":
                    if msg.get("loaded") == True:
                        self.loading_complete.set()
                    else:
                        self.loading_complete.clear()
                elif msg.get("type") == "log":
                    if not self.spooling_up.is_set() and not self.loading_complete.is_set() and not self.loading_chunks.is_set():
                        self.spooling_up.set()
                    self.log_output_queue.put([msg.get("msg")])
                elif msg.get("type") == "logs_list":
                    self.log_output_queue.put(msg.get("logs"))
                elif msg.get("type") == "closing_server" and self.closing_server.is_set():
                    self.server_stopped_signal.emit()
                    self.closing_server.clear()
                elif msg.get("type") == "server_closed_unexpectedly":
                    self.server_stopped_signal.emit()
                elif msg.get("type") == "player_joined":
                    obj = {"name": msg.get("name")}
                    self.add_player(obj)
                elif msg.get("type") == "player_left":
                    obj = {"name": msg.get("name")}
                    self.remove_player(obj)
                elif msg.get("type") == "out_of_memory":
                    self.msg_queue.put("<font color='red'>WARNING: Detecting low memory errors! Check logs.</font>")
                elif msg.get("type") == "stats":
                    mem_perc = msg.get("percent_used")
                    serv_perc = msg.get("server_percent")
                    self.stats_signal.emit({
                        "used_percent": mem_perc,
                        "server_percent": serv_perc
                    })
                elif msg.get("type") == "server_error":
                    self.msg_queue.put(f"<font color='red'>Server Error: {msg.get("error")}</font>")
                elif msg.get("type") == "close_manager":
                    self.close_manager.emit()
                elif msg.get("type") == "tray_close_server":
                    self.loading_complete.clear()
                    self.loading_chunks.clear()
                    self.spooling_up.clear()
                    self.closing_server.set()

                    self.msg_queue.put("Stopping server...")
                    
                    if len(players(self.ip, self.port)) == 0:
                        await self.send({"type": "close", "mode": "immediate"})
                    else:
                        self.msg_queue.put("Giving players 10 seconds notice...")
                        await self.send({"type": "close", "mode": "delayed"})
        except:
            pass
        finally:
            await self.close()
    
    async def send_cmd(self, cmd: str):
        if not self._client:
            return
        
        try:
            await self._client.send(json.dumps({"type": "command", "cmd": cmd}))
        except:
            await self.close()
    
    async def send(self, obj: dict):
        if not self._client:
            return
        
        try:
            if obj.get("type") in ["close", "start_server"]:
                self.loading_complete.clear()
                self.loading_chunks.clear()
                self.spooling_up.clear()
                if obj.get("type") == "close":
                    self.closing_server.set()
            await self._client.send(json.dumps(obj))
        except:
            await self.close()

class AsyncRunner:
    # Allows sync code to run async code. Bridges between them.
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
    
    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
    
    def submit(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)


def create_supervisor(manager_process_args, tray_icon, debug_logs=False):
    supervisor = Supervisor("127.0.0.1", 5675, "dominion", manager_process_args, tray_icon, debug_logs=debug_logs)
    asyncio.run(supervisor.startup())