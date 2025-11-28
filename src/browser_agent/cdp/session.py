"""
CDP Session Management - Manages sessions, targets, and frames.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse

logger = logging.getLogger("browser_agent")


class SessionStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DISCONNECTED = "disconnected"


@dataclass
class TargetInfo:
    """Information about a CDP target."""
    target_id: str
    type: str 
    url: str
    title: str
    session_id: Optional[str] = None
    browser_context_id: Optional[str] = None


@dataclass
class FrameInfo:
    """Information about a frame."""
    frame_id: str
    parent_frame_id: Optional[str]
    url: str
    origin: str
    target_id: Optional[str] = None
    session_id: Optional[str] = None


@dataclass
class SessionInfo:
    """Information about a CDP session."""
    session_id: str
    target_id: str
    status: SessionStatus = SessionStatus.ACTIVE
    domains_enabled: Set[str] = field(default_factory=set)
    created_at: float = field(default_factory=time.time)


class SessionManager:
    """Manages CDP sessions, targets, and frames with thread-safe operations."""
    
    def __init__(self):
        self.sessions: Dict[str, SessionInfo] = {}
        self.targets: Dict[str, TargetInfo] = {}
        self.frames: Dict[str, FrameInfo] = {}
        self.children: Dict[str, List[str]] = {}
        self.active_session_id: Optional[str] = None
        # Lock for thread-safe operations (P1-17)
        self._lock = asyncio.Lock()
    
    def add_session(self, session_id: str, target_id: str) -> SessionInfo:
        """Add a new session to the registry."""
        session_info = SessionInfo(session_id=session_id, target_id=target_id)
        self.sessions[session_id] = session_info
        
        if target_id in self.targets:
            self.targets[target_id].session_id = session_id
        
        return session_info
    
    def add_target(self, target_id: str, type: str, url: str, title: str, 
                   browser_context_id: Optional[str] = None) -> TargetInfo:
        """Add a new target to the registry."""
        target_info = TargetInfo(
            target_id=target_id,
            type=type,
            url=url,
            title=title,
            browser_context_id=browser_context_id
        )
        self.targets[target_id] = target_info
        return target_info
    
    def get_session(self, session_id: str) -> Optional[SessionInfo]:
        """Get session info by session ID."""
        return self.sessions.get(session_id)
    
    def get_target(self, target_id: str) -> Optional[TargetInfo]:
        """Get target info by target ID."""
        return self.targets.get(target_id)
    
    def get_session_for_target(self, target_id: str) -> Optional[str]:
        """Get session ID for a given target ID."""
        target = self.targets.get(target_id)
        return target.session_id if target else None
    
    def set_active_session(self, session_id: str):
        """Set the active session."""
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found in registry")
        
        if self.active_session_id and self.active_session_id in self.sessions:
            self.sessions[self.active_session_id].status = SessionStatus.INACTIVE
        
        self.active_session_id = session_id
        self.sessions[session_id].status = SessionStatus.ACTIVE
    
    def get_active_session(self) -> Optional[str]:
        """Get the active session ID."""
        return self.active_session_id
    
    def mark_domain_enabled(self, session_id: str, domain: str):
        """Mark a domain as enabled for a session."""
        session = self.sessions.get(session_id)
        if session:
            session.domains_enabled.add(domain)
    
    def is_domain_enabled(self, session_id: str, domain: str) -> bool:
        """Check if a domain is enabled for a session."""
        session = self.sessions.get(session_id)
        return session is not None and domain in session.domains_enabled
    
    def mark_session_disconnected(self, session_id: str):
        """Mark a session as disconnected."""
        session = self.sessions.get(session_id)
        if session:
            session.status = SessionStatus.DISCONNECTED
            if self.active_session_id == session_id:
                self.active_session_id = None
    
    def add_frame(self, frame_id: str, parent_frame_id: Optional[str], url: str, 
                  origin: str, target_id: Optional[str] = None, 
                  session_id: Optional[str] = None) -> FrameInfo:
        """Add a frame to the registry."""
        frame_info = FrameInfo(
            frame_id=frame_id,
            parent_frame_id=parent_frame_id,
            url=url,
            origin=origin,
            target_id=target_id,
            session_id=session_id
        )
        self.frames[frame_id] = frame_info
        
        if parent_frame_id:
            if parent_frame_id not in self.children:
                self.children[parent_frame_id] = []
            if frame_id not in self.children[parent_frame_id]:
                self.children[parent_frame_id].append(frame_id)
        
        return frame_info
    
    def get_frame(self, frame_id: str) -> Optional[FrameInfo]:
        """Get frame info by frame ID."""
        return self.frames.get(frame_id)
    
    def get_frame_children(self, frame_id: str) -> List[str]:
        """Get list of child frame IDs for a given frame."""
        return self.children.get(frame_id, [])
    
    def find_target_by_url(self, url: str) -> Optional[TargetInfo]:
        """Find a target by matching URL (exact or prefix match)."""
        for target in self.targets.values():
            if target.url == url or url.startswith(target.url) or target.url.startswith(url):
                return target
        return None
    
    def find_target_by_origin(self, origin: str) -> Optional[TargetInfo]:
        """Find a target by matching security origin."""
        for target in self.targets.values():
            target_origin = self._extract_origin_from_url(target.url)
            if target_origin == origin:
                return target
        return None
    
    def _extract_origin_from_url(self, url: str) -> str:
        """Extract security origin from URL (scheme + host)."""
        if not url:
            return ""
        try:
            # urlparse imported at module level (P3-42)
            parsed = urlparse(url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            return origin
        except (ValueError, AttributeError):
            # Catch specific exceptions (P3-43)
            return ""
    
    def update_frame_target_mapping(self, frame_id: str, target_id: str, session_id: str):
        """Update a frame's target and session mapping."""
        frame = self.frames.get(frame_id)
        if frame:
            frame.target_id = target_id
            frame.session_id = session_id

    def get_session_from_frame(self, frame_id: str) -> Optional[str]:
        """Get session ID for a given frame ID."""
        frame = self.frames.get(frame_id)
        return frame.session_id if frame else None
    
    def remove_frame(self, frame_id: str):
        """Remove a frame and all its children from the registry."""
        frame = self.frames.get(frame_id)
        if not frame:
            return
        
        children = self.children.get(frame_id, [])
        for child_id in children[:]:
            self.remove_frame(child_id)
        
        if frame.parent_frame_id and frame.parent_frame_id in self.children:
            if frame_id in self.children[frame.parent_frame_id]:
                self.children[frame.parent_frame_id].remove(frame_id)
        
        if frame_id in self.children:
            del self.children[frame_id]
        
        del self.frames[frame_id]
    
    def remove_session(self, session_id: str) -> None:
        """
        Remove a session from the registry (P0-8: Memory leak fix).
        
        Also updates the associated target to remove the session reference.
        """
        if session_id not in self.sessions:
            return
        
        session = self.sessions.pop(session_id)
        
        # Update associated target
        if session.target_id and session.target_id in self.targets:
            self.targets[session.target_id].session_id = None
        
        # Clear active session if this was it
        if self.active_session_id == session_id:
            self.active_session_id = None
        
        logger.debug(f"Removed session {session_id}")
    
    def remove_target(self, target_id: str) -> None:
        """
        Remove a target and its associated session and frames (P0-8: Memory leak fix).
        
        Maintains referential integrity by cleaning up all related data.
        """
        if target_id not in self.targets:
            return
        
        target = self.targets.pop(target_id)
        
        # Remove associated session
        if target.session_id and target.session_id in self.sessions:
            self.sessions.pop(target.session_id)
            if self.active_session_id == target.session_id:
                self.active_session_id = None
        
        # Remove associated frames
        frames_to_remove = [
            fid for fid, f in list(self.frames.items()) 
            if f.target_id == target_id
        ]
        for fid in frames_to_remove:
            self.remove_frame(fid)
        
        logger.debug(f"Removed target {target_id}")
    
    def cleanup_disconnected_sessions(self) -> int:
        """
        Remove all disconnected sessions and their targets (P0-8: Memory leak fix).
        
        Returns:
            Number of sessions cleaned up.
        """
        disconnected = [
            sid for sid, s in list(self.sessions.items())
            if s.status == SessionStatus.DISCONNECTED
        ]
        
        for session_id in disconnected:
            session = self.sessions.get(session_id)
            if session:
                self.remove_target(session.target_id)
        
        return len(disconnected)

