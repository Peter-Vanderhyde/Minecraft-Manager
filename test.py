import asyncio
import websockets
import json
from aioconsole import ainput

players = []

def log(msg):
    print("Log:", msg)

def error(msg):
    print("Error:", msg)

def updatePlayers(players):
    log("Setting players to " + str(players))

def handle_response(response):
    response = json.loads(response)
    # print(response)
    if "result" in response:
        result = response["result"]
        if type(result) not in [list, dict]:
            log(str(result))
        elif "methods" in result:
            # schemas = result["components"]["schemas"]
            # print(json.dumps(schemas, indent=2))
            # print(json.dumps(schemas.get("player"), indent=2))
            # print(json.dumps(result["methods"], indent=2))
            for method in result["methods"]:
                for key, value in method.items():
                    print(key + ": " + str(value))
                print()
        else:
            log(str(result))
    elif "error" in response:
        error(response["error"]["data"])
    elif "method" in response:
        if "notification" in response["method"]:
            notification = response["method"].removeprefix("notification:")
            topic, action = notification.split("/")
            if topic == "server":
                if action == "status":
                    params = response["params"][0]
                    if "players" in params:
                        updatePlayers(params["players"])
                    if params["started"]:
                        log("Status is online")
                    else:
                        log("Status is offline")
                    log("Version " + params["version"]["name"])
                elif action == "saving":
                    log("Saving world")
                elif action == "saved":
                    log("Saved world")
            elif topic == "players":
                params = response["params"]
                if action == "joined":
                    updatePlayers(params)
                elif action == "left":
                    updatePlayers([])
    else:
        log(result)

async def listen(ws):
    try:
        async for response in ws:
            handle_response(response)
    except asyncio.TimeoutError:
        pass
    except websockets.ConnectionClosed:
        log("Server shutdown")
    except Exception as e:
        print("Listener Error:", e)

async def sendRequest(ws):
    while True:
        cmd = await ainput("")
        if cmd == "quit":
            log("Quitting...")
            break
        elif cmd == "help":
            cmd = "rpc.discover"
        
        req = {"jsonrpc":"2.0", "id":2, "method":cmd}
        if cmd == "minecraft:server/system_message":
            req = {
  "jsonrpc":"2.0","id":3,"method":"minecraft:server/system_message",
  "params":[{"receivingPlayers":[{"name":"PetergrineFalcon"}], "message": { "literal":"Action bar test!", "bold": True }, "overlay": True }]
}
        
        try:
            await ws.send(json.dumps(req))
        except websockets.ConnectionClosed:
            log("Server shutdown while sending")
            break

async def main():
    url = "ws://localhost:25585"

    async with websockets.connect(url) as ws:
        t_listener = asyncio.create_task(listen(ws))
        t_sender = asyncio.create_task(sendRequest(ws))

        done, pending = await asyncio.wait(
            {t_listener, t_sender},
            return_when=asyncio.FIRST_COMPLETED
        )

        for t in pending:
            t.cancel()
        for t in pending:
            try:
                await t
            except asyncio.CancelledError:
                pass

asyncio.run(main())