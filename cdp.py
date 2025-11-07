#todo create a dict combining dom data w indexing
#remove hidden elements,svgs/no text/interacctivity
#find elements that are covered 
#map so that llm can say -> click button and you find the nodeId, its coords, and click - tools for llm
#convert tree to basic text
from enhanced_merger import BrowserDataMerger
from websockets.asyncio.client import connect
import asyncio, json
from typing import Dict
from dom.main import get_dom
import httpx

import websockets


async def get_page_ws_url(host="localhost", port=9222):
    """Get the WebSocket URL for the first page target"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"http://{host}:{port}/json")
        targets = response.json()
        for target in targets:
            if target.get("type") == "page":
                return target["webSocketDebuggerUrl"]
        raise RuntimeError("No page target found")
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
        return res
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
                            print(f"error: {data}")
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
    ws_url = await get_page_ws_url()
    cdp = CDPClient(ws_url)
    await cdp.connect()
    await cdp.send("Page.enable", {})
    await cdp.send("Runtime.enable", {})
    await cdp.send("DOM.enable", {})
    await cdp.send("Page.navigate", {"url": "https://enkymarketing.com"})
    await asyncio.sleep(2)
    data = await get_dom(cdp)
    for key, value in data.items():
        print(f"{key.upper()}:", json.dumps(value, indent=2))
    merger = BrowserDataMerger()
    enhanced_nodes = merger.merge_browser_data(
        data['dom'],
        data['snapshot'], 
        data['ax'],
        data['metrics']
    )
    print(f"\n🎯 ENHANCED NODES SUMMARY")
    print(f"{'='*60}")
    
    for i, node in enumerate(enhanced_nodes[:10], 1):
        print(f"\n{i}. {node.tag_name.upper()} '{node.ax_name or node.text_content[:30]}'")
        print(f"   Backend ID: {node.backend_node_id}")
        print(f"   Position: {node.bounds_css}")
        print(f"   Click Point: {node.click_point}")
        print(f"   Action: {node.action_type}")
        print(f"   Role: {node.ax_role}")
        print(f"   Confidence: {node.confidence_score:.2f}")
        print(f"   Interactive: {node.is_interactive}, Clickable: {node.is_clickable}")
    
    print(f"\n✅ Successfully processed {len(enhanced_nodes)} actionable elements!")

asyncio.run(main())
