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
from agent import Agent, AgentConfig, DummyLLMBackend, LLMBackend, LLMResponse, ToolCall
from browser import Browser, BrowserConfig
from models import ActionResult, AgentHistory, AgentStep, BrowserState
from serialization import SelectorEntry, SerializedOutput, serialize_dom
from tools import (
    TOOL_DEFINITIONS,
    ToolExecutionResult,
    execute_tool,
    get_system_prompt,
    get_tool_schemas,
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
    # Action results
    "ActionResult",
    "AgentStep",
    "AgentHistory",
    # Serialization
    "SelectorEntry",
    "SerializedOutput",
    "serialize_dom",
    # LLM Integration
    "TOOL_DEFINITIONS",
    "ToolExecutionResult",
    "execute_tool",
    "get_tool_schemas",
    "get_system_prompt",
    # Version
    "__version__",
]
