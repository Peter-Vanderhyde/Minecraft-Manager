import websockets
import asyncio
import json
import subprocess
import re
import queue
import threading
from queries import version_comparison

CHUNK_RE = re.compile(r"Loading [0-9]+ persistent chunks")
DONE_RE = re.compile(r"Done \(\d+(?:\.\d+)?s\)!")

class Supervisor:
    def __init__(self, host: str, port: int, token: str):
        self.host = host
        self.port = port
        self.token = token
        self._client: websockets.ServerConnection | None = None
        self._mc_server: subprocess.Popen | None = None
        self._mc_version: str = ""
        self._loading_complete = asyncio.Event()
        self._loading_started = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._listener_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._ui_disconnection = asyncio.Event()
        self._waiting_for_feedback = asyncio.Event()
        self._set_feedback_value = asyncio.Event()
        self._feedback_value = False
        self._clients_num = 0
        self._logs = []
        self._log_lock = asyncio.Lock()
    
    def create_mc_server_process(self, server_path, server_args):
        self._loading_complete.clear()
        self._loading_started.set()
        self._start_mc_server(server_args, server_path)
        self._listener_task = asyncio.create_task(self.server_listener())
    
    def _start_mc_server(self, process_args, server_path):
        if self._mc_is_alive():
            return
        
        self._logs.clear()
        self._mc_server = subprocess.Popen(
            process_args,
            cwd=server_path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
    
    def _mc_is_alive(self):
        return self._mc_server and self._mc_server.poll() is None

    async def wait_for_server_shutdown(self, process: subprocess.Popen):
        if not process or process.poll() is not None:
            return
        
        try:
            await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=10)
        except asyncio.TimeoutError:
            process.kill()
            await asyncio.to_thread(process.wait)
    
    async def server_listener(self):
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
                
                await self.send_to_client({"type": "log", "msg": line})
        
        if not server_loaded:
            await self.send_to_client({"type": "loading", "state": "failed"})
            self._loading_complete.clear()
            self._loading_started.clear()
    
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
        self._clients_num += 1
        await self.send_to_client({"type": "log", "client_id": self._clients_num})

        if self._ui_disconnection.is_set():
            self._ui_disconnection.clear()
            async with self._log_lock:
                await self.send_to_client({"type": "logs_list", "logs": self._logs})
            if self._mc_is_alive():
                self.send_server_cmd("say Host app reconnected.")
                self.send_server_cmd("say Players are able to close the server.")
                if version_comparison(self._mc_version, "1.8", after=True, equal=True):
                    self.send_server_cmd('title @a subtitle {"text": "Host app reconnected", "color": "white"}')
                    self.send_server_cmd('title @a title {"text": ""}')

        try:
            async for raw in wsocket:
                msg = json.loads(raw)
                print("Supervisor Received:", msg)
                if msg.get("type") == "close":
                    title_compatible = version_comparison(self._mc_version, "14w26a", after=True, equal=True)
                    if msg.get("mode") == "immediate":
                        self.send_server_cmd("stop")
                        await self.wait_for_server_shutdown(self._mc_server)
                    elif msg.get("mode") == "delayed":
                        self._waiting_for_feedback.set()
                        if not title_compatible:
                            self.send_server_cmd("say Server Closed")
                            self.send_server_cmd("say Closing in 10 seconds...")
                            await asyncio.sleep(10)
                        else:
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

                            if feedback:
                                self.send_server_cmd(f"{cmd} true")
                                await asyncio.sleep(1)
                        
                        self.send_server_cmd("stop")
                        await self.wait_for_server_shutdown(self._mc_server)
                    elif msg.get("mode") == "keep alive":
                        if not title_compatible:
                            self.send_server_cmd("say Host app closed.")
                            self.send_server_cmd("say Players cannot close the server.")
                        else:
                            self.send_server_cmd('title @a subtitle {"text": "Host app closed", "color": "white"}')
                            self.send_server_cmd('title @a title {"text": ""}')
                            self.send_server_cmd("say Players cannot close the server.")
                        self._ui_disconnection.set()
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
            print(f"Handler error: {type(e).__name__}: {e!r}")
            raise
        finally:
            if not self._ui_disconnection.is_set():
                self._shutdown_event.set()
            
            if self._client is wsocket:
                self._client = None
    
    async def startup(self):
        async with websockets.serve(self.handler, self.host, self.port):
            print(f"Supervisor listening on ws://{self.host}:{self.port}")
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
        if self._client is not None:
            await self._client.close()
        
        print("Total shutdown complete")


class SupervisorConnector:
    def __init__(self, msg_queue: queue.Queue, log_output_queue: queue.Queue, server_stopped_signal):
        self.msg_queue = msg_queue
        self.log_output_queue = log_output_queue
        self.server_stopped_signal = server_stopped_signal
        self._client: websockets.ClientConnection | None = None
        self.found_connection = threading.Event()
        self.spooling_up = threading.Event()
        self.loading_chunks = threading.Event()
        self.loading_complete = threading.Event()
        self.failed_to_load = threading.Event()
        self.closing_server = threading.Event()

    def connected(self):
        return self._client is not None
    
    async def close(self):
        if self._client is None:
            return
        
        print("Closing now")
        ws = self._client
        self._client = None
        try:
            await ws.close()
        except Exception:
            pass

    async def connect(self):
        self.failed_to_load.clear()
        self.found_connection.clear()
        print("Attempting connection")
        if self._client:
            print("Already connected")
            return True

        uri = "ws://127.0.0.1:5675"

        try:
            wsocket = await websockets.connect(uri)
            print("Connected")
            await wsocket.send(json.dumps({"type": "handshake", "token": "dominion"}))
            print("Sent handshake")

            response: dict = json.loads(await wsocket.recv())
            if response.get("type") != "handshake_ok":
                print("Incorrect handshake message")
                self.failed_to_load.set()
                return False

            self._client = wsocket
            self.found_connection.set()
            asyncio.create_task(self.handler())
            await wsocket.send(json.dumps({"type": "loaded_status"}))
            print("Sent loaded status request")
            return True
        except Exception as e:
            print("Failed to connect")
            print(e)
            self.failed_to_load.set()
            return False
    
    async def handler(self):
        try:
            async for raw in self._client:
                msg: dict = json.loads(raw)
                print("UI Received:", msg)
                if msg.get("type") == "loading":
                    state = msg.get("state")
                    if state == "chunks" and not self.loading_chunks.is_set():
                        self.loading_chunks.set()
                        self.msg_queue.put("Generating chunks...")
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


def create_supervisor():
    supervisor = Supervisor("127.0.0.1", 5675, "dominion")
    asyncio.run(supervisor.startup())