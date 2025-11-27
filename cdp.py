"""
CDP Client - Chrome DevTools Protocol WebSocket client for browser automation.
"""
import asyncio
import json
import logging
from typing import Dict, Optional, Set, cast, Callable, Any


import httpx
import websockets
from websockets.asyncio.client import connect

from enhanced_merger import  EnhancedNode
from targets import SessionManager, SessionStatus
from errors import (
    BrowserAgentError,
    CDPConnectionError,
    CDPTimeoutError,
    CDPProtocolError,
    CDPSessionError,
    CDPTargetError,
)

logger = logging.getLogger("browser_agent")


def setup_logging(level: int = logging.INFO, debug: bool = False):
    """Configure logging for the browser agent."""
    if debug:
        level = logging.DEBUG
    
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    handler.setFormatter(formatter)
    
    logger.setLevel(level)
    logger.addHandler(handler)
    
    if not logger.handlers:
        logger.addHandler(handler)


async def get_page_ws_url(host="localhost", port=9222):
    """Get the WebSocket URL for the first page target."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://{host}:{port}/json")
            targets = response.json()
            for target in targets:
                if target.get("type") == "page":
                    ws_url = target["webSocketDebuggerUrl"]
                    logger.debug(f"Found page target, ws_url={ws_url}")
                    return ws_url
            raise CDPTargetError(
                f"No page target found at {host}:{port}",
                method="get_page_ws_url"
            )
    except httpx.RequestError as e:
        raise CDPConnectionError(
            f"Failed to connect to Chrome at {host}:{port}",
            method="get_page_ws_url"
        ) from e


class CDPClient:
    """Chrome DevTools Protocol WebSocket client."""
    
    def __init__(self, ws_url: str, debug: bool = False):
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
        self.debug = debug
        self._retry_config = {
            "max_attempts": 3,
            "initial_delay": 0.1,
            "max_delay": 2.0,
            "backoff_multiplier": 2.0,
        }

    def _now(self) -> float:
        return asyncio.get_running_loop().time()
    
    def _is_retryable_error(self, error: Exception) -> bool:
        """Check if an error is retryable (transient)."""
        return isinstance(error, (CDPTimeoutError, CDPConnectionError))
    
    async def _with_retry(
        self,
        operation: Callable[[], Any],
        operation_name: str = "operation",
        session_id: Optional[str] = None,
    ) -> Any:
        """Execute an operation with exponential backoff retry."""
        max_attempts = self._retry_config["max_attempts"]
        initial_delay = self._retry_config["initial_delay"]
        max_delay = self._retry_config["max_delay"]
        backoff_multiplier = self._retry_config["backoff_multiplier"]
        
        delay = initial_delay
        last_error = None
        
        for attempt in range(1, max_attempts + 1):
            try:
                if self.debug:
                    logger.debug(
                        f"Attempt {attempt}/{max_attempts} for {operation_name}",
                        extra={"session_id": session_id}
                    )
                return await operation()
            except Exception as e:
                last_error = e
                if not self._is_retryable_error(e):
                    logger.warning(
                        f"{operation_name} failed with non-retryable error: {e}",
                        extra={"session_id": session_id, "error_type": type(e).__name__}
                    )
                    raise
                
                if attempt < max_attempts:
                    logger.warning(
                        f"{operation_name} failed (attempt {attempt}/{max_attempts}): {e}. "
                        f"Retrying in {delay:.2f}s...",
                        extra={"session_id": session_id, "error_type": type(e).__name__}
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * backoff_multiplier, max_delay)
                else:
                    logger.error(
                        f"{operation_name} failed after {max_attempts} attempts: {e}",
                        extra={"session_id": session_id, "error_type": type(e).__name__}
                    )
        
        raise last_error
    
    async def _ensure_session_active(self, session_id: Optional[str] = None) -> str:
        """Ensure a session is active, attempting recovery if needed."""
        if session_id is None:
            session_id = self.registry.get_active_session()
        
        if session_id is None:
            raise CDPSessionError("No active session available", method="_ensure_session_active")
        
        session_info = self.registry.get_session(session_id)
        if session_info is None:
            raise CDPSessionError(
                f"Session {session_id} not found in registry",
                session_id=session_id,
                method="_ensure_session_active"
            )
        
        if session_info.status == SessionStatus.DISCONNECTED:
            logger.info(
                f"Session {session_id} is disconnected, attempting recovery...",
                extra={"session_id": session_id}
            )
            try:
                recovered_session_id = await self._recover_session(session_id)
                logger.info(
                    f"Session recovery successful: {recovered_session_id}",
                    extra={"session_id": recovered_session_id, "old_session_id": session_id}
                )
                return recovered_session_id
            except Exception as e:
                logger.error(
                    f"Session recovery failed: {e}",
                    extra={"session_id": session_id, "error_type": type(e).__name__}
                )
                raise CDPSessionError(
                    f"Failed to recover session {session_id}",
                    session_id=session_id,
                    method="_ensure_session_active"
                ) from e
        
        return session_id
    
    async def _recover_session(self, old_session_id: str) -> str:
        """Recover a disconnected session by re-attaching to its target."""
        session_info = self.registry.get_session(old_session_id)
        if not session_info:
            raise CDPSessionError(
                f"Session {old_session_id} not found",
                session_id=old_session_id,
                method="_recover_session"
            )
        
        target_id = session_info.target_id
        
        try:
            targets_result = await self.send("Target.getTargets", {})
            target_infos = targets_result.get("targetInfos", [])
            
            target_exists = any(t.get("targetId") == target_id for t in target_infos)
            if not target_exists:
                raise CDPTargetError(
                    f"Target {target_id} no longer exists",
                    target_id=target_id,
                    session_id=old_session_id,
                    method="_recover_session"
                )
            
            res = await self.send("Target.attachToTarget", {
                "targetId": target_id,
                "flatten": True
            })
            new_session_id = res["sessionId"]
            
            self.registry.add_session(new_session_id, target_id)
            self.registry.set_active_session(new_session_id)
            
            await self.enable_domains(["DOM", "Page", "Network", "Runtime"], new_session_id)
            
            if old_session_id in self._lifecycle_enabled_sessions:
                try:
                    await self.send("Page.setLifecycleEventsEnabled", {"enabled": True}, session_id=new_session_id)
                    self._lifecycle_enabled_sessions.add(new_session_id)
                    self._lifecycle_enabled_sessions.discard(old_session_id)
                except Exception:
                    pass
            
            logger.info(
                f"Re-enabled domains for recovered session",
                extra={"session_id": new_session_id, "target_id": target_id}
            )
            
            return new_session_id
        except BrowserAgentError:
            raise
        except Exception as e:
            raise CDPSessionError(
                f"Failed to recover session: {e}",
                session_id=old_session_id,
                target_id=target_id,
                method="_recover_session"
            ) from e

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
        session_id = await self._ensure_session_active(session_id)
        
        if not self.registry.is_domain_enabled(session_id, "Page"):
            await self.enable_domains(["Page"], session_id)
        if not self.registry.is_domain_enabled(session_id, "Network"):
            await self.enable_domains(["Network"], session_id)
        if session_id not in self._lifecycle_enabled_sessions:
            try:
                await self.send("Page.setLifecycleEventsEnabled", {"enabled": True}, session_id=session_id, use_retry=False)
            except BrowserAgentError:
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
        logger.info(f"Connecting to Chrome via WebSocket: {self.ws_url}")
        
        try:
            self.ws = await connect(self.ws_url)
            logger.info("WebSocket connection established")
        except Exception as e:
            logger.error(f"Failed to establish WebSocket connection: {e}")
            raise CDPConnectionError(
                f"Failed to connect to Chrome WebSocket: {e}",
                method="connect"
            ) from e
        
        asyncio.create_task(self.listen())
        
        try:
            await self.send("Target.setAutoAttach", {
                "autoAttach": True,
                "flatten": True,
                "waitForDebuggerOnStart": False
            }, use_retry=False)
            
            targets_result = await self.send("Target.getTargets", {}, use_retry=False)
            target_infos = targets_result.get("targetInfos", [])
            
            logger.debug(f"Found {len(target_infos)} targets")
            
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
                raise CDPTargetError(
                    "No page target found after connecting",
                    method="connect"
                )
            
            res = await self.send("Target.attachToTarget", {
                "targetId": match["targetId"],
                "flatten": True
            }, use_retry=False)
            session_id = res["sessionId"]
            
            self.registry.add_session(session_id, match["targetId"])
            self.registry.set_active_session(session_id)
            
            logger.info(
                f"Attached to page target, session_id={session_id}",
                extra={"session_id": session_id, "target_id": match["targetId"]}
            )
            
            await self.enable_domains(["DOM", "Page", "Network", "Runtime","DOMSnapshot","Accessibility"], session_id)
        except BrowserAgentError:
            raise
        except Exception as e:
            logger.error(f"Error during connection setup: {e}", exc_info=True)
            raise CDPConnectionError(
                f"Failed to complete connection setup: {e}",
                method="connect"
            ) from e
    async def enable_domains(self, domains, session_id: Optional[str] = None):
        """Enable CDP domains for a session."""
        session_id = await self._ensure_session_active(session_id)
        
        for domain in domains:
            if not self.registry.is_domain_enabled(session_id, domain):
                await self.send(f"{domain}.enable", {}, session_id=session_id, use_retry=False)
                self.registry.mark_domain_enabled(session_id, domain)
                logger.debug(
                    f"Enabled domain: {domain}",
                    extra={"session_id": session_id, "domain": domain}
                )
    
    async def attach_to_target(self, target_id):
        """Attach to a target and return the session ID."""
        try:
            res = await self.send("Target.attachToTarget", {
                "targetId": target_id,
                "flatten": True
            }, use_retry=False)
            session_id = res["sessionId"]
            
            self.registry.add_session(session_id, target_id)
            self.registry.set_active_session(session_id)
            
            logger.info(
                f"Attached to target",
                extra={"session_id": session_id, "target_id": target_id}
            )
            
            await self.enable_domains(["DOM", "Page", "Network", "Runtime"], session_id)
            return session_id
        except BrowserAgentError:
            raise
        except Exception as e:
            raise CDPTargetError(
                f"Failed to attach to target {target_id}: {e}",
                target_id=target_id,
                method="attach_to_target"
            ) from e
    async def send(self, method, params=None, session_id: Optional[str] = None, use_retry: bool = True):
        """Send a CDP command and wait for response."""
        if use_retry:
            async def operation():
                return await self._send_internal(method, params, session_id)
            return await self._with_retry(
                operation,
                operation_name=f"CDP.send({method})",
                session_id=session_id,
            )
        else:
            return await self._send_internal(method, params, session_id)
    
    async def _send_internal(self, method, params=None, session_id: Optional[str] = None):
        """Internal send implementation without retry."""
        session_id = await self._ensure_session_active(session_id)
        
        self.message_id += 1
        msg_id = self.message_id
        future = asyncio.Future()
        
        self.pending_message[msg_id] = future
        
        message = {"id": msg_id, "method": method, "params": params or {}}
        if session_id is not None:
            message["sessionId"] = session_id
        
        start_time = self._now()
        
        if self.debug:
            logger.debug(
                f"CDP command: {method}",
                extra={
                    "method": method,
                    "params": params,
                    "session_id": session_id,
                    "message_id": msg_id,
                }
            )
        
        try:
            if not self.ws:
                raise CDPConnectionError(
                    "WebSocket connection not established",
                    session_id=session_id,
                    method=method,
                )
            
            await self.ws.send(json.dumps(message))
            result = await future
            
            duration = self._now() - start_time
            if self.debug:
                logger.debug(
                    f"CDP response: {method} (duration={duration:.3f}s)",
                    extra={
                        "method": method,
                        "session_id": session_id,
                        "message_id": msg_id,
                        "duration_ms": duration * 1000,
                    }
                )
            
            return result
        except asyncio.TimeoutError as e:
            duration = self._now() - start_time
            logger.error(
                f"CDP command timeout: {method} after {duration:.3f}s",
                extra={
                    "method": method,
                    "session_id": session_id,
                    "message_id": msg_id,
                    "duration_ms": duration * 1000,
                }
            )
            raise CDPTimeoutError(
                f"CDP command {method} timed out after {duration:.3f}s",
                timeout=duration,
                session_id=session_id,
                method=method,
            ) from e
        except Exception as e:
            duration = self._now() - start_time
            logger.error(
                f"CDP command error: {method} - {e}",
                extra={
                    "method": method,
                    "session_id": session_id,
                    "message_id": msg_id,
                    "duration_ms": duration * 1000,
                    "error_type": type(e).__name__,
                }
            )
            if isinstance(e, BrowserAgentError):
                raise
            raise CDPConnectionError(
                f"CDP command {method} failed: {e}",
                session_id=session_id,
                method=method,
            ) from e
    
    def _handle_event(self, data: dict):
        """Handle CDP events."""
        method = data.get("method", "")
        params = data.get("params", {})
        session_id = data.get("sessionId")  # Events from sessions include this
        
        if self.debug:
            logger.debug(
                f"CDP event: {method}",
                extra={"method": method, "session_id": session_id}
            )
        
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
                logger.info(
                    f"Target detached from session",
                    extra={"session_id": session_id}
                )
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
                    logger.info(
                        f"Target destroyed",
                        extra={"target_id": target_id, "session_id": target.session_id}
                    )
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
                            error_data = data["error"]
                            error_code = error_data.get("code")
                            error_message = error_data.get("message", "Unknown CDP error")
                            
                            logger.error(
                                f"CDP protocol error: {error_message}",
                                extra={
                                    "error_code": error_code,
                                    "error_data": error_data,
                                    "message_id": data["id"],
                                }
                            )
                            
                            future.set_exception(CDPProtocolError(
                                f"CDP Error: {error_message}",
                                code=error_code,
                                cdp_error=error_data,
                                method=data.get("method"),
                            ))
                        else:
                            future.set_result(data["result"])
                elif "method" in data:
                    self._handle_event(data)
                    
        except websockets.exceptions.ConnectionClosed as e:
            logger.error("WebSocket connection closed", exc_info=True)
            for future in self.pending_message.values():
                if not future.done():
                    future.set_exception(CDPConnectionError(
                        "WebSocket connection closed",
                        method="listen"
                    ))
            self.pending_message.clear()
        except Exception as e:
            logger.error(f"Error in listen loop: {e}", exc_info=True)
            for future in self.pending_message.values():
                if not future.done():
                    if isinstance(e, BrowserAgentError):
                        future.set_exception(e)
                    else:
                        future.set_exception(CDPConnectionError(
                            f"Unexpected error in listen loop: {e}",
                            method="listen"
                        ))
            self.pending_message.clear()
    async def get_frame_tree(self, session_id: Optional[str] = None):
        """
        Collect frame tree from a session and store frames in registry.
        
        This recursively parses the frame tree structure from Page.getFrameTree
        and stores all frames with their parent-child relationships.
        """
        session_id = await self._ensure_session_active(session_id)
        
        if not self.registry.is_domain_enabled(session_id, "Page"):
            await self.enable_domains(["Page"], session_id)
        
        result = await self.send("Page.getFrameTree", session_id=session_id)
        frame_tree = result.get("frameTree")
        
        if not frame_tree:
            logger.debug("No frame tree returned", extra={"session_id": session_id})
            return
        
        session_info = self.registry.get_session(session_id)
        target_id = session_info.target_id if session_info else None
        
        self._parse_frame_tree(frame_tree, parent_frame_id=None, target_id=target_id, session_id=session_id)
        logger.debug(
            f"Collected frame tree",
            extra={"session_id": session_id, "frame_count": len(self.registry.frames)}
        )
    
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
        session_id = await self._ensure_session_active(session_id)
        
        logger.info(
            f"Waiting for page load",
            extra={"session_id": session_id, "timeout": timeout}
        )

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
                
                logger.error(
                    f"Page load timeout after {timeout}s",
                    extra={
                        "session_id": session_id,
                        "timeout": timeout,
                        "pending_frames": pending_frames,
                        "inflight_requests": inflight,
                    }
                )
                
                raise CDPTimeoutError(
                    f"Page load timed out after {timeout} seconds "
                    f"(pending_frames={pending_frames}, inflight_requests={inflight})",
                    timeout=timeout,
                    session_id=session_id,
                    method="wait_for_load",
                    pending_frames=pending_frames,
                    inflight_requests=inflight,
                )

            if not ready_state_complete:
                try:
                    ready_state_complete = await self._is_document_ready(session_id)
                    if ready_state_complete:
                        logger.debug("Document readyState is complete", extra={"session_id": session_id})
                except BrowserAgentError:
                    ready_state_complete = False

            network_idle = self._is_network_idle(session_id, network_idle_threshold, now)
            frames_loaded = self._are_frames_loaded(session_id)

            if ready_state_complete and network_idle and frames_loaded:
                logger.info("Page load complete", extra={"session_id": session_id})
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
                except BrowserAgentError as e:
                    logger.warning(
                        f"Failed to collect frame tree for session: {e}",
                        extra={"session_id": session_id, "error_type": type(e).__name__}
                    )
                except Exception as e:
                    logger.warning(
                        f"Unexpected error collecting frame tree: {e}",
                        extra={"session_id": session_id},
                        exc_info=True
                    )

    async def click_node(
        self,
        node: EnhancedNode,
        *,
        button: str = "left",
        click_count: int = 1,
        move_before_click: bool = True,
        scroll_into_view: bool = True,
        delay_between_events: float = 0.05,
        session_id: Optional[str] = None,
    ):
        """
        Dispatch a mouse click against the supplied EnhancedNode.

        Args:
            node: EnhancedNode with click metadata.
            button: Mouse button to use (left, right, middle).
            click_count: Number of clicks to report (1 for single, 2 for double).
            move_before_click: If True, send a mouseMoved event first.
            scroll_into_view: If True, attempt to scroll the node into view.
            delay_between_events: Seconds to wait between press/release.
            session_id: Optional explicit session override.
        """
        if not isinstance(node, EnhancedNode):
            raise ValueError("click_node requires an EnhancedNode instance")

        backend_node_id = getattr(node, "backend_node_id", None)
        if backend_node_id is None:
            raise ValueError("EnhancedNode is missing backend_node_id required for click")

        # Resolve the session for the node's frame; fall back to provided session or active session.
        resolved_session_id = session_id or self.registry.get_session_from_frame(node.frame_id)
        resolved_session_id = await self._ensure_session_active(resolved_session_id)

        if scroll_into_view:
            try:
                await self.send(
                    "DOM.scrollIntoViewIfNeeded",
                    {"backendNodeId": backend_node_id},
                    session_id=resolved_session_id,
                )
            except BrowserAgentError as exc:
                logger.debug(
                    "scrollIntoViewIfNeeded failed, continuing with click",
                    extra={
                        "session_id": resolved_session_id,
                        "backend_node_id": backend_node_id,
                        "error_type": type(exc).__name__,
                    },
                )

        x, y = node.click_point
        x_float = float(x)
        y_float = float(y)

        if move_before_click:
            await self.send(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseMoved",
                    "x": x_float,
                    "y": y_float,
                    "modifiers": 0,
                },
                session_id=resolved_session_id,
            )

        await self.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": x_float,
                "y": y_float,
                "button": button,
                "clickCount": click_count,
                "modifiers": 0,
            },
            session_id=resolved_session_id,
        )

        if delay_between_events > 0:
            await asyncio.sleep(delay_between_events)

        await self.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": x_float,
                "y": y_float,
                "button": button,
                "clickCount": click_count,
                "modifiers": 0,
            },
            session_id=resolved_session_id,
        )

    async def type_text(
        self,
        node: EnhancedNode,
        text: str,
        *,
        clear_existing: bool = False,
        click_to_focus: bool = True,
        delay_between_chars: float = 0.0,
        session_id: Optional[str] = None,
    ):
        """
        Type the provided text into the supplied EnhancedNode.

        Args:
            node: EnhancedNode representing an input-capable element.
            text: Text content to insert.
            clear_existing: If True, clears existing value before typing.
            click_to_focus: If True, click the element to ensure focus.
            delay_between_chars: Optional delay between characters (seconds).
            session_id: Optional explicit session override.
        """
        if not isinstance(node, EnhancedNode):
            raise ValueError("type_text requires an EnhancedNode instance")

        if text is None:
            raise ValueError("type_text received None for text argument")

        backend_node_id = getattr(node, "backend_node_id", None)
        if backend_node_id is None:
            raise ValueError("EnhancedNode is missing backend_node_id required for typing")

        resolved_session_id = session_id or self.registry.get_session_from_frame(node.frame_id)
        resolved_session_id = await self._ensure_session_active(resolved_session_id)

        if click_to_focus:
            await self.click_node(
                node,
                button="left",
                click_count=1,
                move_before_click=False,
                scroll_into_view=True,
                delay_between_events=0.0,
                session_id=resolved_session_id,
            )

        try:
            await self.send(
                "DOM.focus",
                {"backendNodeId": backend_node_id},
                session_id=resolved_session_id,
            )
        except BrowserAgentError as exc:
            logger.debug(
                "Failed to focus node before typing",
                extra={
                    "session_id": resolved_session_id,
                    "backend_node_id": backend_node_id,
                    "error_type": type(exc).__name__,
                },
            )

        object_id: Optional[str] = None
        try:
            resolved = await self.send(
                "DOM.resolveNode",
                {"backendNodeId": backend_node_id},
                session_id=resolved_session_id,
            )
            object_id = resolved.get("object", {}).get("objectId")
        except BrowserAgentError as exc:
            logger.debug(
                "DOM.resolveNode failed, continuing without objectId",
                extra={
                    "session_id": resolved_session_id,
                    "backend_node_id": backend_node_id,
                    "error_type": type(exc).__name__,
                },
            )

        if clear_existing and object_id:
            try:
                await self.send(
                    "Runtime.callFunctionOn",
                    {
                        "objectId": object_id,
                        "functionDeclaration": """
                            function() {
                                if (this instanceof HTMLInputElement || this instanceof HTMLTextAreaElement) {
                                    this.value = '';
                                    this.dispatchEvent(new Event('input', { bubbles: true }));
                                    this.dispatchEvent(new Event('change', { bubbles: true }));
                                } else {
                                    this.textContent = '';
                                }
                            }
                        """,
                        "awaitPromise": False,
                    },
                    session_id=resolved_session_id,
                )
            except BrowserAgentError as exc:
                logger.debug(
                    "Failed to clear existing text before typing",
                    extra={
                        "session_id": resolved_session_id,
                        "backend_node_id": backend_node_id,
                        "error_type": type(exc).__name__,
                    },
                )

        if delay_between_chars > 0:
            for char in text:
                await self.send(
                    "Input.insertText",
                    {"text": char},
                    session_id=resolved_session_id,
                )
                await asyncio.sleep(delay_between_chars)
        else:
            await self.send(
                "Input.insertText",
                {"text": text},
                session_id=resolved_session_id,
                    )
    # =========================================================================
    # Screenshot Capture (Task 1.3)
    # =========================================================================

    async def capture_screenshot(
        self,
        *,
        format: str = "jpeg",
        quality: int = 80,
        full_page: bool = False,
        session_id: Optional[str] = None,
    ) -> str:
        """
        Capture a screenshot of the current page.

        Args:
            format: Image format - "jpeg" or "png".
            quality: JPEG quality (0-100). Ignored for PNG.
            full_page: If True, capture the full scrollable page. If False, capture viewport only.
            session_id: Optional explicit session override.

        Returns:
            Base64-encoded image string.
        """
        resolved_session_id = await self._ensure_session_active(session_id)

        params: Dict[str, Any] = {
            "format": format,
        }

        if format == "jpeg":
            params["quality"] = quality

        if full_page:
            # captureBeyondViewport captures the full page
            params["captureBeyondViewport"] = True

        result = await self.send(
            "Page.captureScreenshot",
            params,
            session_id=resolved_session_id,
        )

        return result.get("data", "")

    # =========================================================================
    # Scroll Action (Task 1.4)
    # =========================================================================

    async def scroll(
        self,
        *,
        direction: str = "down",
        amount: int = 500,
        x: Optional[float] = None,
        y: Optional[float] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """
        Scroll the page in the specified direction.

        Args:
            direction: One of "up", "down", "left", "right".
            amount: Pixels to scroll.
            x: X coordinate for scroll origin. Defaults to viewport center.
            y: Y coordinate for scroll origin. Defaults to viewport center.
            session_id: Optional explicit session override.
        """
        resolved_session_id = await self._ensure_session_active(session_id)

        # Default to center of viewport if not specified
        if x is None:
            x = 640.0  # Default viewport width / 2
        if y is None:
            y = 360.0  # Default viewport height / 2

        # Calculate delta based on direction
        delta_x = 0.0
        delta_y = 0.0

        if direction == "down":
            delta_y = amount
        elif direction == "up":
            delta_y = -amount
        elif direction == "right":
            delta_x = amount
        elif direction == "left":
            delta_x = -amount
        else:
            raise ValueError(f"Invalid scroll direction: {direction}. Use 'up', 'down', 'left', or 'right'.")

        # Send mouseWheel event
        await self.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseWheel",
                "x": x,
                "y": y,
                "deltaX": delta_x,
                "deltaY": delta_y,
                "modifiers": 0,
            },
            session_id=resolved_session_id,
        )

    # =========================================================================
    # Navigation Helpers (Task 1.5)
    # =========================================================================

    async def go_back(self, *, session_id: Optional[str] = None) -> bool:
        """
        Navigate back in browser history.

        Args:
            session_id: Optional explicit session override.

        Returns:
            True if navigation was successful, False if no history to go back to.
        """
        resolved_session_id = await self._ensure_session_active(session_id)

        # Get navigation history
        history = await self.send(
            "Page.getNavigationHistory",
            {},
            session_id=resolved_session_id,
        )

        current_index = history.get("currentIndex", 0)
        entries = history.get("entries", [])

        if current_index <= 0 or len(entries) <= 1:
            logger.debug("No history to go back to", extra={"session_id": resolved_session_id})
            return False

        # Navigate to previous entry
        previous_entry = entries[current_index - 1]
        await self.send(
            "Page.navigateToHistoryEntry",
            {"entryId": previous_entry["id"]},
            session_id=resolved_session_id,
        )

        return True

    async def go_forward(self, *, session_id: Optional[str] = None) -> bool:
        """
        Navigate forward in browser history.

        Args:
            session_id: Optional explicit session override.

        Returns:
            True if navigation was successful, False if no history to go forward to.
        """
        resolved_session_id = await self._ensure_session_active(session_id)

        # Get navigation history
        history = await self.send(
            "Page.getNavigationHistory",
            {},
            session_id=resolved_session_id,
        )

        current_index = history.get("currentIndex", 0)
        entries = history.get("entries", [])

        if current_index >= len(entries) - 1:
            logger.debug("No history to go forward to", extra={"session_id": resolved_session_id})
            return False

        # Navigate to next entry
        next_entry = entries[current_index + 1]
        await self.send(
            "Page.navigateToHistoryEntry",
            {"entryId": next_entry["id"]},
            session_id=resolved_session_id,
        )

        return True

    async def refresh(self, *, ignore_cache: bool = False, session_id: Optional[str] = None) -> None:
        """
        Reload the current page.

        Args:
            ignore_cache: If True, bypass the cache (hard refresh).
            session_id: Optional explicit session override.
        """
        resolved_session_id = await self._ensure_session_active(session_id)

        await self.send(
            "Page.reload",
            {"ignoreCache": ignore_cache},
            session_id=resolved_session_id,
        )

    async def navigate(
        self,
        url: str,
        *,
        wait_for_load: bool = True,
        timeout: float = 15.0,
        session_id: Optional[str] = None,
    ) -> None:
        """
        Navigate to a URL and optionally wait for the page to load.

        Args:
            url: The URL to navigate to.
            wait_for_load: If True, wait for page load to complete.
            timeout: Maximum time to wait for page load (seconds).
            session_id: Optional explicit session override.
        """
        resolved_session_id = await self._ensure_session_active(session_id)

        await self.send(
            "Page.navigate",
            {"url": url},
            session_id=resolved_session_id,
        )

        if wait_for_load:
            await self.wait_for_load(session_id=resolved_session_id, timeout=timeout)

    async def get_current_url(self, *, session_id: Optional[str] = None) -> str:
        """
        Get the current page URL.

        Args:
            session_id: Optional explicit session override.

        Returns:
            The current URL as a string.
        """
        resolved_session_id = await self._ensure_session_active(session_id)

        result = await self.send(
            "Runtime.evaluate",
            {"expression": "window.location.href", "returnByValue": True},
            session_id=resolved_session_id,
        )

        return result.get("result", {}).get("value", "")

    async def get_page_title(self, *, session_id: Optional[str] = None) -> str:
        """
        Get the current page title.

        Args:
            session_id: Optional explicit session override.

        Returns:
            The page title as a string.
        """
        resolved_session_id = await self._ensure_session_active(session_id)

        result = await self.send(
            "Runtime.evaluate",
            {"expression": "document.title", "returnByValue": True},
            session_id=resolved_session_id,
        )

        return result.get("result", {}).get("value", "")

    async def close(self) -> None:
        """
        Close the WebSocket connection gracefully.
        """
        if self.ws:
            try:
                await self.ws.close()
            except Exception as e:
                logger.debug(f"Error closing WebSocket: {e}")
            finally:
                self.ws = None


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
