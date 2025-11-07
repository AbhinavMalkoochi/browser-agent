"""
CDP Client - Chrome DevTools Protocol WebSocket client for browser automation.
"""
import asyncio
import json
from typing import Dict, Optional
import httpx
import websockets
from websockets.asyncio.client import connect

from dom.main import get_dom
from enhanced_merger import BrowserDataMerger


async def get_page_ws_url(host="localhost", port=9222):
    """Get the WebSocket URL for the first page target."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"http://{host}:{port}/json")
        targets = response.json()
        for target in targets:
            if target.get("type") == "page":
                return target["webSocketDebuggerUrl"]
        raise RuntimeError("No page target found")


class CDPClient:
    """Chrome DevTools Protocol WebSocket client."""
    
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.message_id = 1
        self.pending_message: Dict[int, asyncio.Future] = {}
        self.ws = None
        self.session_id=None
    async def connect(self):
        """Connect to Chrome via WebSocket."""
        self.ws = await connect(self.ws_url)
        asyncio.create_task(self.listen())
        await self.send("Target.setAutoAttach",{"autoAttach":True,"flatten":True,"waitForDebuggerOnStart":False})
        targets = await self.send("Target.getTargets",{})
        match = next((target for target in targets if target["type"]=='page'),None)
        res = await self.send("Target.attachToTarget",{"targetId":match["targetId"],"flatten":True})
        self.session_id = res["sessionId"]
        self.enable_domains(["DOM","Page","Network","Runtime"])
    async def enable_domains(self,domains):
        for domain in domains:
            await self.send(f"{domain}.enable",{},session_id=self.session_id)
    async def attach_to_target(self,target_id):
        res = await self.ws.send("Target.attachToTarget",{"targetId":target_id,"flatten":True})
        self.session_id=res["session_id"]
        self.enable_domains(["DOM","Page","Network","Runtime"])
        return self.session_id
    async def get_session_id(self,target_id):
        res = await self.send("Target.attachToTarget",{"targetId":target_id,"flatten":True})
        self.session_id = res["sessionId"]
    async def send(self, method,session_id:Optional[str], params=None ):
        """Send a CDP command and wait for response."""
        self.message_id += 1
        future = asyncio.Future()
        s_id = session_id or self.session_id
        self.pending_message[self.message_id] = future
        await self.ws.send(
            json.dumps({"id": self.message_id, "method": method, "params": params or {}, "sessionId":s_id})
        )
        return await future
    async def listen(self):
        """Listen for CDP responses and events."""
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
                            future.set_exception(Exception(f"CDP Error: {data['error']}"))
                        else:
                            future.set_result(data["result"])
                    else:
                        print("dup req")
                elif "method" in data:
                    pass
                    
        except websockets.exceptions.ConnectionClosed:
            for future in self.pending_message.values():
                if not future.done():
                    future.set_exception(ConnectionError("WebSocket connection closed"))
            self.pending_message.clear()
        except Exception as e:
            for future in self.pending_message.values():
                if not future.done():
                    future.set_exception(e)
            self.pending_message.clear()


async def get_enhanced_elements(url: str) -> list:
    """Get enhanced actionable elements from a webpage."""
    ws_url = await get_page_ws_url()
    cdp = CDPClient(ws_url)
    await cdp.connect()
    
    # Enable required domains
    await cdp.send("Page.enable", {})
    await cdp.send("Runtime.enable", {})
    await cdp.send("DOM.enable", {})
    
    # Navigate and wait for load
    await cdp.send("Page.navigate", {"url": url})
    await asyncio.sleep(2)
    
    # Get raw DOM data
    dom_data = await get_dom(cdp)
    
    # Process with enhanced merger
    merger = BrowserDataMerger()
    enhanced_nodes = merger.merge_browser_data(
        dom_data['dom'],
        dom_data['snapshot'], 
        dom_data['ax'],
        dom_data['metrics']
    )
    
    return enhanced_nodes


if __name__ == "__main__":
    async def main():
        enhanced_nodes = await get_enhanced_elements("https://enkymarketing.com")
        
        # print(f"🎯 Found {len(enhanced_nodes)} actionable elements:")
        # for i, node in enumerate(enhanced_nodes[:5], 1):
        #     print(f"{i}. {node.tag_name.upper()} '{node.ax_name or node.text_content[:30]}'")
        #     print(f"   Click: {node.click_point}, Confidence: {node.confidence_score:.2f}")
    
    asyncio.run(main())
