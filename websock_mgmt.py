from PyQt6.QtCore import QObject, pyqtSignal
import asyncio
import websockets
import json
import queue


class MgmtBus(QObject):
    connected = pyqtSignal(bool)
    log = pyqtSignal(str)
    recvd_result = pyqtSignal(bool, list, str, dict)
    server_closed = pyqtSignal()
    set_players = pyqtSignal(list)
    player_join = pyqtSignal(dict)
    player_leave = pyqtSignal(dict)
    update_status = pyqtSignal(list)

    close_server = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.close_server.connect(self.send_close)
        self.cmd_queue = queue.Queue()

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
    
    async def mgmt_listener_worker(self, ip, port):
        url = f"ws://{ip}:{port}"
        time_waited = 0

        while time_waited < 81:
            try:
                with websockets.connect(url) as ws:
                    self.connected.emit(True)
                    async for raw in ws:
                        received = json.loads(raw)
                        self.handle_received(received)
            except websockets.ConnectionClosed:
                self.server_closed.emit()
                return
            except ConnectionRefusedError:
                asyncio.sleep(3.0)
                time_waited += 3
                if time_waited == 9:
                    self.log.emit("Attempting to connect to server websocket...")
                elif time_waited == 21:
                    self.log.emit("Attempting connection for 60 more seconds...")
        
        self.return_error("Timed out waiting for server to respond.")
        self.connected.emit(False)
    
    async def mgmt_sender_worker(self, ip, port):
        url = f"ws://{ip}:{port}"
        time_waited = 0

        while time_waited < 10:
            try:
                with websockets.connect(url) as ws:
                    while True:
                        cmd = await self.cmd_queue.get()
                        await ws.send(json.dumps(cmd))

                        while not self.cmd_queue.empty():
                            cmd = await self.cmd_queue.get()
                            await ws.send(json.dumps(cmd))
            except websockets.ConnectionClosed:
                return
            except ConnectionRefusedError:
                asyncio.sleep(2.0)
                time_waited += 2
    
    def handle_received(self, recvd):
        if "error" in recvd:
            self.return_error(f"Error: {recvd["error"]["data"]}")
        elif "result" in recvd:
            self.recvd_result.emit(recvd["result"])
        elif "method" in recvd:
            if "notification" in recvd["method"]:
                notification = recvd["method"].removeprefix("notification:")
                topic, action = notification.split("/")
                params = recvd["params"]
                if topic == "server":
                    if action == "status":
                        if "players" in params:
                            self.set_players.emit(params["players"])
                        else:
                            self.set_players.emit([])
                        
                        status = params["started"]
                        version = params["version"]["name"]
                        self.update_status.emit([status, version])
        else:
            self.return_error(f"Unknown Data Received: {recvd}")
    
    def assemble_data(self, method, *args):
        data = {"jsonrpc":"2.0", "id":2, "method":method}
        if args:
            data["params"] = list(args)
        
        self.cmd_queue.put(data)

    def send_close(self):
        self.assemble_data("minecraft:server/stop")