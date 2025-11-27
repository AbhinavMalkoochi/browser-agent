# Browser Agent - Production MVP Tasks

This document outlines the complete development plan for a production-ready browser automation agent. Tasks are prioritized for **MVP first**, then production hardening, then polish.

---

## Code Analysis Summary

### ✅ What's Working Well

- **CDP Client (`cdp.py`)**: Solid WebSocket implementation with retry logic, session recovery, frame tracking
- **Enhanced Merger (`enhanced_merger.py`)**: Good multi-source data correlation (DOM + Snapshot + AX)
- **Session Manager (`targets.py`)**: Proper OOPIF handling and frame-to-session routing
- **Error Taxonomy (`errors.py`)**: Clean exception hierarchy
- **Actions**: `click_node()` and `type_text()` implemented correctly
- **Serialization**: Basic LLM-friendly format in place

### ⚠️ Issues Found

1. **Dead code in `cdp.py`**: `get_session_for_node()` and `interact()` are unused stubs
2. **Missing `__init__.py`**: Package structure incomplete
3. **No `Browser` class**: User must manually manage CDP client lifecycle
4. **No `Agent` class**: No unified interface for LLM tool integration
5. **Missing actions**: scroll, select dropdown, keyboard shortcuts, go_back, go_forward
6. **No screenshot capability**: Critical for vision models
7. **No navigation helper**: `navigate(url)` with proper wait
8. **DOMSnapshot domain not enabled**: `get_dom()` will fail on first call
9. **Accessibility domain not enabled**: Same issue
10. **No graceful shutdown**: WebSocket cleanup is inconsistent

---

## 🎯 PHASE 1: MVP - Minimum Viable Agent (Priority: CRITICAL)

**Goal**: A working agent that an LLM can use to browse the web.

### Task 1.1: Create High-Level `Browser` Class ⭐ ✅ COMPLETED

**File**: `browser.py`
**Why**: Users shouldn't manage CDP details. Provide a clean async context manager.

```python
# Target API:
async with Browser(headless=False) as browser:
    state = await browser.get_state()
    await browser.click(index=3)
    await browser.type(index=5, text="hello")
```

- [x] 1.1.1 Create `Browser` class with `__aenter__` / `__aexit__`
- [x] 1.1.2 Auto-launch Chrome subprocess if not running
- [x] 1.1.3 Auto-connect to CDP and enable all required domains
- [x] 1.1.4 Implement `navigate(url)` with proper wait
- [x] 1.1.5 Implement `get_state()` returning `BrowserState` (serialized DOM + screenshot + URL + title)
- [x] 1.1.6 Implement `click(index)` using selector map
- [x] 1.1.7 Implement `type(index, text)` using selector map
- [x] 1.1.8 Implement `scroll(direction, amount)` for page scrolling
- [x] 1.1.9 Implement `go_back()` and `go_forward()`
- [x] 1.1.10 Implement `screenshot()` returning base64 JPEG
- [x] 1.1.11 Graceful shutdown (close WebSocket, terminate Chrome if we launched it)

### Task 1.2: Fix Domain Enablement ⭐ ✅ COMPLETED

**File**: `cdp.py`
**Why**: `DOMSnapshot.captureSnapshot` and `Accessibility.getFullAXTree` require their domains enabled first.

- [x] 1.2.1 Add `DOMSnapshot` and `Accessibility` to auto-enabled domains in `CDPClient.connect()`
- [x] 1.2.2 Update `get_dom()` to accept a client and verify domains are enabled

### Task 1.3: Implement Screenshot Capture ⭐ ✅ COMPLETED

**File**: `cdp.py`
**Why**: Vision models need screenshots. This is table stakes.

- [x] 1.3.1 Add `capture_screenshot(format="jpeg", quality=80, full_page=False)` method
- [x] 1.3.2 Use `Page.captureScreenshot` CDP command
- [x] 1.3.3 Return base64-encoded string

### Task 1.4: Implement Scroll Action ⭐ ✅ COMPLETED

**File**: `cdp.py`
**Why**: Pages are often longer than viewport. LLM needs to scroll to see more content.

- [x] 1.4.1 Add `scroll(direction="down", amount=500, session_id=None)` method
- [x] 1.4.2 Use `Input.dispatchMouseEvent` with type="mouseWheel"
- [x] 1.4.3 Support "up", "down", "left", "right" directions

### Task 1.5: Implement Navigation Helpers ⭐ ✅ COMPLETED

**File**: `cdp.py`
**Why**: Basic navigation is core functionality.

- [x] 1.5.1 Add `go_back()` using `Page.navigateToHistoryEntry`
- [x] 1.5.2 Add `go_forward()` using `Page.navigateToHistoryEntry`
- [x] 1.5.3 Add `refresh()` using `Page.reload`
- [x] 1.5.4 Add `navigate(url)` with wait_for_load option
- [x] 1.5.5 Add `get_current_url()` and `get_page_title()`

### Task 1.6: Create `BrowserState` Data Class ⭐ ✅ COMPLETED

**File**: `models.py`
**Why**: Single object containing everything the LLM needs.

- [x] 1.6.1 Create `BrowserState` dataclass with: url, title, dom_text, selector_map, screenshot_base64, viewport_size
- [x] 1.6.2 Include helper method `get_element(index)` to retrieve SelectorEntry from selector map
- [x] 1.6.3 Include `to_prompt()` method for LLM consumption

### Task 1.7: Create Package Structure ⭐ ✅ COMPLETED

**Files**: `__init__.py`, `pyproject.toml`
**Why**: Proper Python package for `pip install`.

- [x] 1.7.1 Create root `__init__.py` exporting `Browser`, `BrowserState`, `ActionResult`, etc.
- [x] 1.7.2 Update `pyproject.toml` with proper metadata, classifiers, and build system
- [x] 1.7.3 Add `py.typed` marker for type checking (already existed)

### Task 1.8: Clean Up Dead Code ✅ COMPLETED

**File**: `cdp.py`
**Why**: Remove confusion and reduce maintenance burden.

- [x] 1.8.1 Remove `get_session_for_node()` (duplicate of registry method) - already removed
- [x] 1.8.2 Remove `interact()` stub - already removed
- [x] 1.8.3 Remove `test_frame_events()` and `get_enhanced_elements()` test functions - already removed
- [x] 1.8.4 Move test code to `tests/` directory - tests already in tests/

---

## 🔧 PHASE 2: Production Hardening (Priority: HIGH)

**Goal**: Make the agent reliable for real-world use.

### Task 2.1: Select Dropdown Action ✅ COMPLETED

**File**: `cdp.py`
**Why**: Forms often have `<select>` elements.

- [x] 2.1.1 Add `select_option(node, value, by="value")` method
- [x] 2.1.2 Use JS to set selected option with support for "value", "text", and "index" matching
- [x] 2.1.3 Dispatch `change` and `input` events

### Task 2.2: Keyboard Shortcuts ✅ COMPLETED

**File**: `cdp.py`
**Why**: Copy/paste, form submission, escape modals.

- [x] 2.2.1 Add `press_key(key, modifiers=[])` method
- [x] 2.2.2 Support common keys: Enter, Escape, Tab, Backspace, Delete, Arrow keys, Home, End, PageUp/Down
- [x] 2.2.3 Support modifiers: Ctrl, Alt, Shift, Meta
- [x] 2.2.4 Use `Input.dispatchKeyEvent` with proper key codes

### Task 2.3: Improved Page Load Detection

**File**: `cdp.py`
**Why**: Current implementation can be flaky on SPAs.

- [ ] 2.3.1 Add mutation observer fallback for SPA detection
- [ ] 2.3.2 Add configurable "stable DOM" threshold (no mutations for N ms)
- [ ] 2.3.3 Handle pages that never fire `loadEventFired`

### Task 2.4: Element Highlighting (Debug Aid) ✅ COMPLETED

**File**: `cdp.py`
**Why**: Visual feedback helps debug "why did it click there?"

- [x] 2.4.1 Add `highlight_node(node, duration_ms=2000)` method
- [x] 2.4.2 Use CDP's `Overlay.highlightNode` for native highlighting
- [x] 2.4.3 Auto-remove highlight after duration via async task

### Task 2.5: Occlusion Verification Before Click ✅ COMPLETED

**File**: `cdp.py`
**Why**: Prevent clicking on covered elements.

- [x] 2.5.1 Add `verify_element_visible(node)` method
- [x] 2.5.2 Use `document.elementFromPoint(x, y)` to check what's at click point
- [x] 2.5.3 Verify returned element matches target or is a descendant
- [ ] 2.5.4 Integrate into click action with JS fallback (future enhancement)

### Task 2.6: Action Result Tracking ✅ COMPLETED

**File**: `models.py`
**Why**: LLM needs to know if actions succeeded.

- [x] 2.6.1 Create `ActionResult` dataclass with success, action_type, element_index, error_message, screenshot_after
- [x] 2.6.2 Return `ActionResult` from all Browser action methods
- [x] 2.6.3 Include `to_message()` method for LLM-friendly formatting

### Task 2.7: Timeout Configuration ✅ COMPLETED

**File**: `browser.py`
**Why**: Different pages need different timeouts.

- [x] 2.7.1 Add `BrowserConfig` dataclass with all timeout settings
- [x] 2.7.2 Pass config to `Browser` constructor
- [x] 2.7.3 Expose: `page_load_timeout`, `action_timeout`, `network_idle_timeout`

### Task 2.8: Connection Health Monitoring

**File**: `cdp.py`
**Why**: Detect and recover from stale connections.

- [ ] 2.8.1 Add periodic heartbeat (ping/pong or simple CDP call)
- [ ] 2.8.2 Detect connection loss within N seconds
- [ ] 2.8.3 Auto-reconnect if connection drops

---

## 🧠 PHASE 3: LLM Integration Layer (Priority: HIGH)

**Goal**: Make it trivial to connect to any LLM.

### Task 3.1: Tool Schema Definitions ✅ COMPLETED

**File**: `tools.py`
**Why**: LLMs need JSON schemas for tool calling.

- [x] 3.1.1 Define OpenAI-compatible tool schemas for: click, type, scroll, navigate, go_back, go_forward, refresh, select, press_key, screenshot, done
- [x] 3.1.2 Define Anthropic-compatible tool schemas
- [x] 3.1.3 Create `get_tool_schemas(format="openai")` function with optional tool filtering

### Task 3.2: Tool Executor ✅ COMPLETED

**File**: `tools.py`
**Why**: Parse LLM tool calls and execute them.

- [x] 3.2.1 Create `execute_tool(browser, tool_name, tool_args)` async function
- [x] 3.2.2 Validate required arguments and provide defaults
- [x] 3.2.3 Return `ToolExecutionResult` with structured result for LLM consumption

### Task 3.3: Agent Loop Helper ✅ COMPLETED

**File**: `agent.py`
**Why**: Provide a ready-to-use agent loop.

- [x] 3.3.1 Create `Agent` class with `run(task: str)` async method
- [x] 3.3.2 Implement ReAct-style loop: observe → think → act → repeat
- [x] 3.3.3 Support pluggable LLM backends via `LLMBackend` protocol
- [x] 3.3.4 Add `max_steps` and `max_failures` limits in `AgentConfig`
- [x] 3.3.5 Include `DummyLLMBackend` for testing

### Task 3.4: System Prompt Template ✅ COMPLETED

**File**: `tools.py`
**Why**: Good prompts are critical for agent performance.

- [x] 3.4.1 Create system prompt explaining browser state format
- [x] 3.4.2 Include tool usage instructions
- [x] 3.4.3 Include common patterns (login, search, form filling, navigation)

---

## 🚀 PHASE 4: Performance Optimization (Priority: MEDIUM)

**Goal**: Make it fast enough for production.

### Task 4.1: Parallel Data Collection

**File**: `dom/main.py`
**Why**: Current implementation is already parallel, but verify it's optimal.

- [ ] 4.1.1 Benchmark current `get_dom()` performance
- [ ] 4.1.2 Optimize `computedStyles` list (only request what's needed)
- [ ] 4.1.3 Add caching for unchanged DOM regions

### Task 4.2: Incremental DOM Updates

**File**: `enhanced_merger.py`
**Why**: Full DOM collection on every action is wasteful.

- [ ] 4.2.1 Implement DOM diffing (detect what changed)
- [ ] 4.2.2 Only re-serialize changed subtrees
- [ ] 4.2.3 Cache selector map between calls

### Task 4.3: Screenshot Optimization

**File**: `cdp.py`
**Why**: Screenshots can be large and slow.

- [ ] 4.3.1 Add viewport-only screenshot option (default)
- [ ] 4.3.2 Add downscaling option for vision models
- [ ] 4.3.3 Implement screenshot caching (invalidate on DOM change)

### Task 4.4: Memory Management

**File**: All
**Why**: Long-running agents can leak memory.

- [ ] 4.4.1 Clear old selector maps after each action
- [ ] 4.4.2 Limit history/screenshot retention
- [ ] 4.4.3 Add memory usage monitoring

---

## 🧪 PHASE 5: Testing & Quality (Priority: MEDIUM)

**Goal**: Confidence that it works.

### Task 5.1: Unit Tests

**Directory**: `tests/`

- [ ] 5.1.1 Test `BrowserDataMerger` with mock CDP data
- [ ] 5.1.2 Test `serialize_dom` output format
- [ ] 5.1.3 Test `SessionManager` frame routing
- [ ] 5.1.4 Test error handling and retry logic

### Task 5.2: Integration Tests

**Directory**: `tests/`

- [ ] 5.2.1 Test against static HTML test pages
- [ ] 5.2.2 Test against dynamic SPA (e.g., React app)
- [ ] 5.2.3 Test iframe interactions
- [ ] 5.2.4 Test form filling and submission

### Task 5.3: CI/CD Setup

**File**: `.github/workflows/test.yml`

- [ ] 5.3.1 Set up GitHub Actions workflow
- [ ] 5.3.2 Run tests with headless Chrome
- [ ] 5.3.3 Add linting (ruff) and type checking (mypy)

---

## 📦 PHASE 6: Documentation & Polish (Priority: LOW)

**Goal**: Make it usable by others.

### Task 6.1: API Documentation

- [ ] 6.1.1 Add docstrings to all public methods
- [ ] 6.1.2 Generate API docs with mkdocs or sphinx
- [ ] 6.1.3 Add usage examples

### Task 6.2: README Improvements

- [ ] 6.2.1 Add quick start guide
- [ ] 6.2.2 Add architecture diagram
- [ ] 6.2.3 Add troubleshooting section

### Task 6.3: Example Scripts ✅ COMPLETE

**Directory**: `examples/`

- [x] 6.3.1 Basic navigation example (`basic_navigation.py`)
- [x] 6.3.2 Form filling example (`form_filling.py`)
- [x] 6.3.3 Agent demo with pluggable backend (`agent_demo.py`)
- [x] 6.3.4 Full agent with OpenAI example (`agent_with_openai.py`)
- [x] 6.3.5 Full agent with Anthropic example (`agent_with_anthropic.py`)
- [x] 6.3.6 Full agent with Gemini example (`agent_with_gemini.py`)

---

## Immediate Next Steps (Start Here)

✅ **Phase 1 (MVP) - COMPLETE**
✅ **Phase 2 (Production Hardening) - MOSTLY COMPLETE**
✅ **Phase 3 (LLM Integration) - COMPLETE**
✅ **Phase 5 (Testing) - PARTIAL (test suite created)**
✅ **Phase 6 (Documentation) - PARTIAL (examples complete)**

**Additional Completed Work:**
- [x] Real LLM backends: OpenAI, Anthropic, Gemini (`llm_backends.py`)
- [x] Comprehensive test suite (`tests/test_browser.py`, `tests/test_tools.py`, `tests/test_llm_backends.py`)
- [x] CDP code audit: All functions verified as necessary

**Remaining High-Priority Tasks:**

1. **Task 2.3**: Improved page load detection for SPAs
2. **Task 2.8**: Connection health monitoring
3. **Task 4.1-4.4**: Performance optimization

---

## Success Criteria

### MVP Complete When: ✅ ALL COMPLETE

- [x] Can navigate to a URL and get page state
- [x] Can click elements by index
- [x] Can type into inputs by index
- [x] Can scroll the page
- [x] Can take screenshots
- [x] Has a clean `Browser` class API

### Production Ready When:

- [ ] 95%+ action success rate on diverse pages
- [ ] < 2s state collection time
- [ ] < 500ms action execution time
- [ ] Handles iframes and SPAs
- [ ] Has comprehensive error messages
- [ ] Has 80%+ test coverage
