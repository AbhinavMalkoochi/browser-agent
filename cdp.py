"""
CDP Client - Chrome DevTools Protocol WebSocket client for browser automation.
"""
import asyncio
import json
from typing import Dict, Optional, TYPE_CHECKING, Set, cast

if TYPE_CHECKING:
    from targets import TargetInfo
import httpx
import websockets
from websockets.asyncio.client import connect

from dom.main import get_dom
from enhanced_merger import BrowserDataMerger, EnhancedNode
from targets import SessionManager, SessionStatus

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
        self._network_activity: Dict[str, Dict[str, object]] = {}
        self._frame_load_states: Dict[str, bool] = {}
        self._frame_last_update: Dict[str, float] = {}
        self._lifecycle_enabled_sessions: Set[str] = set()
        self._main_frames: Dict[str, str] = {}

    def _now(self) -> float:
        return asyncio.get_running_loop().time()

    def _get_network_state(self, session_id: str) -> Dict[str, object]:
        state = self._network_activity.get(session_id)
        if state is None:
            state = {"inflight": set(), "last_activity": self._now()}
            self._network_activity[session_id] = state
        return state

    def _mark_frame_loading(self, frame_id: Optional[str]):
        if not frame_id:
            return
        timestamp = self._now()
        self._frame_load_states[frame_id] = False
        self._frame_last_update[frame_id] = timestamp

    def _mark_frame_loaded(self, frame_id: Optional[str]):
        if not frame_id:
            return
        timestamp = self._now()
        self._frame_load_states[frame_id] = True
        self._frame_last_update[frame_id] = timestamp

    def _clear_frame_tracking(self, frame_id: Optional[str]):
        if not frame_id:
            return
        self._frame_load_states.pop(frame_id, None)
        self._frame_last_update.pop(frame_id, None)

    def _frames_pending_load(self, session_id: str) -> Set[str]:
        pending: Set[str] = set()
        for frame_id, frame in self.registry.frames.items():
            if frame.session_id != session_id:
                continue
            if not self._frame_load_states.get(frame_id):
                pending.add(frame_id)
        return pending

    def _are_frames_loaded(self, session_id: str) -> bool:
        for frame_id, frame in self.registry.frames.items():
            if frame.session_id != session_id:
                continue
            if not self._frame_load_states.get(frame_id):
                return False
        return True

    def _is_network_idle(self, session_id: str, idle_threshold: float, now: float) -> bool:
        state = self._network_activity.get(session_id)
        if not state:
            return True
        inflight = cast(Set[str], state["inflight"])
        if inflight:
            return False
        last_activity = cast(float, state["last_activity"])
        return now - last_activity >= idle_threshold

    def _handle_request_will_be_sent(self, session_id: str, params: Dict[str, object]):
        state = self._get_network_state(session_id)
        request_id = params.get("requestId")
        if request_id:
            inflight = cast(Set[str], state["inflight"])
            inflight.add(str(request_id))
        state["last_activity"] = self._now()

    def _handle_request_finished(self, session_id: str, params: Dict[str, object]):
        state = self._get_network_state(session_id)
        request_id = params.get("requestId")
        if request_id:
            inflight = cast(Set[str], state["inflight"])
            inflight.discard(str(request_id))
        state["last_activity"] = self._now()

    async def _prepare_for_load_wait(self, session_id: str):
        if not self.registry.is_domain_enabled(session_id, "Page"):
            await self.enable_domains(["Page"], session_id)
        if not self.registry.is_domain_enabled(session_id, "Network"):
            await self.enable_domains(["Network"], session_id)
        if session_id not in self._lifecycle_enabled_sessions:
            try:
                await self.send("Page.setLifecycleEventsEnabled", {"enabled": True}, session_id=session_id)
            except Exception:
                pass
            else:
                self._lifecycle_enabled_sessions.add(session_id)
        state = self._get_network_state(session_id)
        inflight = cast(Set[str], state["inflight"])
        inflight.clear()
        state["last_activity"] = self._now()
        for frame_id, frame in self.registry.frames.items():
            if frame.session_id == session_id:
                self._mark_frame_loading(frame_id)

    async def _is_document_ready(self, session_id: str) -> bool:
        result = await self.send(
            "Runtime.evaluate",
            {"expression": "document.readyState", "returnByValue": True},
            session_id=session_id,
        )
        ready_state = result.get("result", {}).get("value")
        if isinstance(ready_state, str):
            return ready_state == "complete"
        return False

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
        session_id = data.get("sessionId")  # Events from sessions include this
        
        if method == "Target.attachedToTarget":
            session_id = params.get("sessionId")
            target_info = params.get("targetInfo", {})
            target_id = target_info.get("targetId")
            target_url = target_info.get("url", "")
            
            if session_id and target_id:
                self.registry.add_target(
                    target_id=target_id,
                    type=target_info.get("type", "unknown"),
                    url=target_url,
                    title=target_info.get("title", ""),
                    browser_context_id=target_info.get("browserContextId")
                )
                self.registry.add_session(session_id, target_id)
                
                self._map_target_to_frames(target_id, target_url, session_id)
        
        elif method == "Target.detachedFromTarget":
            session_id = params.get("sessionId")
            if session_id:
                self.registry.mark_session_disconnected(session_id)
        
        elif method == "Target.targetCreated":
            target_info = params.get("targetInfo", {})
            target_id = target_info.get("targetId")
            target_url = target_info.get("url", "")
            
            self.registry.add_target(
                target_id=target_id,
                type=target_info.get("type", "unknown"),
                url=target_url,
                title=target_info.get("title", ""),
                browser_context_id=target_info.get("browserContextId")
            )
            
            if target_info.get("type") == "page" and target_info.get("url"):
                self._map_target_to_frames(target_id, target_url, None)
        
        elif method == "Target.targetDestroyed":
            target_id = params.get("targetId")
            if target_id:
                target = self.registry.get_target(target_id)
                if target and target.session_id:
                    self.registry.mark_session_disconnected(target.session_id)
        elif method == "Page.frameAttached":
            frame_id = params.get("frameId")
            parent_frame_id = params.get("parentFrameId")
            
            if not frame_id:
                return
            
            parent_frame = self.registry.get_frame(parent_frame_id) if parent_frame_id else None
            
            if parent_frame:
                target_id = parent_frame.target_id
                frame_session_id = parent_frame.session_id or session_id
            else:
                target_id = None
                frame_session_id = session_id or self.registry.get_active_session()
            
            self.registry.add_frame(
                frame_id=frame_id,
                parent_frame_id=parent_frame_id,
                url="",
                origin="",
                target_id=target_id,
                session_id=frame_session_id
            )
            
            self._mark_frame_loading(frame_id)
        
        elif method == "Page.frameNavigated":
            frame_data = params.get("frame")
            if not frame_data:
                return
            
            frame_id = frame_data.get("id")
            url = frame_data.get("url", "")
            origin = frame_data.get("securityOrigin", "")
            
            if not frame_id:
                return
            
            if session_id and not frame_data.get("parentId"):
                self._main_frames[session_id] = frame_id
            self._mark_frame_loading(frame_id)
            
            frame = self.registry.get_frame(frame_id)
            if frame:
                frame.url = url
                frame.origin = origin
                
                if frame.parent_frame_id:
                    parent = self.registry.get_frame(frame.parent_frame_id)
                    if parent and origin != parent.origin and origin:
                        target = self.registry.find_target_by_origin(origin)
                        if target and target.session_id:
                            frame.target_id = target.target_id
                            frame.session_id = target.session_id
            else:
                parent_frame_id = None
                frame_session_id = session_id or self.registry.get_active_session()
                session_info = self.registry.get_session(frame_session_id) if frame_session_id else None
                target_id = session_info.target_id if session_info else None
                
                self.registry.add_frame(
                    frame_id=frame_id,
                    parent_frame_id=parent_frame_id,
                    url=url,
                    origin=origin,
                    target_id=target_id,
                    session_id=frame_session_id
                )
        
        elif method == "Page.frameDetached":
            frame_id = params.get("frameId")
            if frame_id:
                self._clear_frame_tracking(frame_id)
                self.registry.remove_frame(frame_id)
        
        elif method == "Page.frameStartedLoading":
            frame_id = params.get("frameId")
            self._mark_frame_loading(frame_id)
        
        elif method == "Page.frameStoppedLoading":
            frame_id = params.get("frameId")
            self._mark_frame_loaded(frame_id)
        
        elif method == "Page.loadEventFired":
            if session_id and session_id in self._main_frames:
                self._mark_frame_loaded(self._main_frames[session_id])
        
        elif method == "Network.requestWillBeSent":
            if session_id:
                self._handle_request_will_be_sent(session_id, params)
        
        elif method in ("Network.loadingFinished", "Network.loadingFailed"):
            if session_id:
                self._handle_request_finished(session_id, params)
        
        elif method.startswith("Page."):
            pass
    
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
    async def get_frame_tree(self, session_id: Optional[str] = None):
        """
        Collect frame tree from a session and store frames in registry.
        
        This recursively parses the frame tree structure from Page.getFrameTree
        and stores all frames with their parent-child relationships.
        """
        if session_id is None:
            session_id = self.registry.get_active_session()
            if session_id is None:
                raise RuntimeError("No active session available")
        
        if not self.registry.is_domain_enabled(session_id, "Page"):
            await self.enable_domains(["Page"], session_id)
        
        result = await self.send("Page.getFrameTree", session_id=session_id)
        frame_tree = result.get("frameTree")
        
        if not frame_tree:
            return
        
        session_info = self.registry.get_session(session_id)
        target_id = session_info.target_id if session_info else None
        
        self._parse_frame_tree(frame_tree, parent_frame_id=None, target_id=target_id, session_id=session_id)
    
    def _parse_frame_tree(self, frame_tree_node: dict, parent_frame_id: Optional[str], 
                         target_id: Optional[str], session_id: str):
        """
        Recursively parse a frame tree node and its children.
        
        frame_tree_node structure:
        {
          "frame": {
            "id": "...",
            "url": "...",
            "securityOrigin": "...",
            ...
          },
          "childFrames": [...]
        }
        """
        frame_data = frame_tree_node.get("frame", {})
        if not frame_data:
            return
        
        frame_id = frame_data.get("id")
        if not frame_id:
            return
        
        url = frame_data.get("url", "")
        origin = frame_data.get("securityOrigin", "")
        
        child_target_id = target_id
        child_session_id = session_id
        
        if parent_frame_id:
            parent_frame = self.registry.get_frame(parent_frame_id)
            if parent_frame:
                parent_origin = parent_frame.origin
                is_cross_origin = origin != parent_origin and origin != "" and parent_origin != ""
                
                if is_cross_origin:
                    target = self._find_target_for_cross_origin_frame(url, origin)
                    if target and target.session_id:
                        child_target_id = target.target_id
                        child_session_id = target.session_id
        
        self.registry.add_frame(
            frame_id=frame_id,
            parent_frame_id=parent_frame_id,
            url=url,
            origin=origin,
            target_id=child_target_id,
            session_id=child_session_id
        )
        
        child_frames = frame_tree_node.get("childFrames", [])
        for child_frame_tree in child_frames:
            self._parse_frame_tree(
                child_frame_tree,
                parent_frame_id=frame_id,
                target_id=child_target_id,
                session_id=child_session_id
            )
    
    def _find_target_for_cross_origin_frame(self, url: str, origin: str):
        """Find the target that corresponds to a cross-origin frame."""
        target = self.registry.find_target_by_url(url)
        if target:
            return target
        
        target = self.registry.find_target_by_origin(origin)
        if target:
            return target
        
        return None
    
    def _map_target_to_frames(self, target_id: str, target_url: str, session_id: Optional[str]):
        """
        Map a target to any frames that match it by URL or origin.
        
        This is called:
        1. When Target.attachedToTarget fires (with session_id)
        2. When Target.targetCreated fires (session_id may be None, will be set later)
        """
        if not target_url:
            return
        
        target_origin = self.registry._extract_origin_from_url(target_url)
        
        for frame_id, frame in self.registry.frames.items():
            if frame.target_id is None or frame.target_id != target_id:
                frame_matches = (
                    frame.url == target_url or
                    target_url.startswith(frame.url) or
                    frame.url.startswith(target_url) or
                    (frame.origin and frame.origin == target_origin)
                )
                
                if frame_matches:
                    if session_id:
                        self.registry.update_frame_target_mapping(frame_id, target_id, session_id)
                    else:
                        frame.target_id = target_id
    async def wait_for_load(
        self,
        session_id: Optional[str] = None,
        timeout: float = 15.0,
        network_idle_threshold: float = 0.5,
        check_interval: float = 0.1,
    ):
        if session_id is None:
            session_id = self.registry.get_active_session()
        if session_id is None:
            raise RuntimeError("No active session available")

        await self._prepare_for_load_wait(session_id)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        ready_state_complete = False

        while True:
            now = loop.time()
            if now >= deadline:
                state = self._get_network_state(session_id)
                inflight = len(cast(Set[str], state["inflight"]))
                pending_frames = list(self._frames_pending_load(session_id))
                raise TimeoutError(
                    f"Page load timed out after {timeout} seconds "
                    f"(pending_frames={pending_frames}, inflight_requests={inflight})"
                )

            if not ready_state_complete:
                try:
                    ready_state_complete = await self._is_document_ready(session_id)
                except Exception:
                    ready_state_complete = False

            network_idle = self._is_network_idle(session_id, network_idle_threshold, now)
            frames_loaded = self._are_frames_loaded(session_id)

            if ready_state_complete and network_idle and frames_loaded:
                return

            await asyncio.sleep(check_interval)
            
    async def collect_all_frame_trees(self):
        """
        Collect frame trees from all active sessions.
        
        This should be called after page load to discover all frames,
        including cross-origin iframes that have their own sessions.
        """
        for session_id, session_info in self.registry.sessions.items():
            if session_info.status == SessionStatus.ACTIVE:
                try:
                    await self.get_frame_tree(session_id=session_id)
                except Exception:
                    pass
    def get_session_for_node(self,node:dict)->Optional[str]:
        frame_id = node.get('frameId')
        if not frame_id:
            return self.registry.get_active_session()
        return self.registry.get_session_from_frame(frame_id)
    async def interact(self,node:EnhancedNode):
        session_id = self.registry.get_session_from_frame(node.frame_id)

        self.send("Some Action",{},session_id=session_id)
async def test_frame_events():
    """Test function specifically for frame events."""
    ws_url = await get_page_ws_url()
    cdp = CDPClient(ws_url)
    await cdp.connect()
    
    active_session = cdp.registry.get_active_session()
    if active_session:
        if not cdp.registry.is_domain_enabled(active_session, "Page"):
            await cdp.enable_domains(["Page"], active_session)
    
    test_url = """data:text/html,
<!DOCTYPE html>
<html>
<head><title>Frame Test</title></head>
<body>
    <h1>Frame Events Test</h1>
    <div id="container"></div>
    <script>
        function addIframe() {
            const iframe = document.createElement('iframe');
            iframe.src = 'https://example.com';
            iframe.style.width = '100%';
            iframe.style.height = '300px';
            iframe.style.border = '1px solid black';
            document.getElementById('container').appendChild(iframe);
        }
        setTimeout(addIframe, 2000);
        setTimeout(addIframe, 4000);
    </script>
</body>
</html>
"""
    
    await cdp.send("Page.navigate", {"url": test_url})
    await cdp.wait_for_load(session_id=active_session, timeout=15.0)

async def get_enhanced_elements() -> list:
    """Get enhanced actionable elements from a webpage."""
    ws_url = await get_page_ws_url()
    cdp = CDPClient(ws_url)
    await cdp.connect()
    # await cdp.get_frame_tree()    
    # # Navigate and wait for load
    await cdp.send("Page.navigate", {"url": "http://localhost:8000/test_frame_events.html"})
    await cdp.wait_for_load(timeout=15.0)
    
    # # Get raw DOM data
    # dom_data = await get_dom(cdp)
    
    # # Process with enhanced merger
    # merger = BrowserDataMerger()
    # enhanced_nodes = merger.merge_browser_data(
    #     dom_data['dom'],
    #     dom_data['snapshot'], 
    #     dom_data['ax'],
    #     dom_data['metrics']
    # )
    
    # return enhanced_nodes


if __name__ == "__main__":
    async def main():
        # Test frame events
        await test_frame_events()
        
        # Or use normal flow:
        # enhanced_nodes = await get_enhanced_elements()
        # print(f"🎯 Found {len(enhanced_nodes)} actionable elements:")
        # for i, node in enumerate(enhanced_nodes[:5], 1):
        #     print(f"{i}. {node.tag_name.upper()} '{node.ax_name or node.text_content[:30]}'")
        #     print(f"   Click: {node.click_point}, Confidence: {node.confidence_score:.2f}")
    
    asyncio.run(main())
