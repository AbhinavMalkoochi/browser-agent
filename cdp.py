from websockets.asyncio.client import connect
import asyncio, json

class CDPClient:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.message_id = 1
        self.pending_message = {}
        self.ws = None

    async def connect(self):
        self.ws = await connect(self.ws_url)
        asyncio.create_task(self.listen())

    async def send(self, method, params=None):
        msg_id = self.message_id
        self.message_id += 1
        future = asyncio.Future()
        self.pending_message[msg_id] = future
        await self.ws.send(json.dumps({
            "id": msg_id,
            "method": method,
            "params": params or {}
        }))
        res = await future
        return res.get("result")

    async def listen(self):
        async for message in self.ws:
            data = json.loads(message)
            if "id" in data:
                msg_id = data["id"]
                if msg_id in self.pending_message:
                    self.pending_message[msg_id].set_result(data)
            else:
                print(f"🔔 Event: {data.get('method')}")

async def main():
    cdp = CDPClient("ws://127.0.0.1:9222/devtools/page/774356D7C98129A1BB6580024E5DEC91")
    await cdp.connect()

    await cdp.send("Page.enable", {})
    result = await cdp.send("Page.navigate", {"url": "https://news.ycombinator.com"})
    print(f"Navigated: {result}")

    await asyncio.sleep(3)  

asyncio.run(main())
