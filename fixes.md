# Browser Agent - Fixes Roadmap

This document organizes all identified issues by priority, with actionable fixes for each.

---

## P0 - Critical (Causes crashes, hangs, data corruption)

### 1. WebSocket Task Lifecycle Management
**File:** `src/browser_agent/cdp/client.py`  
**Severity:** Critical - ROOT CAUSE OF TERMINAL ERROR  
**Complexity:** Small

**Problem:**  
`asyncio.create_task(self.listen())` is called in `connect()`, but the task object is not stored. If `connect()` raises an exception after starting the task, or if the client is garbage collected, the task might dangle or be destroyed abruptly. This causes the `WebSocket connection closed` / `ConnectionClosedOK` error seen in the terminal.

**Fix:**  
Store the task returned by `create_task` (e.g., `self._listen_task`). In the `close()` method, explicitly cancel this task and await it (suppressing `CancelledError`) to ensure clean shutdown.

```python
# In connect():
self._listen_task = asyncio.create_task(self.listen())

# In close():
if self._listen_task:
    self._listen_task.cancel()
    try:
        await self._listen_task
    except asyncio.CancelledError:
        pass
```

---

### 2. Gemini Tool Response Mapping Bug
**File:** `src/browser_agent/llm/backends.py`  
**Severity:** Critical - API Rejection  
**Complexity:** Medium

**Problem:**  
In `GeminiBackend._convert_messages_to_gemini`, the code attempts to reconstruct the function name from the `tool_call_id`:

```python
func_name = tool_call_id.split("_")[0] if "_" in tool_call_id else "unknown"
```

OpenAI and Anthropic generate random IDs (e.g., `call_89123js`). Splitting this string yields "call", not the actual function name. Gemini requires the **function name** to validate a function response. Passing "call" or "unknown" will cause the API to reject the request.

**Fix:**  
Implement a look-back mechanism. When iterating through messages, store a mapping of `tool_call_id` -> `function_name` when encountering an `assistant` message with `tool_calls`. Use this map when processing subsequent `tool` messages.

```python
def _convert_messages_to_gemini(self, messages: List[Dict[str, Any]]) -> tuple[str, List[Any]]:
    # Build tool_call_id -> function_name mapping first
    tool_call_id_to_name: Dict[str, str] = {}
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tool_call_id_to_name[tc["id"]] = tc["function"]["name"]
    
    # Then use it when processing tool messages
    # ...
    elif role == "tool":
        tool_call_id = msg.get("tool_call_id", "")
        func_name = tool_call_id_to_name.get(tool_call_id, "unknown")
        # ...
```

---

### 3. Blocking I/O in stop()
**File:** `src/browser_agent/browser.py`  
**Severity:** Critical - Freezes Event Loop  
**Complexity:** Small

**Problem:**  
In the `stop()` method, `self._chrome_process.wait(timeout=5)` is a blocking synchronous call. While waiting 5 seconds for Chrome to close, the entire Python Event Loop is frozen. Heartbeats, other async tasks, or network listeners will hang.

**Fix:**  
Use `asyncio.to_thread()` to run the blocking wait call in a separate thread, or use `asyncio.create_subprocess_exec` instead of `subprocess.Popen` from the start.

```python
# Option 1: Use asyncio.to_thread for the wait
async def stop(self):
    if self._chrome_process:
        self._chrome_process.terminate()
        try:
            await asyncio.to_thread(self._chrome_process.wait, timeout=5)
        except subprocess.TimeoutExpired:
            self._chrome_process.kill()
```

---

### 4. Infinite Recursion in Session Recovery
**File:** `src/browser_agent/cdp/client.py`  
**Severity:** Critical - Infinite Loop  
**Complexity:** Medium

**Problem:**  
There is a circular dependency between `_ensure_session_active`, `_recover_session`, and `send`:
- `_ensure_session_active` calls `_recover_session` if a session is disconnected
- `_recover_session` calls `self.send("Target.getTargets", ...)`
- `self.send` calls `_ensure_session_active` (unless it is a browser-level command)

If the new session ID hasn't been fully registered or marked active in the registry yet, this can loop infinitely.

**Fix:**  
Ensure that calls made inside `_recover_session` explicitly bypass the `_ensure_session_active` check by passing a flag to `send` or using `_send_internal` directly until the recovery is fully complete.

```python
async def _recover_session(self):
    # Use _send_internal or add a bypass flag
    targets = await self._send_internal("Target.getTargets", {})
    # ... recovery logic ...
    # Only after registry is updated, resume normal send behavior
```

---

### 5. Recursion Depth Limit in DOM Traversal
**File:** `src/browser_agent/utils/merger.py`  
**Severity:** Critical - Crashes on Deep DOMs  
**Complexity:** Medium

**Problem:**  
`_traverse_dom_and_merge` uses recursion. On extremely deep DOM trees (common in enterprise apps or poorly optimized sites), this will hit Python's default recursion limit (`1000`) and crash the script with `RecursionError`.

**Fix:**  
Replace the recursive `_traverse_dom_and_merge` with an iterative stack-based approach.

```python
def _traverse_dom_and_merge(self, root_node, ...):
    stack = [(root_node, None, 0)]  # (node, parent_id, depth)
    
    while stack:
        node, parent_id, depth = stack.pop()
        # Process node...
        
        # Add children to stack (in reverse order to maintain traversal order)
        children = node.get('children', [])
        for child in reversed(children):
            stack.append((child, node_id, depth + 1))
```

---

### 6. Missing return_exceptions=True in asyncio.gather
**File:** `src/browser_agent/cdp/dom.py`  
**Severity:** Critical - One Failure Crashes All  
**Complexity:** Small

**Problem:**  
`asyncio.gather` is used without `return_exceptions=True`. If one of the CDP commands fails (e.g., `Accessibility` fails because the tree isn't ready, or `DOMSnapshot` times out), the entire function will raise an exception, and you will lose the data from the successful requests.

**Fix:**  
Add `return_exceptions=True` and handle partial failures gracefully.

```python
dom_result, snapshot_result, ax_result = await asyncio.gather(
    client.send("DOM.getDocument", {"depth": -1}),
    client.send("DOMSnapshot.captureSnapshot", {...}),
    client.send("Accessibility.getFullAXTree", {}),
    return_exceptions=True
)

# Check each result for exceptions
if isinstance(dom_result, Exception):
    logger.warning(f"DOM.getDocument failed: {dom_result}")
    dom_result = {}
# ... similar for others
```

---

### 7. Cleanup on Start Failure (Zombie Processes)
**File:** `src/browser_agent/browser.py`  
**Severity:** Critical - Resource Leak  
**Complexity:** Small

**Problem:**  
If `start()` launches the Chrome process but fails to connect to the WebSocket (CDP handshake fails), the method raises an exception but leaves `self._chrome_process` running as a zombie process.

**Fix:**  
Use a try/except block around the connection logic in `start()`. If an exception occurs, ensure `self._chrome_process` is terminated before re-raising the exception.

```python
async def start(self):
    self._chrome_process = self._launch_chrome()
    try:
        ws_url = await self._get_ws_url_with_retry()
        await self._cdp.connect(ws_url)
    except Exception:
        if self._chrome_process:
            self._chrome_process.terminate()
            self._chrome_process.wait(timeout=2)
            self._chrome_process = None
        raise
```

---

### 8. Memory Leaks in SessionManager
**File:** `src/browser_agent/cdp/session.py`  
**Severity:** Critical - Memory Leak  
**Complexity:** Medium

**Problem:**  
While there is a `remove_frame` method, there are no methods to remove sessions (`remove_session`) or targets (`remove_target`). In a long-running browser instance where tabs (targets) are opened and closed frequently, the `self.sessions` and `self.targets` dictionaries will grow indefinitely, causing memory exhaustion.

**Fix:**  
Implement `remove_session(session_id)` and `remove_target(target_id)`. Ensure that removing a target also cleans up associated frames and sessions to maintain referential integrity.

```python
def remove_session(self, session_id: str) -> None:
    if session_id in self.sessions:
        session = self.sessions.pop(session_id)
        # Update associated target
        if session.target_id and session.target_id in self.targets:
            self.targets[session.target_id].session_id = None

def remove_target(self, target_id: str) -> None:
    if target_id in self.targets:
        target = self.targets.pop(target_id)
        # Remove associated session
        if target.session_id:
            self.sessions.pop(target.session_id, None)
        # Remove associated frames
        frames_to_remove = [fid for fid, f in self.frames.items() if f.target_id == target_id]
        for fid in frames_to_remove:
            self.remove_frame(fid)
```

---

## P1 - High (Significant functionality/performance issues)

### 9. Sequential Awaiting in get_state
**File:** `src/browser_agent/browser.py`  
**Severity:** High - Performance  
**Complexity:** Small

**Problem:**  
The `get_state` method awaits `get_dom`, `merger.merge`, `get_current_url`, `get_page_title`, and `capture_screenshot` one by one. Each call involves a network round-trip to the browser. Doing them sequentially adds unnecessary latency (e.g., 50ms + 20ms + 20ms + 200ms).

**Fix:**  
Use `asyncio.gather()` to fetch URL, Title, and Screenshot concurrently.

```python
async def get_state(self, include_screenshot: bool = True):
    dom_data = await self._cdp.get_dom()
    
    # Fetch these concurrently
    url, title, screenshot = await asyncio.gather(
        self._cdp.get_current_url(),
        self._cdp.get_page_title(),
        self._cdp.capture_screenshot() if include_screenshot else asyncio.sleep(0),
    )
    # ...
```

---

### 10. OS-Specific Hardcoding
**File:** `src/browser_agent/browser.py`  
**Severity:** High - Cross-Platform Failure  
**Complexity:** Medium

**Problem:**  
- The `_launch_chrome` method manually searches specific Linux/Unix binary paths (`/usr/bin/...`). This code will fail on Windows and may fail on standard macOS installations.
- `BrowserConfig` defaults `user_data_dir` to `/tmp/browser-agent-chrome`. Windows does not have a `/tmp` directory.

**Fix:**  
Use `shutil.which()` to find the executable dynamically and `tempfile.gettempdir()` for cross-platform temporary paths.

```python
import shutil
import tempfile

def _find_chrome_binary(self) -> str:
    candidates = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path
    raise FileNotFoundError("Chrome/Chromium not found in PATH")

# In BrowserConfig:
user_data_dir: str = field(default_factory=lambda: os.path.join(tempfile.gettempdir(), "browser-agent-chrome"))
```

---

### 11. User Data Directory Locking
**File:** `src/browser_agent/browser.py`  
**Severity:** High - Parallel Instance Crash  
**Complexity:** Small

**Problem:**  
If two instances of `Browser` are initialized with the default config, they will try to write to the exact same `user_data_dir`. Chrome will lock the directory, causing the second instance to crash or hang.

**Fix:**  
Append a unique identifier (UUID or PID) to the `user_data_dir` path to ensure process isolation.

```python
import uuid

# In BrowserConfig or Browser.__init__:
user_data_dir: str = field(default_factory=lambda: os.path.join(
    tempfile.gettempdir(), 
    f"browser-agent-chrome-{uuid.uuid4().hex[:8]}"
))
```

---

### 12. Modern Event Listener Detection ("React Gap")
**File:** `src/browser_agent/utils/merger.py`  
**Severity:** High - Missed Interactive Elements  
**Complexity:** Medium

**Problem:**  
The method `_is_element_interactive` checks for inline event attributes (e.g., `onclick`, `onmousedown`). Modern frameworks (React, Vue, Angular) attach event listeners via JavaScript, not inline HTML attributes. A React button rendered as `<div class="btn">Submit</div>` will have **no** inline attributes and will be classified as non-interactive.

**Fix:**  
Rely more heavily on computed styles:
- Trust `cursor: pointer` implicitly
- Check `user-select: none` (often implies non-text interaction)
- If `pointer-events: none` is present, the element is definitely not clickable

```python
def _is_element_interactive(self, node) -> bool:
    # Check computed styles first
    cursor = node.computed_styles.get('cursor', '')
    if cursor == 'pointer':
        return True
    
    pointer_events = node.computed_styles.get('pointer-events', '')
    if pointer_events == 'none':
        return False
    
    # Then check traditional attributes and roles...
```

---

### 13. Occlusion Logic Flaws
**File:** `src/browser_agent/utils/merger.py`  
**Severity:** High - False Positives/Negatives  
**Complexity:** Large

**Problem:**  
`_apply_occlusion_detection` checks if the center point of the target is inside the bounding box of an obstacle. This causes:
1. **Partial Overlap:** If a button is 90% covered but the center is visible, it is marked "visible"
2. **Hollow Elements:** If a transparent `<div>` covers the center, the button is marked "occluded" even if the overlay allows clicks (`pointer-events: none`)
3. **Parent/Child:** Complex stacking contexts (z-index) are not handled correctly

**Fix:**  
- Check intersection area instead of just center point
- Respect `pointer-events: none` in computed styles
- If Intersection Area / Target Area > 0.9, consider it occluded

```python
def _is_occluded(self, target, obstacle) -> bool:
    # Skip if obstacle has pointer-events: none
    if obstacle.computed_styles.get('pointer-events') == 'none':
        return False
    
    # Calculate intersection area
    intersection = self._calculate_intersection(target.bounds, obstacle.bounds)
    target_area = target.bounds.width * target.bounds.height
    
    if target_area == 0:
        return False
    
    return (intersection / target_area) > 0.9
```

---

### 14. Memory Management - Screenshots in History
**File:** `src/browser_agent/core/models.py`  
**Severity:** High - OOM Risk  
**Complexity:** Medium

**Problem:**  
`BrowserState`, `ActionResult`, and `AgentStep` classes all contain fields for Base64 encoded screenshots. Base64 strings are ~33% larger than binary. In `AgentHistory`, storing 50+ high-resolution Base64 strings in RAM leads to rapid memory bloating and potential OOM crashes.

**Fix:**  
Do not store raw Base64 strings in history objects. Instead, save screenshots to temporary files and store the file path/URI in the dataclass.

```python
@dataclass
class AgentStep:
    # Change from:
    # screenshot_after: Optional[str] = None  # Base64
    
    # To:
    screenshot_path: Optional[str] = None  # File path or URI
```

---

### 15. No Timeout Constraints in DOM Fetching
**File:** `src/browser_agent/cdp/dom.py`  
**Severity:** High - Hangs Indefinitely  
**Complexity:** Small

**Problem:**  
There is no timeout specified for the `asyncio.gather` operation. `DOMSnapshot` on a large page can take several seconds. Without a timeout, this function could hang indefinitely if the CDP connection stalls.

**Fix:**  
Wrap the `asyncio.gather` call in `asyncio.wait_for` with a reasonable timeout.

```python
async def get_dom(client: "CDPClient", timeout: float = 30.0) -> Dict[str, Any]:
    try:
        result = await asyncio.wait_for(
            asyncio.gather(
                client.send("DOM.getDocument", {"depth": -1}),
                client.send("DOMSnapshot.captureSnapshot", {...}),
                client.send("Accessibility.getFullAXTree", {}),
                return_exceptions=True
            ),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        raise CDPTimeoutError(f"DOM fetching timed out after {timeout}s")
```

---

### 16. click_node Coordinate Reliability
**File:** `src/browser_agent/cdp/client.py`  
**Severity:** High - Click Misses  
**Complexity:** Medium

**Problem:**  
`click_node` performs `scrollIntoViewIfNeeded` and then immediately dispatches mouse events at `node.click_point`. However:
- `scrollIntoViewIfNeeded` is not instantaneous; it might require a layout recalculation
- If the node moves during scroll (e.g., sticky headers), the pre-calculated `click_point` might become stale

**Fix:**  
After `scrollIntoViewIfNeeded`, recalculate the node's position using `DOM.getBoxModel` to ensure click coordinates are accurate.

```python
async def click_node(self, node):
    await self.send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": node.backend_node_id})
    
    # Recalculate position after scroll
    box_model = await self.send("DOM.getBoxModel", {"backendNodeId": node.backend_node_id})
    content = box_model.get("model", {}).get("content", [])
    if len(content) >= 4:
        x = (content[0] + content[2]) / 2
        y = (content[1] + content[5]) / 2
    else:
        x, y = node.click_point
    
    await self._dispatch_click(x, y)
```

---

### 17. Race Conditions in SessionManager
**File:** `src/browser_agent/cdp/session.py`  
**Severity:** High - Data Corruption  
**Complexity:** Medium

**Problem:**  
CDP clients often receive events on background threads or operate in an asynchronous environment. This class uses standard Python dictionaries without any locking mechanisms. Concurrent writes (e.g., adding a frame while removing a session) will lead to race conditions and data corruption.

**Fix:**  
Add a lock and use it in every method that reads from or writes to the internal dictionaries.

```python
import asyncio

class SessionManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self.sessions: Dict[str, SessionInfo] = {}
        # ...
    
    async def add_session(self, session_id: str, target_id: str) -> SessionInfo:
        async with self._lock:
            # ... existing logic ...
```

---

### 18. Single Tool Execution Restriction
**File:** `src/browser_agent/agent.py`  
**Severity:** High - Agent Capability  
**Complexity:** Medium

**Problem:**  
The code explicitly executes only the first tool call (`response.tool_calls[0]`). Modern LLMs often output parallel calls (e.g., "click this checkbox" AND "click that checkbox"). Ignoring subsequent calls wastes tokens and confuses the LLM, which assumes all actions were taken.

**Fix:**  
Implement a loop to execute all tool calls. If safety is a concern, check the tool types. Read-only tools can run in parallel; navigation/interaction tools should run sequentially, stopping if one fails or triggers a page load.

```python
for tool_call in response.tool_calls:
    result = await execute_tool(browser, tool_call.name, tool_call.arguments)
    
    # Record step...
    
    if result.is_done:
        # Handle completion
        break
    
    # If this was a navigation action, break to get fresh state
    if tool_call.name in ("navigate", "click", "go_back", "go_forward"):
        break
```

---

### 19. Anthropic Message Ordering
**File:** `src/browser_agent/llm/backends.py`  
**Severity:** High - API Error  
**Complexity:** Small

**Problem:**  
Anthropic is extremely strict about the "User -> Assistant -> User" turn structure. While `_convert_messages_to_anthropic` handles merging consecutive roles, it does not strictly enforce that the first message is a User message. If the message history starts with an Assistant message, the API will error.

**Fix:**  
Ensure the `anthropic_messages` list starts with a user message. If the first message is `assistant`, prepend a dummy user message.

```python
def _convert_messages_to_anthropic(self, messages):
    # ... existing conversion logic ...
    
    # Ensure first message is user role
    if anthropic_messages and anthropic_messages[0]["role"] != "user":
        anthropic_messages.insert(0, {
            "role": "user",
            "content": "Please proceed with the task."
        })
    
    return system_prompt, anthropic_messages
```

---

### 20. Client Lifecycle Management (No close() methods)
**File:** `src/browser_agent/llm/backends.py`  
**Severity:** High - Resource Leak  
**Complexity:** Small

**Problem:**  
The backend classes instantiate their own clients (`AsyncOpenAI`, `AsyncAnthropic`, `genai.Client`) inside `__init__`, but there is no mechanism to close the underlying HTTP sessions. This can lead to resource leaks in long-running applications.

**Fix:**  
Implement `async def close(self)` methods and/or the async context manager protocol (`__aenter__`, `__aexit__`).

```python
class OpenAIBackend:
    async def close(self):
        if hasattr(self.client, 'close'):
            await self.client.close()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
```

---

## P2 - Medium (Code quality, best practices)

### 21. element_count Redundancy
**File:** `src/browser_agent/core/models.py`  
**Complexity:** Small

**Problem:** Redundancy between `element_count` field and `get_element_count()` method can lead to inconsistent state.

**Fix:** Remove the field, convert to a `@property` that returns `len(self.selector_map)`.

---

### 22. Type Safety - selector_map uses Any
**File:** `src/browser_agent/core/models.py`  
**Complexity:** Small

**Problem:** `selector_map` is typed as `Dict[int, Any]`, defeating type checking.

**Fix:** Use `Dict[int, 'SelectorEntry']` with string forward reference.

---

### 23. Hardcoded Magic Strings in merger.py
**File:** `src/browser_agent/utils/merger.py`  
**Complexity:** Small

**Problem:** Strings like `'button'`, `'input'`, `'onclick'` are scattered throughout the code.

**Fix:** Define as `frozenset` constants at module level:
```python
INTERACTIVE_TAGS = frozenset({'button', 'a', 'input', 'select', 'textarea', 'details', 'summary'})
EVENT_ATTRS = frozenset({'onclick', 'onmousedown', 'onmouseup', 'onkeydown', 'onkeyup'})
```

---

### 24. Open/Closed Principle Violation in tools.py
**File:** `src/browser_agent/llm/tools.py`  
**Complexity:** Large

**Problem:** `execute_tool` relies on a massive if/elif/else chain. Every new tool requires modifying both `TOOL_DEFINITIONS` and `execute_tool`.

**Fix:** Implement dynamic dispatching with a registry pattern or use `getattr(browser, tool_name)` with a whitelist.

---

### 25. ToolExecutionResult Should Be a Dataclass
**File:** `src/browser_agent/llm/tools.py`  
**Complexity:** Small

**Problem:** `ToolExecutionResult` is a standard class with verbose `__init__`, lacking `__repr__` and `__eq__`.

**Fix:** Convert to `@dataclass`.

---

### 26. Error Handling Granularity
**Files:** Multiple (`agent.py`, `tools.py`, `client.py`)  
**Complexity:** Medium

**Problem:** Generic `except Exception` catches everything including `KeyboardInterrupt` and `asyncio.CancelledError`.

**Fix:** Catch specific exceptions and let critical ones propagate.

---

### 27. Weak Type Hinting in dom.py
**File:** `src/browser_agent/cdp/dom.py`  
**Complexity:** Small

**Problem:** `client` argument is typed as `Any` despite `TYPE_CHECKING` import.

**Fix:** Use string forward reference: `client: "CDPClient"`.

---

### 28. Hardcoded computedStyles in dom.py
**File:** `src/browser_agent/cdp/dom.py`  
**Complexity:** Small

**Problem:** The `computedStyles` list is hardcoded inside the function.

**Fix:** Move to module-level constant `DEFAULT_COMPUTED_STYLES`.

---

### 29. Library Logging Configuration
**File:** `src/browser_agent/cdp/client.py`  
**Complexity:** Small

**Problem:** `setup_logging` configures handlers, which libraries shouldn't do.

**Fix:** Remove or mark as helper for standalone execution only. Libraries should only emit to `logging.getLogger(__name__)`.

---

### 30. Deprecated Type Hints in session.py
**File:** `src/browser_agent/cdp/session.py`  
**Complexity:** Small

**Problem:** Uses `typing.List`, `typing.Dict`, `typing.Set` instead of built-in types (Python 3.9+).

**Fix:** Replace with `list`, `dict`, `set`.

---

### 31. BrowserState Should Be Immutable
**File:** `src/browser_agent/core/models.py`  
**Complexity:** Small

**Problem:** `BrowserState` represents a snapshot but is mutable, risking accidental modification.

**Fix:** Use `@dataclass(frozen=True)`.

---

### 32. Prompt Formatting Coupled to Data Model
**File:** `src/browser_agent/core/models.py`  
**Complexity:** Medium

**Problem:** `to_prompt` method in `BrowserState` hardcodes the prompt structure, coupling data to presentation.

**Fix:** Move to a dedicated `PromptFormatter` class.

---

### 33. SYSTEM_PROMPT Hardcoded
**File:** `src/browser_agent/llm/tools.py`  
**Complexity:** Small

**Problem:** System prompt is hardcoded in the tools module.

**Fix:** Move to configuration file or `AgentConfig`.

---

### 34. JSON Double-Encoding Risk
**File:** `src/browser_agent/agent.py`  
**Complexity:** Small

**Problem:** `json.dumps(tc["arguments"])` may double-encode if backend returns JSON string.

**Fix:** Add type check before serializing.

---

### 35. Gemini "Hello" Fallback
**File:** `src/browser_agent/llm/backends.py`  
**Complexity:** Small

**Problem:** Empty contents default to "Hello", silently altering conversation context.

**Fix:** Raise an error or use system prompt instead.

---

## P3 - Low (Minor optimizations)

### 36. O(N²) Occlusion Detection
**File:** `src/browser_agent/utils/merger.py`  
**Complexity:** Large

**Problem:** Occlusion detection compares every node against every other node.

**Fix:** Use spatial indexing (R-Tree or grid-based spatial hash) to reduce to O(N log N).

---

### 37. O(N²) URL Deduplication in AgentHistory
**File:** `src/browser_agent/core/models.py`  
**Complexity:** Small

**Problem:** `urls()` method checks `if url not in urls` (list), which is O(N).

**Fix:** Use a set for deduplication.

---

### 38. Linear Search in SessionManager
**File:** `src/browser_agent/cdp/session.py`  
**Complexity:** Medium

**Problem:** `find_target_by_url` iterates over all targets (O(N)).

**Fix:** Maintain a secondary index `self._targets_by_url` for O(1) lookup.

---

### 39. Schema Generation Not Cached
**File:** `src/browser_agent/llm/tools.py`  
**Complexity:** Small

**Problem:** `get_tool_schemas` constructs the list every time it's called.

**Fix:** Cache the result since schemas are static.

---

### 40. Polling in wait_for_load
**File:** `src/browser_agent/cdp/client.py`  
**Complexity:** Medium

**Problem:** `wait_for_load` loop calls `_is_document_ready` every 0.1s, performing `Runtime.evaluate` each time.

**Fix:** Rely primarily on `Page.loadEventFired` and Network idle events; use `Runtime.evaluate` only as final sanity check.

---

### 41. Hardcoded Viewport Center in Scroll
**File:** `src/browser_agent/cdp/client.py`  
**Complexity:** Small

**Problem:** Scroll defaults `x` and `y` to 640.0 and 360.0, assuming 1280x720 viewport.

**Fix:** Fetch actual viewport dimensions dynamically before scrolling.

---

### 42. Repeated Import in _extract_origin_from_url
**File:** `src/browser_agent/cdp/session.py`  
**Complexity:** Small

**Problem:** `from urllib.parse import urlparse` is inside the method.

**Fix:** Move import to top of file.

---

### 43. Exception Swallowing in _extract_origin_from_url
**File:** `src/browser_agent/cdp/session.py`  
**Complexity:** Small

**Problem:** Catches generic `Exception` and returns empty string.

**Fix:** Catch only `ValueError` or `AttributeError` specific to parsing.

---

### 44. Missing Overlay Domain Enablement
**File:** `src/browser_agent/cdp/client.py`  
**Complexity:** Small

**Problem:** `highlight_node` calls `Overlay.highlightNode` but Overlay domain is not enabled.

**Fix:** Add Overlay to enabled domains or enable lazily in `highlight_node`.

---

### 45. httpx Dependency for Single Request
**File:** `src/browser_agent/cdp/client.py`  
**Complexity:** Small

**Problem:** `httpx` is imported solely for `get_page_ws_url`, a single HTTP GET.

**Fix:** Consider using built-in `urllib` for this simple request.

---

## Summary

| Priority | Count | Description |
|----------|-------|-------------|
| P0 | 8 | Critical - Causes crashes, hangs, data corruption |
| P1 | 12 | High - Significant functionality/performance issues |
| P2 | 15 | Medium - Code quality, best practices |
| P3 | 10 | Low - Minor optimizations |
| **Total** | **45** | |

### Recommended Implementation Order

1. **P0-1 (WebSocket Task Lifecycle)** - Fixes the terminal error you're seeing
2. **P0-2 (Gemini Tool Response Bug)** - Critical for Gemini backend users
3. **P0-3 (Blocking I/O)** - Prevents event loop freezes
4. **P0-6 (return_exceptions)** - Quick fix, high impact
5. **P0-7 (Cleanup on Start Failure)** - Prevents zombie processes
6. Continue with remaining P0, then P1 issues

