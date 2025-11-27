"""
LLM Tool Definitions - JSON schemas and executor for LLM tool calling.

This module provides:
1. Tool schemas compatible with OpenAI and Anthropic formats
2. A tool executor that maps tool calls to Browser methods
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from browser import Browser
from models import ActionResult


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

class ToolExecutionResult:
    """Result of executing a tool."""
    
    def __init__(
        self,
        success: bool,
        tool_name: str,
        result: Optional[ActionResult] = None,
        error: Optional[str] = None,
        is_done: bool = False,
        done_message: Optional[str] = None,
        extracted_data: Optional[str] = None,
    ):
        self.success = success
        self.tool_name = tool_name
        self.result = result
        self.error = error
        self.is_done = is_done
        self.done_message = done_message
        self.extracted_data = extracted_data
    
    def to_message(self) -> str:
        """Format for LLM consumption."""
        if self.is_done:
            return f"✓ Task completed: {self.done_message}"
        if self.result:
            return self.result.to_message()
        if self.error:
            return f"✗ {self.tool_name} failed: {self.error}"
        return f"✓ {self.tool_name} executed"


async def execute_tool(
    browser: Browser,
    tool_name: str,
    tool_args: Dict[str, Any],
) -> ToolExecutionResult:
    """
    Execute a tool call against the browser.
    
    Args:
        browser: Browser instance to execute against.
        tool_name: Name of the tool to execute.
        tool_args: Arguments for the tool.
        
    Returns:
        ToolExecutionResult with the outcome.
    """
    try:
        if tool_name == "click":
            index = tool_args.get("index")
            if index is None:
                return ToolExecutionResult(False, tool_name, error="Missing required parameter: index")
            result = await browser.click(index)
            return ToolExecutionResult(result.success, tool_name, result=result)
        
        elif tool_name == "type":
            index = tool_args.get("index")
            text = tool_args.get("text")
            if index is None or text is None:
                return ToolExecutionResult(False, tool_name, error="Missing required parameters: index, text")
            clear_existing = tool_args.get("clear_existing", True)
            result = await browser.type(index, text, clear_existing=clear_existing)
            return ToolExecutionResult(result.success, tool_name, result=result)
        
        elif tool_name == "scroll":
            direction = tool_args.get("direction", "down")
            amount = tool_args.get("amount", 500)
            result = await browser.scroll(direction=direction, amount=amount)
            return ToolExecutionResult(result.success, tool_name, result=result)
        
        elif tool_name == "navigate":
            url = tool_args.get("url")
            if not url:
                return ToolExecutionResult(False, tool_name, error="Missing required parameter: url")
            result = await browser.navigate(url)
            return ToolExecutionResult(result.success, tool_name, result=result)
        
        elif tool_name == "go_back":
            result = await browser.go_back()
            return ToolExecutionResult(result.success, tool_name, result=result)
        
        elif tool_name == "go_forward":
            result = await browser.go_forward()
            return ToolExecutionResult(result.success, tool_name, result=result)
        
        elif tool_name == "refresh":
            result = await browser.refresh()
            return ToolExecutionResult(result.success, tool_name, result=result)
        
        elif tool_name == "select":
            index = tool_args.get("index")
            value = tool_args.get("value")
            if index is None or value is None:
                return ToolExecutionResult(False, tool_name, error="Missing required parameters: index, value")
            by = tool_args.get("by", "value")
            result = await browser.select(index, value, by=by)
            return ToolExecutionResult(result.success, tool_name, result=result)
        
        elif tool_name == "press_key":
            key = tool_args.get("key")
            if not key:
                return ToolExecutionResult(False, tool_name, error="Missing required parameter: key")
            modifiers = tool_args.get("modifiers", [])
            result = await browser.press_key(key, modifiers=modifiers)
            return ToolExecutionResult(result.success, tool_name, result=result)
        
        elif tool_name == "screenshot":
            full_page = tool_args.get("full_page", False)
            screenshot = await browser.screenshot(full_page=full_page)
            return ToolExecutionResult(
                True, 
                tool_name, 
                result=ActionResult.ok("screenshot", extracted_content=f"Screenshot captured ({len(screenshot)} bytes)")
            )
        
        elif tool_name == "done":
            message = tool_args.get("message", "Task completed")
            extracted_data = tool_args.get("extracted_data")
            return ToolExecutionResult(
                True,
                tool_name,
                is_done=True,
                done_message=message,
                extracted_data=extracted_data,
            )
        
        else:
            return ToolExecutionResult(False, tool_name, error=f"Unknown tool: {tool_name}")
    
    except Exception as e:
        return ToolExecutionResult(False, tool_name, error=str(e))


# =============================================================================
# System Prompt
# =============================================================================

SYSTEM_PROMPT = """You are a browser automation agent. You can interact with web pages using the provided tools.

## How to Read Page State

The page state shows actionable elements in this format:
[index] <tag attributes> | action=type | conf=score | name="accessible name" | text="visible text"

- **index**: Use this number with click, type, and select tools
- **action**: What you can do with this element (click, type, select)
- **conf**: Confidence score (0-1) that this element is actionable
- **name/text**: What the element says or represents

## Tips for Success

1. **Always observe first**: Look at the page state before taking action
2. **Use the right tool**: click for buttons/links, type for inputs, select for dropdowns
3. **Scroll if needed**: If you don't see what you're looking for, scroll down
4. **Be patient**: After navigation or clicks, wait for the page to update
5. **Handle errors**: If an action fails, try an alternative approach

## Common Patterns

- **Login**: Find username input → type username → find password input → type password → click submit
- **Search**: Find search input → type query → press Enter or click search button
- **Form filling**: Fill each field in order, then click submit
- **Navigation**: Click links or use navigate() for direct URLs

When you've completed the task, use the done() tool with a summary of what you accomplished.
"""


def get_system_prompt() -> str:
    """Get the system prompt for the browser agent."""
    return SYSTEM_PROMPT

