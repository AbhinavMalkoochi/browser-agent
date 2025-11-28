"""
LLM Tool Definitions - JSON schemas and executor for LLM tool calling.

This module provides:
1. Tool schemas compatible with OpenAI and Anthropic formats
2. A tool executor that maps tool calls to Browser methods
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional, Union

from browser_agent.browser import Browser
from browser_agent.core.models import ActionResult


# =============================================================================
# Tool Schemas
# =============================================================================

TOOL_DEFINITIONS = {
    "click": {
        "name": "click",
        "description": "Click on an element by its index number. Use this to interact with buttons, links, checkboxes, and other clickable elements.",
        "parameters": {
            "type": "object",
            "properties": {
                "index": {
                    "type": "integer",
                    "description": "The element index from the page state (shown in square brackets like [1], [2], etc.)"
                }
            },
            "required": ["index"]
        }
    },
    "type": {
        "name": "type",
        "description": "Type text into an input field, textarea, or contenteditable element. The element must be focused or clickable.",
        "parameters": {
            "type": "object",
            "properties": {
                "index": {
                    "type": "integer",
                    "description": "The element index to type into"
                },
                "text": {
                    "type": "string",
                    "description": "The text to type"
                },
                "clear_existing": {
                    "type": "boolean",
                    "description": "If true, clear existing text before typing. Default is true.",
                    "default": True
                }
            },
            "required": ["index", "text"]
        }
    },
    "scroll": {
        "name": "scroll",
        "description": "Scroll the page in a direction. Use this to see more content that's off-screen.",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down", "left", "right"],
                    "description": "Direction to scroll",
                    "default": "down"
                },
                "amount": {
                    "type": "integer",
                    "description": "Pixels to scroll. Default is 500.",
                    "default": 500
                }
            },
            "required": []
        }
    },
    "navigate": {
        "name": "navigate",
        "description": "Navigate to a URL. Use this to go to a new webpage.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to navigate to (must include http:// or https://)"
                }
            },
            "required": ["url"]
        }
    },
    "go_back": {
        "name": "go_back",
        "description": "Go back to the previous page in browser history.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    "go_forward": {
        "name": "go_forward",
        "description": "Go forward to the next page in browser history.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    "refresh": {
        "name": "refresh",
        "description": "Refresh/reload the current page.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    "select": {
        "name": "select",
        "description": "Select an option from a dropdown (<select>) element.",
        "parameters": {
            "type": "object",
            "properties": {
                "index": {
                    "type": "integer",
                    "description": "The element index of the select dropdown"
                },
                "value": {
                    "type": "string",
                    "description": "The value or text of the option to select"
                },
                "by": {
                    "type": "string",
                    "enum": ["value", "text", "index"],
                    "description": "How to match the option: 'value' (option value attribute), 'text' (visible text), or 'index' (0-based position)",
                    "default": "value"
                }
            },
            "required": ["index", "value"]
        }
    },
    "press_key": {
        "name": "press_key",
        "description": "Press a keyboard key. Useful for form submission (Enter), closing modals (Escape), or navigation.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Key to press: 'Enter', 'Escape', 'Tab', 'Backspace', 'Delete', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', or a single character"
                },
                "modifiers": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["ctrl", "alt", "shift", "meta"]},
                    "description": "Modifier keys to hold while pressing",
                    "default": []
                }
            },
            "required": ["key"]
        }
    },
    "screenshot": {
        "name": "screenshot",
        "description": "Take a screenshot of the current page. Returns base64-encoded image.",
        "parameters": {
            "type": "object",
            "properties": {
                "full_page": {
                    "type": "boolean",
                    "description": "If true, capture the full scrollable page. Default is false (viewport only).",
                    "default": False
                }
            },
            "required": []
        }
    },
    "done": {
        "name": "done",
        "description": "Signal that the task is complete. Use this when you have accomplished the goal.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "A brief summary of what was accomplished"
                },
                "extracted_data": {
                    "type": "string",
                    "description": "Any data extracted from the page (optional)"
                }
            },
            "required": ["message"]
        }
    },
}


def get_tool_schemas(
    format: Literal["openai", "anthropic"] = "openai",
    include_tools: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Get tool schemas in the specified format.
    
    Args:
        format: "openai" for OpenAI/GPT format, "anthropic" for Claude format.
        include_tools: List of tool names to include. If None, includes all tools.
        
    Returns:
        List of tool schema dictionaries.
    """
    tools_to_include = include_tools or list(TOOL_DEFINITIONS.keys())
    
    schemas = []
    for name in tools_to_include:
        if name not in TOOL_DEFINITIONS:
            continue
        
        tool = TOOL_DEFINITIONS[name]
        
        if format == "openai":
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                }
            })
        elif format == "anthropic":
            schemas.append({
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["parameters"],
            })
    
    return schemas


# =============================================================================
# Tool Executor
# =============================================================================

@dataclass
class ToolExecutionResult:
    """Result of executing a tool (P2-25: Converted to dataclass)."""
    
    success: bool
    tool_name: str
    result: Optional[ActionResult] = None
    error: Optional[str] = None
    is_done: bool = False
    done_message: Optional[str] = None
    extracted_data: Optional[str] = None
    
    def to_message(self) -> str:
        """Format for LLM consumption."""
        if self.is_done:
            return f"✓ Task completed: {self.done_message}"
        if self.result:
            return self.result.to_message()
        if self.error:
            return f"✗ {self.tool_name} failed: {self.error}"
        return f"✓ {self.tool_name} executed"


# P2-24: Tool handler type for dynamic dispatch
ToolHandler = Callable[[Browser, Dict[str, Any]], Coroutine[Any, Any, ToolExecutionResult]]


async def _handle_click(browser: Browser, args: Dict[str, Any]) -> ToolExecutionResult:
    index = args.get("index")
    if index is None:
        return ToolExecutionResult(False, "click", error="Missing required parameter: index")
    result = await browser.click(index)
    return ToolExecutionResult(result.success, "click", result=result)


async def _handle_type(browser: Browser, args: Dict[str, Any]) -> ToolExecutionResult:
    index = args.get("index")
    text = args.get("text")
    if index is None or text is None:
        return ToolExecutionResult(False, "type", error="Missing required parameters: index, text")
    clear_existing = args.get("clear_existing", True)
    result = await browser.type(index, text, clear_existing=clear_existing)
    return ToolExecutionResult(result.success, "type", result=result)


async def _handle_scroll(browser: Browser, args: Dict[str, Any]) -> ToolExecutionResult:
    direction = args.get("direction", "down")
    amount = args.get("amount", 500)
    result = await browser.scroll(direction=direction, amount=amount)
    return ToolExecutionResult(result.success, "scroll", result=result)


async def _handle_navigate(browser: Browser, args: Dict[str, Any]) -> ToolExecutionResult:
    url = args.get("url")
    if not url:
        return ToolExecutionResult(False, "navigate", error="Missing required parameter: url")
    result = await browser.navigate(url)
    return ToolExecutionResult(result.success, "navigate", result=result)


async def _handle_go_back(browser: Browser, args: Dict[str, Any]) -> ToolExecutionResult:
    result = await browser.go_back()
    return ToolExecutionResult(result.success, "go_back", result=result)


async def _handle_go_forward(browser: Browser, args: Dict[str, Any]) -> ToolExecutionResult:
    result = await browser.go_forward()
    return ToolExecutionResult(result.success, "go_forward", result=result)


async def _handle_refresh(browser: Browser, args: Dict[str, Any]) -> ToolExecutionResult:
    result = await browser.refresh()
    return ToolExecutionResult(result.success, "refresh", result=result)


async def _handle_select(browser: Browser, args: Dict[str, Any]) -> ToolExecutionResult:
    index = args.get("index")
    value = args.get("value")
    if index is None or value is None:
        return ToolExecutionResult(False, "select", error="Missing required parameters: index, value")
    by = args.get("by", "value")
    result = await browser.select(index, value, by=by)
    return ToolExecutionResult(result.success, "select", result=result)


async def _handle_press_key(browser: Browser, args: Dict[str, Any]) -> ToolExecutionResult:
    key = args.get("key")
    if not key:
        return ToolExecutionResult(False, "press_key", error="Missing required parameter: key")
    modifiers = args.get("modifiers", [])
    result = await browser.press_key(key, modifiers=modifiers)
    return ToolExecutionResult(result.success, "press_key", result=result)


async def _handle_screenshot(browser: Browser, args: Dict[str, Any]) -> ToolExecutionResult:
    full_page = args.get("full_page", False)
    screenshot = await browser.screenshot(full_page=full_page)
    return ToolExecutionResult(
        True, 
        "screenshot", 
        result=ActionResult.ok("screenshot", extracted_content=f"Screenshot captured ({len(screenshot)} bytes)")
    )


async def _handle_done(browser: Browser, args: Dict[str, Any]) -> ToolExecutionResult:
    message = args.get("message", "Task completed")
    extracted_data = args.get("extracted_data")
    return ToolExecutionResult(
        True,
        "done",
        is_done=True,
        done_message=message,
        extracted_data=extracted_data,
    )


# P2-24: Tool handler registry for O(1) dispatch
TOOL_HANDLERS: Dict[str, ToolHandler] = {
    "click": _handle_click,
    "type": _handle_type,
    "scroll": _handle_scroll,
    "navigate": _handle_navigate,
    "go_back": _handle_go_back,
    "go_forward": _handle_go_forward,
    "refresh": _handle_refresh,
    "select": _handle_select,
    "press_key": _handle_press_key,
    "screenshot": _handle_screenshot,
    "done": _handle_done,
}


async def execute_tool(
    browser: Browser,
    tool_name: str,
    tool_args: Dict[str, Any],
) -> ToolExecutionResult:
    """
    Execute a tool call against the browser.
    
    P2-24: Uses handler registry for O(1) dispatch instead of if/elif chain.
    
    Args:
        browser: Browser instance to execute against.
        tool_name: Name of the tool to execute.
        tool_args: Arguments for the tool.
        
    Returns:
        ToolExecutionResult with the outcome.
    """
    try:
        handler = TOOL_HANDLERS.get(tool_name)
        if handler is None:
            return ToolExecutionResult(False, tool_name, error=f"Unknown tool: {tool_name}")
        return await handler(browser, tool_args)
    except Exception as e:
        return ToolExecutionResult(False, tool_name, error=str(e))


# =============================================================================
# System Prompt
# =============================================================================

SYSTEM_PROMPT = """You are a browser automation agent. You MUST interact with web pages using the provided tools.

## CRITICAL RULES

1. **ALWAYS respond with a tool call** - NEVER respond with just text
2. **If the task is complete**, use the `done` tool immediately
3. **If you cannot complete a task** (e.g., requires login, email, human action), use `done` to explain why
4. **AVOID LOOPS** - If you've visited the same URL twice, try a DIFFERENT action
5. **If Elements: 0**, the page may still be loading - try `scroll` or `refresh` first before giving up

## How to Read Page State

The page state shows actionable elements in this format:
[index] <tag href="url"> | action=click | name="text" | text="visible text"

- **index**: Use this number with click, type, and select tools
- **href**: For links, shows where clicking will navigate to - USE THIS to pick the right link
- **name/text**: What the element says or represents

You also receive a screenshot - use it to understand the visual layout.

## Available Actions

- `click(index)` - Click on an element
- `type(index, text)` - Type text into an input field  
- `scroll(direction, amount)` - Scroll the page (direction: up/down, amount: pixels like 500)
- `navigate(url)` - Go to a URL directly
- `go_back()` - Go back in browser history
- `refresh()` - Reload the page (useful if elements aren't loading)
- `done(message, extracted_data)` - Signal task completion with results

## Important Tips

1. **For links**: Look at the `href` attribute to know where it goes BEFORE clicking
   - `href="item?id=123"` → Goes to details/comments page (usually what you want)
   - `href="from?site=example.com"` → Goes to submissions from that site (usually NOT what you want)
   - `href="https://external.com"` → Goes to external site directly
2. **If Elements: 0**: Try `scroll(direction="down", amount=500)` or `refresh()` - the page may need to load
3. **Avoid repeating actions**: If clicking something didn't work, try a DIFFERENT element
4. **External sites**: May have cookie banners or JS issues - if stuck, use `done` to report what you found

## When to Use `done`

- Task is complete (include results in `extracted_data`)
- Task TRULY cannot be completed after trying multiple approaches
- You've tried scrolling multiple times and still can't find what you need

## IMPORTANT: Don't Give Up Too Early!

Before using `done` to report failure, you MUST try:
1. Scroll down at least 2-3 times to see more content
2. Look for alternative buttons/links (like "Apply", "Careers", "Jobs")
3. Check if there are form fields to fill out
4. If on an external site, scroll to find the actual content (it may be below cookie banners)

Only use `done` with a failure message AFTER you've exhausted these options.

REMEMBER: You MUST call a tool. Never respond with just text.
"""


def get_system_prompt() -> str:
    """Get the system prompt for the browser agent."""
    return SYSTEM_PROMPT

