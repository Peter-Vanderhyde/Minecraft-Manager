from PyQt6.QtCore import QObject, pyqtSignal
import asyncio
import websockets
import json
import queue
import html


class MgmtBus(QObject):
    connected = pyqtSignal(bool)
    log = pyqtSignal(str)
    recvd_result = pyqtSignal(object)
    server_closing = pyqtSignal()
    server_closed = pyqtSignal()
    set_players = pyqtSignal(list)
    player_join = pyqtSignal(dict)
    player_leave = pyqtSignal(dict)
    update_status = pyqtSignal(list)

    close_server = pyqtSignal()
    op_player = pyqtSignal(str, bool)
    enable_whitelist = pyqtSignal(bool)
    whitelist_player = pyqtSignal(str, bool)
    kick_player = pyqtSignal(str)
    ban_player = pyqtSignal(str)
    notify_player = pyqtSignal(str, str)
    msg_player = pyqtSignal(str, str)
    view_distance = pyqtSignal(int)
    simulation_distance = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.close_server.connect(self.send_close)
        self.op_player.connect(self.send_op)
        self.enable_whitelist.connect(self.send_whitelist_enable)
        self.whitelist_player.connect(self.send_whitelist)
        self.kick_player.connect(self.send_kick)
        self.ban_player.connect(self.send_ban)
        self.notify_player.connect(self.send_notification_to_player)
        self.msg_player.connect(self.send_message_to_player)
        self.view_distance.connect(self.send_view_distance)
        self.simulation_distance.connect(self.send_simulation_distance)
        self.cmd_queue = queue.Queue()
        self._shutdown = asyncio.Event()
    
    def shutdown(self):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(self._shutdown.set)
            else:
                pass
        except RuntimeError:
            pass

        # Sentinal that breaks the sender thread's waiting for cmds
        self.cmd_queue.put(None)

    def return_error(self, msg):
        self.log.emit(f"<font color='red'>{msg}</font>")

    def run_mgmt_listener_client(self, ip, port):
        try:
            asyncio.run(self.mgmt_listener_worker(ip, port))
        except Exception as e:
            self.return_error(f"run_mgmt_listener_client raised exception: {e!r}")
    
    def run_mgmt_sender_client(self, ip, port):
        try:
            asyncio.run(self.mgmt_sender_worker(ip, port))
        except Exception as e:
            self.return_error(f"run_mgmt_sender_client raised exception: {e!r}")
    
    async def _listen(self, ws):
        try:
            async for raw in ws:
                received = json.loads(raw)
                self.handle_received(received)
        except asyncio.CancelledError:
            # Task was cancelled by the outer race — normal during shutdown
            raise
        except websockets.ConnectionClosedOK:
            # Normal close with a frame — let outer layer handle final logging if it wants
            return
        except websockets.ConnectionClosedError:
            # Abrupt close (no frame). Normal when the server dies or process exits.
            return
        except (ConnectionResetError, OSError):
            # Windows-y “WinError 64” path. Treat as normal end.
            return
    
    async def mgmt_listener_worker(self, ip, port):
        url = f"ws://{ip}:{port}"
        time_waited = 0
        connected = False

        if not hasattr(self, "_shutdown") or self._shutdown is None:
            # shutdown() was called before this loop
            self._shutdown = asyncio.Event()

        while time_waited < 51 and not self._shutdown.is_set():
            try:
                async with websockets.connect(url) as ws:
                    connected = True
                    self.connected.emit(True)
                    listener = asyncio.create_task(self._listen(ws))
                    stopper = asyncio.create_task(self._shutdown.wait())
                    done, pending = await asyncio.wait({listener, stopper}, return_when=asyncio.FIRST_COMPLETED)
                    for task in pending:
                        task.cancel()
                    if self._shutdown.is_set():
                        try:
                            await ws.close()
                        except Exception:
                            pass
                        break
            except websockets.ConnectionClosed:
                self.server_closed.emit()
                return
            except ConnectionRefusedError:
                if connected:
                    self.server_closed.emit()
                    return
                await asyncio.sleep(3.0)
                time_waited += 3
                if time_waited == 9:
                    self.log.emit("Attempting to connect to server websocket...")
                elif time_waited == 21:
                    self.log.emit("Attempting connection for 30 more seconds...")
        
        if not self._shutdown.is_set():
            self.return_error("Timed out waiting for server to respond.")
            self.connected.emit(False)
    
    async def mgmt_sender_worker(self, ip, port):
        url = f"ws://{ip}:{port}"
        loop = asyncio.get_running_loop()
        time_waited = 0

        while time_waited < 51 and not self._shutdown.is_set():
            try:
                async with websockets.connect(url) as ws:
                    while not self._shutdown.is_set():
                        cmd = await loop.run_in_executor(None, self.cmd_queue.get)
                        if cmd is None or self._shutdown.is_set():
                            try:
                                await ws.close()
                            except Exception:
                                pass
                            return
                        await ws.send(json.dumps(cmd))
            except websockets.ConnectionClosed:
                return
            except ConnectionRefusedError:
                await asyncio.sleep(2.0)
                time_waited += 2
    
    def handle_received(self, recvd):
        def append_log(text, fg=None, bg=None):
            safe = html.escape(text).replace("\n", "<br>")
            if fg or bg:
                style = []
                if fg: style.append(f"color:{fg}")
                if bg: style.append(f"background-color:{bg}")
                style.append(f"padding:2px 6px")
                style.append("margin:2px 0")
                self.log.emit(f"<span style=\"{';'.join(style)}\">{safe}</span>")
            else:
                self.log.emit(safe)
        
        if "error" in recvd:
            self.return_error(f"Error: {recvd["error"].get("data") or recvd["error"].get("message")}")
        elif "result" in recvd:
            self.recvd_result.emit(recvd["result"])
        elif "method" in recvd:
            if "notification" in recvd["method"]:
                notification = recvd["method"].removeprefix("notification:")
                topic, action = notification.split("/")
                params = [] if "params" not in recvd else recvd["params"]
                if topic == "server":
                    if action == "status":
                        if "players" in params[0]:
                            self.set_players.emit(params[0]["players"])
                        else:
                            self.set_players.emit([])
                        
                        status = params[0]["started"]
                        version = params[0]["version"]["name"]
                        self.update_status.emit([status, version])
                    elif action == "stopping":
                        self.server_closing.emit()
                elif topic == "players":
                    if action == "joined":
                        self.player_join.emit(params[0])
                    elif action == "left":
                        self.player_leave.emit(params[0])
                elif topic == "operators":
                    if action == "added":
                        append_log(f"{params[0]['player']['name']} was given operator status.", "#ffffff", "#3b5998")
                    elif action == "removed":
                        append_log(f"{params[0]['player']['name']} lost operator status.", "#ffffff", "#a54040")
                elif topic == "allowlist":
                    if action == "added":
                        append_log(f"{params[0]['name']} was added to the whitelist.", "#ffffff", "#3b5998")
                    elif action == "removed":
                        append_log(f"{params[0]['name']} was removed from the whitelist.", "#ffffff", "#a54040")
                elif topic == "bans":
                    if action == "added":
                        append_log(f"{params[0]['player']['name']} was banned from the server.", "#ffffff", "#a54040")
                    elif action == "removed":
                        append_log(f"{params[0]['name']} was pardoned from their ban.", "#ffffff", "#3b5998")
        else:
            self.return_error(f"Unknown Data Received: {recvd}")
    
    def assemble_data(self, method, *args):
        data = {"jsonrpc":"2.0", "id":2, "method":method}
        if args:
            data["params"] = list(args)
        
        self.cmd_queue.put(data)

    def send_close(self):
        self.assemble_data("minecraft:server/stop")
    
    def send_op(self, name, remove=False):
        if not remove:
            self.assemble_data(f"minecraft:operators/add", [{"player": {"name": name}}])
        else:
            self.assemble_data(f"minecraft:operators/remove", [{"name": name}])
    
    def send_whitelist_enable(self, enable):
        self.assemble_data(f"minecraft:serversettings/use_allowlist/set", enable)
    
    def send_whitelist(self, name, remove=False):
        command = "add" if not remove else "remove"
        self.assemble_data(f"minecraft:allowlist/{command}", [{"name": name}])
    
    def send_kick(self, name):
        self.assemble_data(f"minecraft:players/kick", {"players": [{"name": name}], "message": {"literal": "You have been kicked? What were you doing?!"}})
    
    def send_ban(self, name):
        self.assemble_data(f"minecraft:bans/add", [{"player": {"name": name}, "reason": "You done messed up."}])
    
    def send_notification_to_player(self, name, msg):
        self.assemble_data(f"minecraft:server/system_message", {"receiving_players": [{"name": name}], "message": {"literal": msg}, "overlay": True})
    
    def send_message_to_player(self, name, msg):
        self.assemble_data(f"minecraft:server/system_message", {"receiving_players": [{"name": name}], "message": {"literal": msg}, "overlay": False})
    
    def send_view_distance(self, distance):
        self.assemble_data(f"minecraft:serversettings/view_distance/set", distance)
    
    def send_simulation_distance(self, distance):
        self.assemble_data(f"minecraft:serversettings/simulation_distance/set", distance)