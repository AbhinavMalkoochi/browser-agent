"""
Browser - High-level async interface for browser automation.

This module provides the main user-facing API for the browser agent.
It wraps the low-level CDP client with a clean, intuitive interface.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from browser_agent.cdp.client import CDPClient, get_page_ws_url
from browser_agent.cdp.dom import get_dom
from browser_agent.utils.merger import BrowserDataMerger, EnhancedNode
from browser_agent.core.errors import BrowserAgentError, CDPConnectionError
from browser_agent.core.models import ActionResult, BrowserState
from browser_agent.core.serialization import SelectorEntry, serialize_dom

logger = logging.getLogger("browser_agent")


def _default_user_data_dir() -> str:
    """Generate a unique user data directory for process isolation."""
    return os.path.join(tempfile.gettempdir(), f"browser-agent-chrome-{uuid.uuid4().hex[:8]}")


@dataclass
class BrowserConfig:
    """Configuration options for the Browser."""
    
    headless: bool = False
    viewport_width: int = 1280
    viewport_height: int = 720
    host: str = "localhost"
    port: int = 9222
    page_load_timeout: float = 15.0
    action_timeout: float = 5.0
    network_idle_timeout: float = 0.5
    screenshot_quality: int = 80
    screenshot_format: str = "jpeg"
    user_data_dir: str = field(default_factory=_default_user_data_dir)
    debug: bool = False


class Browser:
    """
    High-level browser automation interface.
    
    Provides a clean async context manager for browser automation.
    Handles Chrome lifecycle, CDP connection, and state management.
    
    Usage:
        async with Browser() as browser:
            await browser.navigate("https://example.com")
            state = await browser.get_state()
            await browser.click(1)
            await browser.type(2, "hello world")
    """
    
    def __init__(self, config: Optional[BrowserConfig] = None):
        """
        Initialize the Browser.
        
        Args:
            config: Browser configuration. Uses defaults if not provided.
        """
        self.config = config or BrowserConfig()
        self._client: Optional[CDPClient] = None
        self._chrome_process: Optional[subprocess.Popen] = None
        self._selector_map: Dict[int, SelectorEntry] = {}
        self._nodes: List[EnhancedNode] = []
        self._last_state: Optional[BrowserState] = None
        self._launched_chrome = False
    
    async def __aenter__(self) -> Browser:
        """Async context manager entry - connect to browser."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - cleanup resources."""
        await self.stop()
    
    async def start(self) -> None:
        """
        Start the browser session.
        
        Attempts to connect to an existing Chrome instance first.
        If none is found, launches a new Chrome process.
        """
        try:
            # Try to connect to existing Chrome
            ws_url = await get_page_ws_url(
                host=self.config.host,
                port=self.config.port,
            )
            logger.info(f"Connected to existing Chrome at {self.config.host}:{self.config.port}")
        except CDPConnectionError:
            # Launch Chrome if not running
            logger.info("No Chrome found, launching new instance...")
            await self._launch_chrome()
            
            # Wait for Chrome to start and retry connection
            for attempt in range(10):
                # Check if process is still alive (fail fast if Chrome crashed)
                if self._chrome_process and self._chrome_process.poll() is not None:
                    exit_code = self._chrome_process.returncode
                    self._chrome_process = None
                    self._launched_chrome = False
                    raise CDPConnectionError(
                        f"Chrome process exited unexpectedly with code {exit_code}",
                        method="Browser.start"
                    )
                
                await asyncio.sleep(0.5)
                try:
                    ws_url = await get_page_ws_url(
                        host=self.config.host,
                        port=self.config.port,
                    )
                    break
                except CDPConnectionError:
                    if attempt == 9:
                        # Cleanup on failure (P0-7)
                        await self._cleanup_chrome_process()
                        raise CDPConnectionError(
                            f"Chrome failed to start after 5 seconds",
                            method="Browser.start"
                        )
        
        # Create and connect CDP client
        self._client = CDPClient(ws_url, debug=self.config.debug)
        try:
            await self._client.connect()
        except Exception:
            # Cleanup on connection failure (P0-7)
            await self._cleanup_chrome_process()
            raise
        
        logger.info("Browser session started")
    
    async def _cleanup_chrome_process(self) -> None:
        """Cleanup Chrome process without blocking the event loop."""
        if self._launched_chrome and self._chrome_process:
            logger.info("Terminating Chrome process...")
            self._chrome_process.terminate()
            try:
                # Use asyncio.to_thread to avoid blocking the event loop (P0-3)
                await asyncio.wait_for(
                    asyncio.to_thread(self._chrome_process.wait),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                self._chrome_process.kill()
                # Give it a moment to be killed
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(self._chrome_process.wait),
                        timeout=2.0
                    )
                except asyncio.TimeoutError:
                    pass
            self._chrome_process = None
            self._launched_chrome = False

    async def stop(self) -> None:
        """
        Stop the browser session and cleanup resources.
        """
        if self._client:
            await self._client.close()
            self._client = None
        
        await self._cleanup_chrome_process()
        
        logger.info("Browser session stopped")
    
    async def _launch_chrome(self) -> None:
        """Launch a Chrome process with CDP debugging enabled."""
        # Use shutil.which for cross-platform Chrome detection (P1-10)
        chrome_names = [
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
            "chrome",
        ]
        
        chrome_executable = None
        for name in chrome_names:
            path = shutil.which(name)
            if path:
                chrome_executable = path
                break
        
        # Fallback to common paths for systems where shutil.which might not find it
        if not chrome_executable:
            fallback_paths = [
                "/usr/bin/google-chrome",
                "/usr/bin/chromium-browser",
                "/usr/bin/chromium",
                "/snap/bin/chromium",
                "/opt/google/chrome/chrome",
                # macOS paths
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ]
            for path in fallback_paths:
                if os.path.exists(path):
                    chrome_executable = path
                    break
        
        if not chrome_executable:
            raise CDPConnectionError(
                "Chrome/Chromium not found. Please install Chrome or Chromium.",
                method="Browser._launch_chrome"
            )
        
        chrome_args = [
            chrome_executable,
            f"--remote-debugging-port={self.config.port}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            f"--user-data-dir={self.config.user_data_dir}",
            f"--window-size={self.config.viewport_width},{self.config.viewport_height}",
            "about:blank",
        ]
        
        if self.config.headless:
            chrome_args.extend([
                "--headless=new",
                "--disable-gpu",
            ])
        
        self._chrome_process = subprocess.Popen(
            chrome_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._launched_chrome = True
        logger.info(f"Launched Chrome (PID: {self._chrome_process.pid})")
    
    def _ensure_connected(self) -> CDPClient:
        """Ensure we have an active CDP client."""
        if not self._client:
            raise BrowserAgentError(
                "Browser not connected. Call start() or use async context manager.",
                method="_ensure_connected"
            )
        return self._client
    
    # =========================================================================
    # Navigation
    # =========================================================================
    
    async def navigate(self, url: str, *, wait_for_load: bool = True) -> ActionResult:
        """
        Navigate to a URL.
        
        Args:
            url: The URL to navigate to.
            wait_for_load: If True, wait for page load to complete.
            
        Returns:
            ActionResult indicating success or failure.
        """
        client = self._ensure_connected()
        try:
            await client.navigate(
                url,
                wait_for_load=wait_for_load,
                timeout=self.config.page_load_timeout,
            )
            return ActionResult.ok("navigate", extracted_content=url)
        except BrowserAgentError as e:
            return ActionResult.error("navigate", str(e))
    
    async def go_back(self) -> ActionResult:
        """Navigate back in browser history."""
        client = self._ensure_connected()
        try:
            success = await client.go_back()
            if success:
                return ActionResult.ok("go_back")
            return ActionResult.error("go_back", "No history to go back to")
        except BrowserAgentError as e:
            return ActionResult.error("go_back", str(e))
    
    async def go_forward(self) -> ActionResult:
        """Navigate forward in browser history."""
        client = self._ensure_connected()
        try:
            success = await client.go_forward()
            if success:
                return ActionResult.ok("go_forward")
            return ActionResult.error("go_forward", "No history to go forward to")
        except BrowserAgentError as e:
            return ActionResult.error("go_forward", str(e))
    
    async def refresh(self) -> ActionResult:
        """Reload the current page."""
        client = self._ensure_connected()
        try:
            await client.refresh()
            return ActionResult.ok("refresh")
        except BrowserAgentError as e:
            return ActionResult.error("refresh", str(e))
    
    # =========================================================================
    # State Collection
    # =========================================================================
    
    async def get_state(self, *, include_screenshot: bool = True) -> BrowserState:
        """
        Get the current browser state.
        
        Collects DOM data, serializes it for LLM consumption, and optionally
        captures a screenshot.
        
        Args:
            include_screenshot: If True, include a screenshot in the state.
            
        Returns:
            BrowserState containing all information needed by the LLM.
        """
        client = self._ensure_connected()
        
        # Collect DOM data
        dom_data = await get_dom(client)
        
        # Process with merger
        merger = BrowserDataMerger(
            viewport_width=self.config.viewport_width,
            viewport_height=self.config.viewport_height,
        )
        self._nodes = merger.merge_browser_data(
            dom_data["dom"],
            dom_data["snapshot"],
            dom_data["ax"],
            dom_data["metrics"],
        )
        
        # Serialize for LLM
        serialized = serialize_dom(self._nodes)
        self._selector_map = serialized.selector_map
        
        # Fetch URL, title, and screenshot concurrently (P1-9)
        async def get_screenshot_or_none():
            if include_screenshot:
                return await client.capture_screenshot(
                    format=self.config.screenshot_format,
                    quality=self.config.screenshot_quality,
                )
            return None
        
        url, title, screenshot = await asyncio.gather(
            client.get_current_url(),
            client.get_page_title(),
            get_screenshot_or_none(),
        )
        
        self._last_state = BrowserState(
            url=url,
            title=title,
            dom_text=serialized.text,
            selector_map=self._selector_map,
            screenshot_base64=screenshot,
            viewport_width=self.config.viewport_width,
            viewport_height=self.config.viewport_height,
        )
        
        return self._last_state
    
    async def screenshot(self, *, full_page: bool = False) -> str:
        """
        Capture a screenshot of the current page.
        
        Args:
            full_page: If True, capture the full scrollable page.
            
        Returns:
            Base64-encoded image string.
        """
        client = self._ensure_connected()
        return await client.capture_screenshot(
            format=self.config.screenshot_format,
            quality=self.config.screenshot_quality,
            full_page=full_page,
        )
    
    # =========================================================================
    # Actions
    # =========================================================================
    
    def _get_node_by_index(self, index: int) -> Optional[EnhancedNode]:
        """Get an EnhancedNode by its selector map index."""
        entry = self._selector_map.get(index)
        if not entry:
            return None
        
        # Find the matching node
        for node in self._nodes:
            if node.backend_node_id == entry.backend_node_id:
                return node
        return None
    
    async def click(self, index: int) -> ActionResult:
        """
        Click an element by its index.
        
        Args:
            index: Element index from the serialized DOM (1-based).
            
        Returns:
            ActionResult indicating success or failure.
        """
        client = self._ensure_connected()
        
        node = self._get_node_by_index(index)
        if not node:
            return ActionResult.error(
                "click",
                f"Element [{index}] not found. Call get_state() first or element may have changed.",
                element_index=index,
            )
        
        try:
            await client.click_node(node)
            return ActionResult.ok("click", element_index=index)
        except BrowserAgentError as e:
            return ActionResult.error("click", str(e), element_index=index)
    
    async def type(self, index: int, text: str, *, clear_existing: bool = True) -> ActionResult:
        """
        Type text into an element by its index.
        
        Args:
            index: Element index from the serialized DOM (1-based).
            text: Text to type.
            clear_existing: If True, clear existing text before typing.
            
        Returns:
            ActionResult indicating success or failure.
        """
        client = self._ensure_connected()
        
        node = self._get_node_by_index(index)
        if not node:
            return ActionResult.error(
                "type",
                f"Element [{index}] not found. Call get_state() first or element may have changed.",
                element_index=index,
            )
        
        try:
            await client.type_text(node, text, clear_existing=clear_existing)
            return ActionResult.ok("type", element_index=index)
        except BrowserAgentError as e:
            return ActionResult.error("type", str(e), element_index=index)
    
    async def scroll(
        self,
        *,
        direction: str = "down",
        amount: int = 500,
    ) -> ActionResult:
        """
        Scroll the page.
        
        Args:
            direction: One of "up", "down", "left", "right".
            amount: Pixels to scroll.
            
        Returns:
            ActionResult indicating success or failure.
        """
        client = self._ensure_connected()
        
        try:
            await client.scroll(direction=direction, amount=amount)
            return ActionResult.ok("scroll", extracted_content=f"{direction} {amount}px")
        except BrowserAgentError as e:
            return ActionResult.error("scroll", str(e))
    
    async def select(
        self,
        index: int,
        value: str,
        *,
        by: str = "value",
    ) -> ActionResult:
        """
        Select an option in a dropdown element.
        
        Args:
            index: Element index from the serialized DOM (1-based).
            value: The value to select.
            by: How to match the option - "value", "text", or "index".
            
        Returns:
            ActionResult indicating success or failure.
        """
        client = self._ensure_connected()
        
        node = self._get_node_by_index(index)
        if not node:
            return ActionResult.error(
                "select",
                f"Element [{index}] not found. Call get_state() first or element may have changed.",
                element_index=index,
            )
        
        try:
            await client.select_option(node, value, by=by)
            return ActionResult.ok("select", element_index=index, extracted_content=value)
        except BrowserAgentError as e:
            return ActionResult.error("select", str(e), element_index=index)
    
    async def press_key(
        self,
        key: str,
        *,
        modifiers: Optional[List[str]] = None,
    ) -> ActionResult:
        """
        Press a keyboard key.
        
        Args:
            key: Key to press (e.g., "Enter", "Escape", "Tab", "a", "A").
            modifiers: Optional list of modifiers ("ctrl", "alt", "shift", "meta").
            
        Returns:
            ActionResult indicating success or failure.
        """
        client = self._ensure_connected()
        
        try:
            await client.press_key(key, modifiers=modifiers)
            mod_str = f"+{'+'.join(modifiers)}" if modifiers else ""
            return ActionResult.ok("press_key", extracted_content=f"{key}{mod_str}")
        except BrowserAgentError as e:
            return ActionResult.error("press_key", str(e))
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    async def get_url(self) -> str:
        """Get the current page URL."""
        client = self._ensure_connected()
        return await client.get_current_url()
    
    async def get_title(self) -> str:
        """Get the current page title."""
        client = self._ensure_connected()
        return await client.get_page_title()
    
    def get_element(self, index: int) -> Optional[SelectorEntry]:
        """
        Get element metadata by index.
        
        Args:
            index: Element index from the serialized DOM (1-based).
            
        Returns:
            SelectorEntry if found, None otherwise.
        """
        return self._selector_map.get(index)
    
    @property
    def element_count(self) -> int:
        """Get the number of actionable elements from the last state."""
        return len(self._selector_map)
    
    @property
    def last_state(self) -> Optional[BrowserState]:
        """Get the most recently collected browser state."""
        return self._last_state

