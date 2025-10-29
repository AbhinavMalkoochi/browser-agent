from websockets.asyncio.client import connect
import asyncio, json
from typing import Dict
from dom.main import get_dom

import websockets
class CDPClient:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.message_id = 1
        self.pending_message: Dict[int, asyncio.Future] = {}
        self.ws = None

    async def connect(self):
        self.ws = await connect(self.ws_url)
        asyncio.create_task(self.listen())

    async def send(self, method, params=None):
        self.message_id += 1
        future = asyncio.Future()
        self.pending_message[self.message_id] = future
        await self.ws.send(
            json.dumps({"id": self.message_id, "method": method, "params": params or {}})
        )
        res = await future
        return res.get("result")
    async def listen(self):
        try:
            while True:
                if not self.ws:
                    break
                raw = await self.ws.recv()
                data = json.loads(raw)
                if "id" in data and data["id"] in self.pending_message:
                    future = self.pending_message.pop(data["id"])
                    if not future.done():
                        if "error" in data:
                            print("error")
                        else:
                            future.set_result(data["result"])
                    else:
                        print("dup req")
                elif "method" in data:
                    method = data["method"]
                    params = data.get("params",{})
                    sessionID=data.get("sessionId")
                    #handle events
                else:
                    print("unknown error")
        except websockets.exceptions.ConnectionClosed as e:
                print(f"WebSocket connection closed: {e}")
                for future in self.pending_message.values():
                    if not future.done():
                        future.set_exception(ConnectionError("WebSocket connection closed"))
                self.pending_message.clear()
        except Exception as e:
            print(f"Error in message handler: {e}")
            for future in self.pending_message.values():
                if not future.done():
                    future.set_exception(e)
            self.pending_message.clear()            


async def main():
    cdp = CDPClient(
        "ws://127.0.0.1:9222/devtools/page/774356D7C98129A1BB6580024E5DEC91"
    )
    await cdp.connect()
    await cdp.send("Page.enable", {})
    await cdp.send("Runtime.enable", {})
    await cdp.send("DOM.enable", {})
    await cdp.send("Page.navigate", {"url": "https://enkymarketing.com"})
    await asyncio.sleep(2)
    dom, snapshot, ax, metrics = await get_dom(cdp)


asyncio.run(main())
