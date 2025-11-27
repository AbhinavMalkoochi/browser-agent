"""
Browser Agent - A lightweight, high-performance browser automation library using CDP.

This package provides a clean, async-first API for browser automation,
optimized for LLM-based agents.

Usage:
    from browser_agent import Browser, BrowserConfig, BrowserState

    async with Browser() as browser:
        await browser.navigate("https://example.com")
        state = await browser.get_state()
        await browser.click(1)
        await browser.type(2, "hello world")

For LLM integration:
    from browser_agent import Agent, get_tool_schemas, execute_tool

    agent = Agent(llm_backend)
    result = await agent.run("Search for Python tutorials")

Low-level tool execution:
    tools = get_tool_schemas(format="openai")
    result = await execute_tool(browser, "click", {"index": 1})
"""
from browser_agent.browser import Browser, BrowserConfig
from browser_agent.agent import Agent, AgentConfig, DummyLLMBackend, LLMBackend
from browser_agent.core.types import LLMResponse, ToolCall
from browser_agent.core.models import ActionResult, AgentHistory, AgentStep, BrowserState
from browser_agent.core.serialization import SelectorEntry, SerializedOutput, serialize_dom
from browser_agent.core.errors import (
    BrowserAgentError,
    CDPConnectionError,
    CDPTimeoutError,
    CDPProtocolError,
    CDPSessionError,
    CDPTargetError,
)
from browser_agent.llm.tools import (
    TOOL_DEFINITIONS,
    ToolExecutionResult,
    execute_tool,
    get_system_prompt,
    get_tool_schemas,
)
from browser_agent.llm.backends import (
    OpenAIBackend,
    AnthropicBackend,
    GeminiBackend,
    create_backend,
)

__version__ = "0.1.0"

__all__ = [
    # Main API
    "Browser",
    "BrowserConfig",
    "BrowserState",
    # Agent
    "Agent",
    "AgentConfig",
    "LLMBackend",
    "LLMResponse",
    "ToolCall",
    "DummyLLMBackend",
    # LLM Backends
    "OpenAIBackend",
    "AnthropicBackend",
    "GeminiBackend",
    "create_backend",
    # Action results
    "ActionResult",
    "AgentStep",
    "AgentHistory",
    # Serialization
    "SelectorEntry",
    "SerializedOutput",
    "serialize_dom",
    # Errors
    "BrowserAgentError",
    "CDPConnectionError",
    "CDPTimeoutError",
    "CDPProtocolError",
    "CDPSessionError",
    "CDPTargetError",
    # LLM Integration
    "TOOL_DEFINITIONS",
    "ToolExecutionResult",
    "execute_tool",
    "get_tool_schemas",
    "get_system_prompt",
    # Version
    "__version__",
]

