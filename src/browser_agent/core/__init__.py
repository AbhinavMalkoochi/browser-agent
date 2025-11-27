"""
Core module - Data models, errors, serialization, and types.
"""
from browser_agent.core.models import ActionResult, AgentHistory, AgentStep, BrowserState
from browser_agent.core.errors import (
    BrowserAgentError,
    CDPConnectionError,
    CDPTimeoutError,
    CDPProtocolError,
    CDPSessionError,
    CDPTargetError,
)
from browser_agent.core.serialization import SelectorEntry, SerializedOutput, serialize_dom
from browser_agent.core.types import LLMResponse, ToolCall

__all__ = [
    "ActionResult",
    "AgentHistory",
    "AgentStep",
    "BrowserState",
    "BrowserAgentError",
    "CDPConnectionError",
    "CDPTimeoutError",
    "CDPProtocolError",
    "CDPSessionError",
    "CDPTargetError",
    "SelectorEntry",
    "SerializedOutput",
    "serialize_dom",
    "LLMResponse",
    "ToolCall",
]

