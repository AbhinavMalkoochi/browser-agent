"""
CDP Module - Chrome DevTools Protocol client and session management.
"""
from browser_agent.cdp.client import CDPClient, get_page_ws_url, setup_logging
from browser_agent.cdp.session import SessionManager, SessionInfo, SessionStatus, TargetInfo, FrameInfo
from browser_agent.cdp.dom import get_dom

__all__ = [
    "CDPClient",
    "get_page_ws_url",
    "setup_logging",
    "SessionManager",
    "SessionInfo",
    "SessionStatus",
    "TargetInfo",
    "FrameInfo",
    "get_dom",
]

