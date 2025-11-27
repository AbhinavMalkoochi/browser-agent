"""
Browser Agent - High-performance browser automation for LLM-driven interaction.
"""
from cdp import CDPClient, get_page_ws_url, setup_logging
from enhanced_merger import BrowserDataMerger, EnhancedNode
from models import BrowserState, ActionResult, AgentStep, AgentHistory
from serialization import serialize_dom, SelectorEntry, SerializedOutput
from errors import (
    BrowserAgentError,
    CDPConnectionError,
    CDPTimeoutError,
    CDPProtocolError,
    CDPSessionError,
    CDPTargetError,
)

__version__ = "0.1.0"

__all__ = [
    # Core
    "CDPClient",
    "get_page_ws_url",
    "setup_logging",
    # Data processing
    "BrowserDataMerger",
    "EnhancedNode",
    # Models
    "BrowserState",
    "ActionResult",
    "AgentStep",
    "AgentHistory",
    # Serialization
    "serialize_dom",
    "SelectorEntry",
    "SerializedOutput",
    # Errors
    "BrowserAgentError",
    "CDPConnectionError",
    "CDPTimeoutError",
    "CDPProtocolError",
    "CDPSessionError",
    "CDPTargetError",
]

