"""
Tests for the tools module (tool schemas and executor).

Run with: pytest tests/test_tools.py -v
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from models import ActionResult
from tools import (
    TOOL_DEFINITIONS,
    ToolExecutionResult,
    execute_tool,
    get_system_prompt,
    get_tool_schemas,
)


# =============================================================================
# Test Tool Schemas
# =============================================================================

class TestToolSchemas:
    """Tests for tool schema generation."""
    
    def test_get_all_tools_openai_format(self):
        """Test getting all tools in OpenAI format."""
        tools = get_tool_schemas(format="openai")
        
        assert len(tools) > 0
        
        # Check structure
        for tool in tools:
            assert tool["type"] == "function"
            assert "function" in tool
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]
    
    def test_get_all_tools_anthropic_format(self):
        """Test getting all tools in Anthropic format."""
        tools = get_tool_schemas(format="anthropic")
        
        assert len(tools) > 0
        
        # Check structure
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
    
    def test_get_specific_tools(self):
        """Test getting specific tools only."""
        tools = get_tool_schemas(
            format="openai",
            include_tools=["click", "type"]
        )
        
        assert len(tools) == 2
        
        names = [t["function"]["name"] for t in tools]
        assert "click" in names
        assert "type" in names
        assert "scroll" not in names
    
    def test_tool_definitions_have_required_fields(self):
        """Test that all tool definitions have required fields."""
        required_fields = ["name", "description", "parameters"]
        
        for name, tool in TOOL_DEFINITIONS.items():
            for field in required_fields:
                assert field in tool, f"Tool {name} missing {field}"
    
    def test_click_tool_schema(self):
        """Test click tool schema structure."""
        tools = get_tool_schemas(include_tools=["click"])
        click_tool = tools[0]["function"]
        
        assert click_tool["name"] == "click"
        assert "index" in click_tool["parameters"]["properties"]
        assert "index" in click_tool["parameters"]["required"]
    
    def test_type_tool_schema(self):
        """Test type tool schema structure."""
        tools = get_tool_schemas(include_tools=["type"])
        type_tool = tools[0]["function"]
        
        assert type_tool["name"] == "type"
        assert "index" in type_tool["parameters"]["properties"]
        assert "text" in type_tool["parameters"]["properties"]
        assert "index" in type_tool["parameters"]["required"]
        assert "text" in type_tool["parameters"]["required"]
    
    def test_scroll_tool_schema(self):
        """Test scroll tool schema structure."""
        tools = get_tool_schemas(include_tools=["scroll"])
        scroll_tool = tools[0]["function"]
        
        assert scroll_tool["name"] == "scroll"
        assert "direction" in scroll_tool["parameters"]["properties"]
        assert "amount" in scroll_tool["parameters"]["properties"]


# =============================================================================
# Test Tool Executor
# =============================================================================

class TestToolExecutor:
    """Tests for tool execution."""
    
    @pytest.fixture
    def mock_browser(self):
        """Create a mock browser for testing."""
        browser = MagicMock()
        browser.click = AsyncMock(return_value=ActionResult.ok("click", element_index=1))
        browser.type = AsyncMock(return_value=ActionResult.ok("type", element_index=2))
        browser.scroll = AsyncMock(return_value=ActionResult.ok("scroll"))
        browser.navigate = AsyncMock(return_value=ActionResult.ok("navigate"))
        browser.go_back = AsyncMock(return_value=ActionResult.ok("go_back"))
        browser.go_forward = AsyncMock(return_value=ActionResult.ok("go_forward"))
        browser.refresh = AsyncMock(return_value=ActionResult.ok("refresh"))
        browser.select = AsyncMock(return_value=ActionResult.ok("select"))
        browser.press_key = AsyncMock(return_value=ActionResult.ok("press_key"))
        browser.screenshot = AsyncMock(return_value="base64_screenshot_data")
        return browser
    
    @pytest.mark.asyncio
    async def test_execute_click(self, mock_browser):
        """Test executing click tool."""
        result = await execute_tool(mock_browser, "click", {"index": 5})
        
        assert result.success
        assert result.tool_name == "click"
        mock_browser.click.assert_called_once_with(5)
    
    @pytest.mark.asyncio
    async def test_execute_type(self, mock_browser):
        """Test executing type tool."""
        result = await execute_tool(
            mock_browser, 
            "type", 
            {"index": 3, "text": "hello", "clear_existing": True}
        )
        
        assert result.success
        assert result.tool_name == "type"
        mock_browser.type.assert_called_once_with(3, "hello", clear_existing=True)
    
    @pytest.mark.asyncio
    async def test_execute_scroll(self, mock_browser):
        """Test executing scroll tool."""
        result = await execute_tool(
            mock_browser,
            "scroll",
            {"direction": "down", "amount": 500}
        )
        
        assert result.success
        mock_browser.scroll.assert_called_once_with(direction="down", amount=500)
    
    @pytest.mark.asyncio
    async def test_execute_navigate(self, mock_browser):
        """Test executing navigate tool."""
        result = await execute_tool(
            mock_browser,
            "navigate",
            {"url": "https://example.com"}
        )
        
        assert result.success
        mock_browser.navigate.assert_called_once_with("https://example.com")
    
    @pytest.mark.asyncio
    async def test_execute_go_back(self, mock_browser):
        """Test executing go_back tool."""
        result = await execute_tool(mock_browser, "go_back", {})
        
        assert result.success
        mock_browser.go_back.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_go_forward(self, mock_browser):
        """Test executing go_forward tool."""
        result = await execute_tool(mock_browser, "go_forward", {})
        
        assert result.success
        mock_browser.go_forward.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_refresh(self, mock_browser):
        """Test executing refresh tool."""
        result = await execute_tool(mock_browser, "refresh", {})
        
        assert result.success
        mock_browser.refresh.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_select(self, mock_browser):
        """Test executing select tool."""
        result = await execute_tool(
            mock_browser,
            "select",
            {"index": 1, "value": "option1", "by": "value"}
        )
        
        assert result.success
        mock_browser.select.assert_called_once_with(1, "option1", by="value")
    
    @pytest.mark.asyncio
    async def test_execute_press_key(self, mock_browser):
        """Test executing press_key tool."""
        result = await execute_tool(
            mock_browser,
            "press_key",
            {"key": "Enter", "modifiers": ["ctrl"]}
        )
        
        assert result.success
        mock_browser.press_key.assert_called_once_with("Enter", modifiers=["ctrl"])
    
    @pytest.mark.asyncio
    async def test_execute_screenshot(self, mock_browser):
        """Test executing screenshot tool."""
        result = await execute_tool(
            mock_browser,
            "screenshot",
            {"full_page": True}
        )
        
        assert result.success
        mock_browser.screenshot.assert_called_once_with(full_page=True)
    
    @pytest.mark.asyncio
    async def test_execute_done(self, mock_browser):
        """Test executing done tool."""
        result = await execute_tool(
            mock_browser,
            "done",
            {"message": "Task completed", "extracted_data": "some data"}
        )
        
        assert result.success
        assert result.is_done
        assert result.done_message == "Task completed"
        assert result.extracted_data == "some data"
    
    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, mock_browser):
        """Test executing unknown tool."""
        result = await execute_tool(mock_browser, "unknown_tool", {})
        
        assert not result.success
        assert "Unknown tool" in result.error
    
    @pytest.mark.asyncio
    async def test_execute_missing_required_param(self, mock_browser):
        """Test executing tool with missing required parameter."""
        result = await execute_tool(mock_browser, "click", {})
        
        assert not result.success
        assert "Missing required parameter" in result.error
    
    @pytest.mark.asyncio
    async def test_execute_type_missing_text(self, mock_browser):
        """Test executing type with missing text parameter."""
        result = await execute_tool(mock_browser, "type", {"index": 1})
        
        assert not result.success
        assert "Missing required parameters" in result.error


# =============================================================================
# Test ToolExecutionResult
# =============================================================================

class TestToolExecutionResult:
    """Tests for ToolExecutionResult class."""
    
    def test_success_result(self):
        """Test successful execution result."""
        result = ToolExecutionResult(
            success=True,
            tool_name="click",
            result=ActionResult.ok("click", element_index=5)
        )
        
        assert result.success
        assert result.tool_name == "click"
        assert not result.is_done
    
    def test_error_result(self):
        """Test error execution result."""
        result = ToolExecutionResult(
            success=False,
            tool_name="click",
            error="Element not found"
        )
        
        assert not result.success
        assert result.error == "Element not found"
    
    def test_done_result(self):
        """Test done execution result."""
        result = ToolExecutionResult(
            success=True,
            tool_name="done",
            is_done=True,
            done_message="Task completed successfully"
        )
        
        assert result.success
        assert result.is_done
        assert result.done_message == "Task completed successfully"
    
    def test_to_message_success(self):
        """Test to_message for successful result."""
        result = ToolExecutionResult(
            success=True,
            tool_name="click",
            result=ActionResult.ok("click", element_index=5)
        )
        
        message = result.to_message()
        assert "✓" in message
    
    def test_to_message_error(self):
        """Test to_message for error result."""
        result = ToolExecutionResult(
            success=False,
            tool_name="click",
            error="Element not found"
        )
        
        message = result.to_message()
        assert "✗" in message
        assert "failed" in message
    
    def test_to_message_done(self):
        """Test to_message for done result."""
        result = ToolExecutionResult(
            success=True,
            tool_name="done",
            is_done=True,
            done_message="All done!"
        )
        
        message = result.to_message()
        assert "completed" in message.lower()
        assert "All done!" in message


# =============================================================================
# Test System Prompt
# =============================================================================

class TestSystemPrompt:
    """Tests for system prompt generation."""
    
    def test_system_prompt_exists(self):
        """Test that system prompt is generated."""
        prompt = get_system_prompt()
        
        assert prompt
        assert len(prompt) > 100
    
    def test_system_prompt_contains_instructions(self):
        """Test that system prompt contains key instructions."""
        prompt = get_system_prompt()
        
        # Should explain page state format
        assert "index" in prompt.lower() or "[" in prompt
        
        # Should mention tools
        assert "click" in prompt.lower() or "tool" in prompt.lower()
    
    def test_system_prompt_contains_tips(self):
        """Test that system prompt contains helpful tips."""
        prompt = get_system_prompt()
        
        # Should have some guidance
        assert "scroll" in prompt.lower() or "navigate" in prompt.lower()


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

