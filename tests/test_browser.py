"""
Comprehensive tests for the Browser class and related functionality.

Run with: pytest tests/test_browser.py -v

Prerequisites:
- Chrome must be running with debugging enabled:
  python launch_chrome.py
"""
import asyncio
import base64
import pytest

from browser import Browser, BrowserConfig
from models import ActionResult, BrowserState


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def browser_config():
    """Default browser configuration for tests."""
    return BrowserConfig(
        headless=False,
        viewport_width=1280,
        viewport_height=720,
        page_load_timeout=10.0,
    )


@pytest.fixture
async def browser(browser_config):
    """Create and start a browser instance."""
    b = Browser(config=browser_config)
    await b.start()
    yield b
    await b.stop()


# =============================================================================
# Connection Tests
# =============================================================================

class TestBrowserConnection:
    """Tests for browser connection and lifecycle."""
    
    @pytest.mark.asyncio
    async def test_browser_starts_and_stops(self, browser_config):
        """Test that browser can start and stop cleanly."""
        browser = Browser(config=browser_config)
        await browser.start()
        assert browser._client is not None
        await browser.stop()
        assert browser._client is None
    
    @pytest.mark.asyncio
    async def test_browser_context_manager(self, browser_config):
        """Test browser as async context manager."""
        async with Browser(config=browser_config) as browser:
            assert browser._client is not None
        # After context exit, client should be None
        assert browser._client is None
    
    @pytest.mark.asyncio
    async def test_browser_multiple_sessions(self, browser_config):
        """Test that multiple browser sessions can be created."""
        async with Browser(config=browser_config) as b1:
            async with Browser(config=browser_config) as b2:
                # Both should be connected
                assert b1._client is not None
                assert b2._client is not None


# =============================================================================
# Navigation Tests
# =============================================================================

class TestNavigation:
    """Tests for navigation functionality."""
    
    @pytest.mark.asyncio
    async def test_navigate_to_url(self, browser):
        """Test basic URL navigation."""
        result = await browser.navigate("https://example.com")
        assert result.success
        assert result.action_type == "navigate"
        
        url = await browser.get_url()
        assert "example.com" in url
    
    @pytest.mark.asyncio
    async def test_get_page_title(self, browser):
        """Test getting page title."""
        await browser.navigate("https://example.com")
        title = await browser.get_title()
        assert "Example" in title
    
    @pytest.mark.asyncio
    async def test_go_back_and_forward(self, browser):
        """Test browser history navigation."""
        # Navigate to first page
        await browser.navigate("https://example.com")
        url1 = await browser.get_url()
        
        # Navigate to second page
        await browser.navigate("https://www.wikipedia.org")
        url2 = await browser.get_url()
        assert url1 != url2
        
        # Go back
        result = await browser.go_back()
        assert result.success
        await asyncio.sleep(1)  # Wait for navigation
        
        # Go forward
        result = await browser.go_forward()
        assert result.success
    
    @pytest.mark.asyncio
    async def test_refresh(self, browser):
        """Test page refresh."""
        await browser.navigate("https://example.com")
        result = await browser.refresh()
        assert result.success
        assert result.action_type == "refresh"


# =============================================================================
# State Collection Tests
# =============================================================================

class TestStateCollection:
    """Tests for browser state collection."""
    
    @pytest.mark.asyncio
    async def test_get_state_returns_browser_state(self, browser):
        """Test that get_state returns a BrowserState object."""
        await browser.navigate("https://example.com")
        state = await browser.get_state()
        
        assert isinstance(state, BrowserState)
        assert state.url
        assert state.title
        assert state.dom_text
        assert isinstance(state.selector_map, dict)
    
    @pytest.mark.asyncio
    async def test_get_state_includes_screenshot(self, browser):
        """Test that get_state includes screenshot when requested."""
        await browser.navigate("https://example.com")
        
        # With screenshot
        state = await browser.get_state(include_screenshot=True)
        assert state.screenshot_base64 is not None
        assert len(state.screenshot_base64) > 0
        
        # Verify it's valid base64
        try:
            decoded = base64.b64decode(state.screenshot_base64)
            assert len(decoded) > 0
        except Exception:
            pytest.fail("Screenshot is not valid base64")
    
    @pytest.mark.asyncio
    async def test_get_state_without_screenshot(self, browser):
        """Test get_state without screenshot for performance."""
        await browser.navigate("https://example.com")
        state = await browser.get_state(include_screenshot=False)
        
        assert state.screenshot_base64 is None
        assert state.url
        assert state.dom_text
    
    @pytest.mark.asyncio
    async def test_state_element_count(self, browser):
        """Test that state reports correct element count."""
        await browser.navigate("https://example.com")
        state = await browser.get_state()
        
        assert state.element_count >= 0
        assert state.element_count == len(state.selector_map)
    
    @pytest.mark.asyncio
    async def test_state_to_prompt(self, browser):
        """Test BrowserState.to_prompt() method."""
        await browser.navigate("https://example.com")
        state = await browser.get_state()
        
        prompt = state.to_prompt()
        assert "URL:" in prompt
        assert "Title:" in prompt
        assert "Elements:" in prompt


# =============================================================================
# Screenshot Tests
# =============================================================================

class TestScreenshot:
    """Tests for screenshot functionality."""
    
    @pytest.mark.asyncio
    async def test_screenshot_viewport(self, browser):
        """Test viewport screenshot."""
        await browser.navigate("https://example.com")
        screenshot = await browser.screenshot(full_page=False)
        
        assert screenshot
        assert len(screenshot) > 0
        
        # Verify it's valid base64
        decoded = base64.b64decode(screenshot)
        assert len(decoded) > 0
    
    @pytest.mark.asyncio
    async def test_screenshot_full_page(self, browser):
        """Test full page screenshot."""
        await browser.navigate("https://www.wikipedia.org")
        screenshot = await browser.screenshot(full_page=True)
        
        assert screenshot
        assert len(screenshot) > 0


# =============================================================================
# Action Tests
# =============================================================================

class TestActions:
    """Tests for browser actions (click, type, scroll)."""
    
    @pytest.mark.asyncio
    async def test_scroll_down(self, browser):
        """Test scrolling down."""
        await browser.navigate("https://www.wikipedia.org")
        result = await browser.scroll(direction="down", amount=500)
        
        assert result.success
        assert result.action_type == "scroll"
    
    @pytest.mark.asyncio
    async def test_scroll_up(self, browser):
        """Test scrolling up."""
        await browser.navigate("https://www.wikipedia.org")
        
        # First scroll down
        await browser.scroll(direction="down", amount=500)
        await asyncio.sleep(0.5)
        
        # Then scroll up
        result = await browser.scroll(direction="up", amount=300)
        assert result.success
    
    @pytest.mark.asyncio
    async def test_scroll_invalid_direction(self, browser):
        """Test that invalid scroll direction raises error."""
        await browser.navigate("https://example.com")
        result = await browser.scroll(direction="invalid", amount=100)
        
        assert not result.success
        assert "Invalid scroll direction" in result.error_message
    
    @pytest.mark.asyncio
    async def test_click_nonexistent_element(self, browser):
        """Test clicking non-existent element index."""
        await browser.navigate("https://example.com")
        await browser.get_state()  # Populate selector map
        
        result = await browser.click(99999)  # Non-existent index
        assert not result.success
        assert "not found" in result.error_message.lower()
    
    @pytest.mark.asyncio
    async def test_type_nonexistent_element(self, browser):
        """Test typing into non-existent element index."""
        await browser.navigate("https://example.com")
        await browser.get_state()
        
        result = await browser.type(99999, "test")
        assert not result.success
        assert "not found" in result.error_message.lower()
    
    @pytest.mark.asyncio
    async def test_press_key_enter(self, browser):
        """Test pressing Enter key."""
        await browser.navigate("https://example.com")
        result = await browser.press_key("Enter")
        
        assert result.success
        assert result.action_type == "press_key"
    
    @pytest.mark.asyncio
    async def test_press_key_with_modifiers(self, browser):
        """Test pressing key with modifiers."""
        await browser.navigate("https://example.com")
        result = await browser.press_key("a", modifiers=["ctrl"])
        
        assert result.success


# =============================================================================
# ActionResult Tests
# =============================================================================

class TestActionResult:
    """Tests for ActionResult class."""
    
    def test_action_result_ok(self):
        """Test creating successful ActionResult."""
        result = ActionResult.ok("click", element_index=5)
        
        assert result.success
        assert result.action_type == "click"
        assert result.element_index == 5
        assert result.error_message is None
    
    def test_action_result_error(self):
        """Test creating failed ActionResult."""
        result = ActionResult.error("type", "Element not found", element_index=3)
        
        assert not result.success
        assert result.action_type == "type"
        assert result.element_index == 3
        assert result.error_message == "Element not found"
    
    def test_action_result_to_message_success(self):
        """Test to_message for successful result."""
        result = ActionResult.ok("click", element_index=5)
        message = result.to_message()
        
        assert "✓" in message
        assert "click" in message
        assert "[5]" in message
    
    def test_action_result_to_message_error(self):
        """Test to_message for failed result."""
        result = ActionResult.error("type", "Element not found")
        message = result.to_message()
        
        assert "✗" in message
        assert "failed" in message
        assert "Element not found" in message


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests that combine multiple operations."""
    
    @pytest.mark.asyncio
    async def test_full_workflow(self, browser):
        """Test a complete workflow: navigate, get state, scroll."""
        # Navigate
        result = await browser.navigate("https://example.com")
        assert result.success
        
        # Get state
        state = await browser.get_state()
        assert state.url
        assert state.element_count >= 0
        
        # Scroll
        result = await browser.scroll(direction="down", amount=200)
        assert result.success
        
        # Screenshot
        screenshot = await browser.screenshot()
        assert screenshot
    
    @pytest.mark.asyncio
    async def test_multiple_navigations(self, browser):
        """Test multiple page navigations."""
        pages = [
            "https://example.com",
            "https://www.wikipedia.org",
            "https://example.com",
        ]
        
        for url in pages:
            result = await browser.navigate(url)
            assert result.success
            
            current_url = await browser.get_url()
            # URL might have trailing slash or www prefix
            assert any(part in current_url for part in url.split("://")[1].split("/"))


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

