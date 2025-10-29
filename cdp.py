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
    await cdp.send("Runtime.enable", {})
    await cdp.send("DOM.enable", {})
    await cdp.send("Page.navigate", {"url": "https://enkymarketing.com"})
    await asyncio.sleep(2)
    
    visible_elements = await cdp.send("Runtime.evaluate", {
        "expression": """
        (() => {
        const rect = el => el.getBoundingClientRect();
        const isVisible = el => {
            const r = rect(el);
            return !!(r.width && r.height && r.bottom >= 0 && r.right >= 0 &&
                    r.top <= window.innerHeight && r.left <= window.innerWidth) &&
                getComputedStyle(el).visibility !== 'hidden' &&
                getComputedStyle(el).display !== 'none';
        };
        return Array.from(document.querySelectorAll('*'))
            .filter(isVisible)
            .map(el => ({
            tag: el.tagName.toLowerCase(),
            id: el.id,
            cls: el.className,
            rect: rect(el).toJSON(),
            text: el.innerText.slice(0, 100)
            }));
        })()
        """,
        "returnByValue": True
    })
    elements = visible_elements["result"]["value"]
    print(f"Found {len(elements)} visible elements")
    print(elements[:5])


asyncio.run(main())
