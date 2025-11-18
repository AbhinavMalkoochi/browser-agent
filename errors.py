"""
Browser Agent Error Taxonomy - Custom exception classes for browser automation.

This module defines a hierarchy of exceptions specific to browser automation,
allowing for better error handling, retry logic, and recovery strategies.
"""
from typing import Optional


class BrowserAgentError(Exception):
    """Base exception for all browser agent errors."""
    
    def __init__(self, message: str, session_id: Optional[str] = None, 
                 target_id: Optional[str] = None, method: Optional[str] = None,
                 **context):
        super().__init__(message)
        self.message = message
        self.session_id = session_id
        self.target_id = target_id
        self.method = method
        self.context = context
    
    def __str__(self):
        parts = [self.message]
        if self.session_id:
            parts.append(f"session_id={self.session_id}")
        if self.target_id:
            parts.append(f"target_id={self.target_id}")
        if self.method:
            parts.append(f"method={self.method}")
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            parts.append(f"context=({context_str})")
        return " | ".join(parts)


class CDPConnectionError(BrowserAgentError):
    """Raised when connection to Chrome/CDP fails or is lost."""
    pass


class CDPTimeoutError(BrowserAgentError):
    """Raised when a CDP operation times out."""
    
    def __init__(self, message: str, timeout: Optional[float] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.timeout = timeout


class CDPProtocolError(BrowserAgentError):
    """Raised when CDP returns an error response."""
    
    def __init__(self, message: str, code: Optional[int] = None, 
                 cdp_error: Optional[dict] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.code = code
        self.cdp_error = cdp_error


class CDPSessionError(BrowserAgentError):
    """Raised when session-related operations fail."""
    pass


class CDPTargetError(BrowserAgentError):
    """Raised when target-related operations fail."""
    pass

