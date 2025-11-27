# Browser Agent

A high-performance browser automation library using Chrome DevTools Protocol (CDP), designed for LLM-driven browser interaction.

## Features

- **Clean Async API**: Simple `Browser` class with async context manager support
- **LLM-Ready**: Built-in tool schemas for OpenAI and Anthropic, plus a ready-to-use `Agent` class
- **Multiple LLM Backends**: Built-in support for OpenAI, Anthropic Claude, and Google Gemini
- **Intelligent Element Detection**: Correlates DOM, DOMSnapshot, and Accessibility data
- **Precise Actions**: Click, type, scroll, select dropdowns, press keys
- **Confidence Scoring**: Ranks elements by actionability (0-1 scale)
- **Screenshot Support**: Capture viewport or full-page screenshots

## Quick Start

### Prerequisites

- Chrome/Chromium browser
- Python 3.12+

### Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd browser-agent

# Install base dependencies (using uv)
uv sync

# Install with LLM backend support (choose one or more)
uv sync --extra openai      # For OpenAI
uv sync --extra anthropic   # For Anthropic
uv sync --extra gemini      # For Google Gemini
uv sync --extra all-llms    # For all LLM backends

# Or with pip
pip install -e .                  # Base only
pip install -e ".[openai]"        # With OpenAI
pip install -e ".[anthropic]"     # With Anthropic
pip install -e ".[gemini]"        # With Google Gemini
pip install -e ".[all-llms]"      # With all LLM backends
```

### Launch Chrome

Before running any scripts, start Chrome with CDP debugging enabled:

```bash
# Run as a module
python -m browser_agent

# Or with options
python -m browser_agent --headless --remote-debugging-port=9222
```

### Basic Usage

```python
import asyncio
from browser_agent import Browser

async def main():
    async with Browser() as browser:
        # Navigate to a page
        await browser.navigate("https://example.com")

        # Get page state (DOM + screenshot)
        state = await browser.get_state()
        print(f"URL: {state.url}")
        print(f"Elements: {state.element_count}")
        print(state.dom_text)  # LLM-friendly element list

        # Interact with elements by index
        await browser.click(1)  # Click element [1]
        await browser.type(2, "hello world")  # Type into element [2]
        await browser.scroll(direction="down", amount=500)

asyncio.run(main())
```

### LLM Agent Usage

```python
import asyncio
from browser_agent import Agent, AgentConfig, BrowserConfig, OpenAIBackend

async def main():
    # Use built-in OpenAI backend (or AnthropicBackend, GeminiBackend)
    backend = OpenAIBackend(model="gpt-4o")

    config = AgentConfig(
        max_steps=30,
        verbose=True,
        browser_config=BrowserConfig(headless=False),
    )

    agent = Agent(backend, config=config)
    history = await agent.run(
        task="Search for 'Python tutorials' on Google",
        start_url="https://google.com"
    )

    print(f"Completed: {history.is_complete}")
    print(f"Result: {history.final_result}")
    print(f"Steps: {len(history.steps)}")

asyncio.run(main())
```

### Low-Level Tool Execution

```python
from browser_agent import get_tool_schemas, execute_tool

# Get tool schemas for your LLM
tools = get_tool_schemas(format="openai")  # or "anthropic"

# Execute a tool call
result = await execute_tool(browser, "click", {"index": 3})
print(result.to_message())  # "✓ click on element [3]"
```

## API Reference

### Browser Class

```python
from browser_agent import Browser, BrowserConfig

config = BrowserConfig(
    headless=False,           # Run with visible browser
    viewport_width=1280,
    viewport_height=720,
    page_load_timeout=15.0,
    screenshot_quality=80,
)

async with Browser(config) as browser:
    # Navigation
    await browser.navigate(url)
    await browser.go_back()
    await browser.go_forward()
    await browser.refresh()

    # State
    state = await browser.get_state()
    screenshot = await browser.screenshot(full_page=True)
    url = await browser.get_url()
    title = await browser.get_title()

    # Actions (by element index)
    await browser.click(index)
    await browser.type(index, text)
    await browser.select(index, value, by="value")  # or "text", "index"
    await browser.scroll(direction="down", amount=500)
    await browser.press_key("Enter", modifiers=["ctrl"])
```

### BrowserState

```python
@dataclass
class BrowserState:
    url: str                              # Current page URL
    title: str                            # Page title
    dom_text: str                         # LLM-friendly element list
    selector_map: Dict[int, SelectorEntry]  # Index → element metadata
    screenshot_base64: Optional[str]      # Base64 screenshot
    viewport_width: int
    viewport_height: int
    element_count: int

    def get_element(self, index: int) -> Optional[SelectorEntry]
    def to_prompt(self, include_screenshot=False) -> str
```

### ActionResult

All browser actions return an `ActionResult`:

```python
@dataclass
class ActionResult:
    success: bool
    action_type: str
    element_index: Optional[int]
    error_message: Optional[str]
    extracted_content: Optional[str]

    def to_message(self) -> str  # "✓ click on element [3]"
```

### Agent Class

```python
from browser_agent import Agent, AgentConfig, LLMBackend

config = AgentConfig(
    max_steps=50,              # Maximum actions before stopping
    max_failures=5,            # Stop after N consecutive failures
    screenshot_on_error=True,
    verbose=True,
)

agent = Agent(llm_backend, config=config)
history = await agent.run(task="...", start_url="https://...")
```

### LLM Backends

```python
from browser_agent import OpenAIBackend, AnthropicBackend, GeminiBackend, create_backend

# OpenAI
backend = OpenAIBackend(model="gpt-4o", temperature=0.0)

# Anthropic Claude
backend = AnthropicBackend(model="claude-sonnet-4-20250514", temperature=0.0)

# Google Gemini
backend = GeminiBackend(model="gemini-2.5-flash", temperature=0.0)

# Factory function
backend = create_backend("openai", model="gpt-4o-mini")
```

### Tool Schemas

```python
from browser_agent import get_tool_schemas, TOOL_DEFINITIONS

# Get all tools in OpenAI format
tools = get_tool_schemas(format="openai")

# Get specific tools in Anthropic format
tools = get_tool_schemas(
    format="anthropic",
    include_tools=["click", "type", "scroll"]
)

# Available tools:
# - click: Click element by index
# - type: Type text into element
# - scroll: Scroll page
# - navigate: Go to URL
# - go_back/go_forward: Browser history
# - refresh: Reload page
# - select: Select dropdown option
# - press_key: Press keyboard key
# - screenshot: Capture screenshot
# - done: Signal task completion
```

## Architecture

### Project Structure

```
browser-agent/
├── src/
│   └── browser_agent/
│       ├── __init__.py          # Package exports
│       ├── __main__.py          # CLI entry point (launch Chrome)
│       ├── browser.py           # High-level Browser class
│       ├── agent.py             # LLM Agent with ReAct loop
│       ├── cdp/
│       │   ├── __init__.py
│       │   ├── client.py        # CDP WebSocket client
│       │   ├── session.py       # Session/frame management
│       │   └── dom.py           # Raw DOM data collection
│       ├── core/
│       │   ├── __init__.py
│       │   ├── models.py        # Data classes (BrowserState, ActionResult)
│       │   ├── errors.py        # Custom exceptions
│       │   ├── serialization.py # DOM → LLM text conversion
│       │   └── types.py         # LLM types (ToolCall, LLMResponse)
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── tools.py         # Tool schemas and executor
│       │   └── backends.py      # OpenAI, Anthropic, Gemini backends
│       └── utils/
│           ├── __init__.py
│           └── merger.py        # DOM/AX/Snapshot correlation
├── examples/
│   ├── basic_navigation.py
│   ├── form_filling.py
│   ├── agent_demo.py
│   ├── agent_with_openai.py
│   ├── agent_with_anthropic.py
│   └── agent_with_gemini.py
├── tests/
├── pyproject.toml
└── README.md
```

### Data Flow

1. **Collection**: CDP commands gather DOM, DOMSnapshot, Accessibility, and Layout data
2. **Correlation**: `BrowserDataMerger` matches elements across data sources
3. **Enhancement**: Calculate positions, visibility, interactivity, confidence
4. **Serialization**: Convert to LLM-friendly text with selector map
5. **Action**: Use selector map to resolve indices back to CDP operations

## Configuration

### BrowserConfig Options

| Option               | Default       | Description                   |
| -------------------- | ------------- | ----------------------------- |
| `headless`           | `False`       | Run Chrome without UI         |
| `viewport_width`     | `1280`        | Browser viewport width        |
| `viewport_height`    | `720`         | Browser viewport height       |
| `host`               | `"localhost"` | Chrome debugging host         |
| `port`               | `9222`        | Chrome debugging port         |
| `page_load_timeout`  | `15.0`        | Seconds to wait for page load |
| `screenshot_quality` | `80`          | JPEG quality (0-100)          |
| `screenshot_format`  | `"jpeg"`      | `"jpeg"` or `"png"`           |

### AgentConfig Options

| Option                        | Default | Description                          |
| ----------------------------- | ------- | ------------------------------------ |
| `max_steps`                   | `50`    | Maximum actions per run              |
| `max_failures`                | `5`     | Stop after N consecutive failures    |
| `screenshot_on_error`         | `True`  | Capture screenshot on action failure |
| `include_screenshot_in_state` | `True`  | Include screenshot in state          |
| `verbose`                     | `False` | Log detailed progress                |

## Development

### Running Tests

```bash
# Start Chrome first
python -m browser_agent

# Run tests
pytest tests/
```

### Running Examples

```bash
# Basic navigation
python examples/basic_navigation.py

# With OpenAI (requires OPENAI_API_KEY)
export OPENAI_API_KEY="sk-..."
python examples/agent_with_openai.py

# With Anthropic (requires ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY="sk-ant-..."
python examples/agent_with_anthropic.py

# With Gemini (requires GOOGLE_API_KEY)
export GOOGLE_API_KEY="..."
python examples/agent_with_gemini.py
```

## Troubleshooting

### Chrome Connection Issues

```bash
# Check if Chrome is running with debugging
curl http://localhost:9222/json

# Launch Chrome manually
python -m browser_agent
```

### No Elements Found

- Ensure page has loaded (check `wait_for_load` timeout)
- Some elements may be in iframes (check frame handling)
- Lower confidence threshold if needed

### Action Failures

- Check element is visible and not occluded
- Ensure element is in viewport (scroll first)
- Verify element index is still valid (page may have changed)

## License

MIT License - see LICENSE file for details.
