"""
Tests for LLM backends (OpenAI, Anthropic, Gemini).

These tests verify the backend implementations work correctly.
Most tests are mocked to avoid API calls, but there are also
integration tests that require actual API keys.

Run with: pytest tests/test_llm_backends.py -v

For integration tests, set environment variables:
- OPENAI_API_KEY
- ANTHROPIC_API_KEY
- GOOGLE_API_KEY
"""
import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent import LLMResponse, ToolCall


# =============================================================================
# Test Backend Initialization
# =============================================================================

class TestBackendInitialization:
    """Tests for backend initialization."""
    
    def test_openai_backend_requires_api_key(self):
        """Test that OpenAI backend requires API key."""
        # Clear env var if set
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OPENAI_API_KEY", None)
            
            from llm_backends import OpenAIBackend
            with pytest.raises(ValueError, match="API key required"):
                OpenAIBackend()
    
    def test_anthropic_backend_requires_api_key(self):
        """Test that Anthropic backend requires API key."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            
            from llm_backends import AnthropicBackend
            with pytest.raises(ValueError, match="API key required"):
                AnthropicBackend()
    
    def test_gemini_backend_requires_api_key(self):
        """Test that Gemini backend requires API key."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("GOOGLE_API_KEY", None)
            
            from llm_backends import GeminiBackend
            with pytest.raises(ValueError, match="API key required"):
                GeminiBackend()
    
    def test_create_backend_factory(self):
        """Test the create_backend factory function."""
        from llm_backends import create_backend
        
        with pytest.raises(ValueError, match="Unknown provider"):
            create_backend("invalid_provider", api_key="test")


# =============================================================================
# Test Message Conversion
# =============================================================================

class TestMessageConversion:
    """Tests for message format conversion."""
    
    def test_anthropic_message_conversion(self):
        """Test OpenAI to Anthropic message conversion."""
        from llm_backends import AnthropicBackend
        
        # Mock the Anthropic client
        with patch("llm_backends.AsyncAnthropic"):
            backend = AnthropicBackend(api_key="test-key")
        
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]
        
        system, converted = backend._convert_messages_to_anthropic(messages)
        
        assert system == "You are a helpful assistant."
        assert len(converted) == 3  # Excludes system message
        assert converted[0]["role"] == "user"
        assert converted[0]["content"] == "Hello"
        assert converted[1]["role"] == "assistant"
        assert converted[2]["role"] == "user"
    
    def test_anthropic_tool_call_message_conversion(self):
        """Test conversion of messages with tool calls."""
        from llm_backends import AnthropicBackend
        
        with patch("llm_backends.AsyncAnthropic"):
            backend = AnthropicBackend(api_key="test-key")
        
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Click button 1"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_123",
                    "type": "function",
                    "function": {
                        "name": "click",
                        "arguments": '{"index": 1}'
                    }
                }]
            },
            {
                "role": "tool",
                "tool_call_id": "call_123",
                "content": "Clicked element [1]"
            }
        ]
        
        system, converted = backend._convert_messages_to_anthropic(messages)
        
        assert system == "System prompt"
        assert len(converted) == 3
        
        # Check tool call message
        assistant_msg = converted[1]
        assert assistant_msg["role"] == "assistant"
        assert isinstance(assistant_msg["content"], list)
        assert assistant_msg["content"][0]["type"] == "tool_use"
        
        # Check tool result message
        tool_result_msg = converted[2]
        assert tool_result_msg["role"] == "user"
        assert tool_result_msg["content"][0]["type"] == "tool_result"
    
    def test_anthropic_tool_schema_conversion(self):
        """Test OpenAI to Anthropic tool schema conversion."""
        from llm_backends import AnthropicBackend
        
        with patch("llm_backends.AsyncAnthropic"):
            backend = AnthropicBackend(api_key="test-key")
        
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "click",
                    "description": "Click an element",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer"}
                        },
                        "required": ["index"]
                    }
                }
            }
        ]
        
        anthropic_tools = backend._convert_tools_to_anthropic(openai_tools)
        
        assert len(anthropic_tools) == 1
        assert anthropic_tools[0]["name"] == "click"
        assert anthropic_tools[0]["description"] == "Click an element"
        assert "input_schema" in anthropic_tools[0]


# =============================================================================
# Test Response Parsing
# =============================================================================

class TestResponseParsing:
    """Tests for LLM response parsing."""
    
    def test_llm_response_with_tool_calls(self):
        """Test LLMResponse with tool calls."""
        tool_calls = [
            ToolCall(id="1", name="click", arguments={"index": 5}),
            ToolCall(id="2", name="scroll", arguments={"direction": "down"}),
        ]
        
        response = LLMResponse(
            content=None,
            tool_calls=tool_calls,
            finish_reason="tool_calls"
        )
        
        assert response.has_tool_calls
        assert len(response.tool_calls) == 2
        assert response.tool_calls[0].name == "click"
    
    def test_llm_response_with_content(self):
        """Test LLMResponse with text content."""
        response = LLMResponse(
            content="Task completed successfully",
            tool_calls=[],
            finish_reason="stop"
        )
        
        assert not response.has_tool_calls
        assert response.content == "Task completed successfully"
    
    def test_tool_call_dataclass(self):
        """Test ToolCall dataclass."""
        tc = ToolCall(
            id="call_abc123",
            name="type",
            arguments={"index": 3, "text": "hello"}
        )
        
        assert tc.id == "call_abc123"
        assert tc.name == "type"
        assert tc.arguments["index"] == 3
        assert tc.arguments["text"] == "hello"


# =============================================================================
# Integration Tests (Require API Keys)
# =============================================================================

@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set"
)
class TestOpenAIIntegration:
    """Integration tests for OpenAI backend."""
    
    @pytest.mark.asyncio
    async def test_openai_simple_message(self):
        """Test simple message with OpenAI."""
        from llm_backends import OpenAIBackend
        
        backend = OpenAIBackend(model="gpt-4o-mini")
        
        messages = [
            {"role": "user", "content": "Say 'hello' and nothing else."}
        ]
        
        response = await backend.generate(messages, tools=[])
        
        assert response.content is not None
        assert "hello" in response.content.lower()
    
    @pytest.mark.asyncio
    async def test_openai_with_tools(self):
        """Test tool calling with OpenAI."""
        from llm_backends import OpenAIBackend
        from tools import get_tool_schemas
        
        backend = OpenAIBackend(model="gpt-4o-mini")
        tools = get_tool_schemas(format="openai", include_tools=["click", "done"])
        
        messages = [
            {"role": "system", "content": "You are a browser automation agent. Use the click tool to click element 1."},
            {"role": "user", "content": "Click element [1]"}
        ]
        
        response = await backend.generate(messages, tools)
        
        # Should return a tool call
        assert response.has_tool_calls
        assert response.tool_calls[0].name == "click"


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set"
)
class TestAnthropicIntegration:
    """Integration tests for Anthropic backend."""
    
    @pytest.mark.asyncio
    async def test_anthropic_simple_message(self):
        """Test simple message with Anthropic."""
        from llm_backends import AnthropicBackend
        
        backend = AnthropicBackend(model="claude-3-5-haiku-latest")
        
        messages = [
            {"role": "user", "content": "Say 'hello' and nothing else."}
        ]
        
        response = await backend.generate(messages, tools=[])
        
        assert response.content is not None
        assert "hello" in response.content.lower()
    
    @pytest.mark.asyncio
    async def test_anthropic_with_tools(self):
        """Test tool calling with Anthropic."""
        from llm_backends import AnthropicBackend
        from tools import get_tool_schemas
        
        backend = AnthropicBackend(model="claude-3-5-haiku-latest")
        tools = get_tool_schemas(format="openai", include_tools=["click", "done"])
        
        messages = [
            {"role": "system", "content": "You are a browser automation agent. Use the click tool to click element 1."},
            {"role": "user", "content": "Click element [1]"}
        ]
        
        response = await backend.generate(messages, tools)
        
        assert response.has_tool_calls
        assert response.tool_calls[0].name == "click"


@pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY not set"
)
class TestGeminiIntegration:
    """Integration tests for Gemini backend."""
    
    @pytest.mark.asyncio
    async def test_gemini_simple_message(self):
        """Test simple message with Gemini."""
        from llm_backends import GeminiBackend
        
        backend = GeminiBackend(model="gemini-2.0-flash")
        
        messages = [
            {"role": "user", "content": "Say 'hello' and nothing else."}
        ]
        
        response = await backend.generate(messages, tools=[])
        
        assert response.content is not None
        assert "hello" in response.content.lower()


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

