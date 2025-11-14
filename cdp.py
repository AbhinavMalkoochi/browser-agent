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
from targets import SessionManager


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
        self.registry = SessionManager()
    async def connect(self):
        """Connect to Chrome via WebSocket."""
        self.ws = await connect(self.ws_url)
        asyncio.create_task(self.listen())
        
        await self.send("Target.setAutoAttach", {
            "autoAttach": True,
            "flatten": True,
            "waitForDebuggerOnStart": False
        })
        
        targets_result = await self.send("Target.getTargets", {})
        target_infos = targets_result.get("targetInfos", [])
        
        for target_info in target_infos:
            self.registry.add_target(
                target_id=target_info["targetId"],
                type=target_info.get("type", "unknown"),
                url=target_info.get("url", ""),
                title=target_info.get("title", ""),
                browser_context_id=target_info.get("browserContextId")
            )
        
        match = next((target for target in target_infos if target.get("type") == 'page'), None)
        if not match:
            raise RuntimeError("No page target found")
        
        res = await self.send("Target.attachToTarget", {
            "targetId": match["targetId"],
            "flatten": True
        })
        session_id = res["sessionId"]
        
        self.registry.add_session(session_id, match["targetId"])
        self.registry.set_active_session(session_id)
        
        await self.enable_domains(["DOM", "Page", "Network", "Runtime"], session_id)
    async def enable_domains(self, domains, session_id: Optional[str] = None):
        """Enable CDP domains for a session."""
        if session_id is None:
            session_id = self.registry.get_active_session()
            if session_id is None:
                raise RuntimeError("No active session available")
        
        for domain in domains:
            if not self.registry.is_domain_enabled(session_id, domain):
                await self.send(f"{domain}.enable", {}, session_id=session_id)
                self.registry.mark_domain_enabled(session_id, domain)
    
    async def attach_to_target(self, target_id):
        """Attach to a target and return the session ID."""
        res = await self.send("Target.attachToTarget", {
            "targetId": target_id,
            "flatten": True
        })
        session_id = res["sessionId"]
        
        self.registry.add_session(session_id, target_id)
        self.registry.set_active_session(session_id)
        
        await self.enable_domains(["DOM", "Page", "Network", "Runtime"], session_id)
        return session_id
    async def send(self, method, params=None, session_id: Optional[str] = None):
        """Send a CDP command and wait for response."""
        self.message_id += 1
        future = asyncio.Future()
        
        s_id = session_id
        if s_id is None:
            s_id = self.registry.get_active_session()
        
        self.pending_message[self.message_id] = future
        
        message = {"id": self.message_id, "method": method, "params": params or {}}
        if s_id is not None:
            message["sessionId"] = s_id
        
        await self.ws.send(json.dumps(message))
        return await future
    
    def _handle_event(self, data: dict):
        """Handle CDP events."""
        method = data.get("method", "")
        params = data.get("params", {})
        
        if method == "Target.attachedToTarget":
            session_id = params.get("sessionId")
            target_info = params.get("targetInfo", {})
            target_id = target_info.get("targetId")
            
            if session_id and target_id:
                self.registry.add_target(
                    target_id=target_id,
                    type=target_info.get("type", "unknown"),
                    url=target_info.get("url", ""),
                    title=target_info.get("title", ""),
                    browser_context_id=target_info.get("browserContextId")
                )
                self.registry.add_session(session_id, target_id)
        
        elif method == "Target.detachedFromTarget":
            session_id = params.get("sessionId")
            if session_id:
                self.registry.mark_session_disconnected(session_id)
        
        elif method == "Target.targetCreated":
            target_info = params.get("targetInfo", {})
            self.registry.add_target(
                target_id=target_info.get("targetId"),
                type=target_info.get("type", "unknown"),
                url=target_info.get("url", ""),
                title=target_info.get("title", ""),
                browser_context_id=target_info.get("browserContextId")
            )
        
        elif method == "Target.targetDestroyed":
            target_id = params.get("targetId")
            if target_id:
                target = self.registry.get_target(target_id)
                if target and target.session_id:
                    self.registry.mark_session_disconnected(target.session_id)
    
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
                    self._handle_event(data)
                    
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
