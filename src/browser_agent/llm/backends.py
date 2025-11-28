"""
LLM Backends - Real implementations for OpenAI, Anthropic, and Google Gemini.

This module provides production-ready LLM backends that implement the LLMBackend
protocol for use with the Agent class.

Usage:
    from browser_agent import OpenAIBackend, AnthropicBackend, GeminiBackend
    
    backend = OpenAIBackend(api_key="sk-...")
    # or
    backend = AnthropicBackend(api_key="sk-ant-...")
    # or
    backend = GeminiBackend(api_key="...")
    
    agent = Agent(backend)
    result = await agent.run("Search for Python tutorials")
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from browser_agent.core.types import LLMResponse, ToolCall

logger = logging.getLogger("browser_agent")


# =============================================================================
# OpenAI Backend
# =============================================================================

class OpenAIBackend:
    """
    OpenAI GPT backend for the browser agent.
    
    Uses the openai Python SDK to call GPT-4o or other models with tool calling.
    
    Requirements:
        pip install browser-agent[openai]
    
    Usage:
        backend = OpenAIBackend(api_key="sk-...", model="gpt-4o")
        agent = Agent(backend)
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o",
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ):
        """
        Initialize the OpenAI backend.
        
        Args:
            api_key: OpenAI API key. Defaults to OPENAI_API_KEY env var.
            model: Model to use (gpt-4o, gpt-4o-mini, gpt-4-turbo, etc.)
            temperature: Sampling temperature (0.0 = deterministic).
            max_tokens: Maximum tokens in response.
        """
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError(
                "OpenAI SDK not installed. Run: pip install browser-agent[openai]"
            )
        
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY env var or pass api_key."
            )
        
        self.client = AsyncOpenAI(api_key=self.api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
    
    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> LLMResponse:
        """Generate a response using OpenAI's API."""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools if tools else None,
                tool_choice="auto" if tools else None,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            
            choice = response.choices[0]
            message = choice.message
            
            # Extract tool calls if present
            tool_calls = []
            if message.tool_calls:
                for tc in message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    
                    tool_calls.append(ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    ))
            
            return LLMResponse(
                content=message.content,
                tool_calls=tool_calls,
                finish_reason=choice.finish_reason or "stop",
            )
        
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise
    
    async def close(self) -> None:
        """Close the underlying HTTP client (P1-20)."""
        if hasattr(self.client, 'close'):
            await self.client.close()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# =============================================================================
# Anthropic Backend
# =============================================================================

class AnthropicBackend:
    """
    Anthropic Claude backend for the browser agent.
    
    Uses the anthropic Python SDK to call Claude models with tool use.
    
    Requirements:
        pip install browser-agent[anthropic]
    
    Usage:
        backend = AnthropicBackend(api_key="sk-ant-...", model="claude-sonnet-4-20250514")
        agent = Agent(backend)
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ):
        """
        Initialize the Anthropic backend.
        
        Args:
            api_key: Anthropic API key. Defaults to ANTHROPIC_API_KEY env var.
            model: Model to use (claude-sonnet-4-20250514, claude-3-5-sonnet, etc.)
            temperature: Sampling temperature (0.0 = deterministic).
            max_tokens: Maximum tokens in response.
        """
        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            raise ImportError(
                "Anthropic SDK not installed. Run: pip install browser-agent[anthropic]"
            )
        
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY env var or pass api_key."
            )
        
        self.client = AsyncAnthropic(api_key=self.api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
    
    def _convert_messages_to_anthropic(
        self,
        messages: List[Dict[str, Any]],
    ) -> tuple[str, List[Dict[str, Any]]]:
        """
        Convert OpenAI-style messages to Anthropic format.
        
        Handles:
        - System message concatenation (multiple system messages are joined)
        - Role alternation (consecutive same-role messages are merged)
        - Tool results grouping (multiple tool results go into one user message)
        
        Returns:
            Tuple of (system_prompt, messages)
        """
        system_parts: List[str] = []
        anthropic_messages: List[Dict[str, Any]] = []
        
        # First pass: collect all messages, converting to Anthropic format
        pending_tool_results: List[Dict[str, Any]] = []
        
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            
            if role == "system":
                # Concatenate all system messages
                if content:
                    system_parts.append(content)
                    
            elif role == "user":
                # Flush any pending tool results first
                if pending_tool_results:
                    self._append_or_merge(
                        anthropic_messages,
                        "user",
                        pending_tool_results.copy()
                    )
                    pending_tool_results.clear()
                
                # Add user message
                self._append_or_merge(
                    anthropic_messages,
                    "user",
                    [{"type": "text", "text": content or ""}]
                )
                    
            elif role == "assistant":
                # Flush any pending tool results first
                if pending_tool_results:
                    self._append_or_merge(
                        anthropic_messages,
                        "user",
                        pending_tool_results.copy()
                    )
                    pending_tool_results.clear()
                
                # Handle assistant messages with tool calls
                if msg.get("tool_calls"):
                    content_blocks = []
                    if content:
                        content_blocks.append({"type": "text", "text": content})
                    
                    for tc in msg["tool_calls"]:
                        # Parse arguments if they're a string
                        args = tc["function"]["arguments"]
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {}
                        
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "input": args,
                        })
                    
                    self._append_or_merge(
                        anthropic_messages,
                        "assistant",
                        content_blocks
                    )
                else:
                    self._append_or_merge(
                        anthropic_messages,
                        "assistant",
                        [{"type": "text", "text": content or ""}]
                    )
                    
            elif role == "tool":
                # Collect tool results - they'll be flushed as a single user message
                pending_tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id"),
                    "content": content or "",
                })
        
        # Flush any remaining tool results
        if pending_tool_results:
            self._append_or_merge(
                anthropic_messages,
                "user",
                pending_tool_results
            )
        
        # Join system prompts with newlines
        system_prompt = "\n\n".join(system_parts)
        
        # Ensure first message is user role (P1-19: Anthropic requires this)
        if anthropic_messages and anthropic_messages[0]["role"] != "user":
            anthropic_messages.insert(0, {
                "role": "user",
                "content": "Please proceed with the task."
            })
        
        return system_prompt, anthropic_messages
    
    def _append_or_merge(
        self,
        messages: List[Dict[str, Any]],
        role: str,
        content_blocks: List[Dict[str, Any]],
    ) -> None:
        """
        Append content to messages, merging with previous message if same role.
        
        This ensures Anthropic's alternating role requirement is satisfied.
        """
        if not content_blocks:
            return
            
        if messages and messages[-1]["role"] == role:
            # Merge with previous message of same role
            prev_content = messages[-1]["content"]
            if isinstance(prev_content, str):
                # Convert string content to list format
                prev_content = [{"type": "text", "text": prev_content}]
            prev_content.extend(content_blocks)
            messages[-1]["content"] = prev_content
        else:
            # Add new message
            # If only one text block, can use string format
            if (len(content_blocks) == 1 and 
                content_blocks[0].get("type") == "text"):
                messages.append({
                    "role": role,
                    "content": content_blocks[0]["text"],
                })
            else:
                messages.append({
                    "role": role,
                    "content": content_blocks,
                })
    
    def _convert_tools_to_anthropic(
        self,
        tools: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Convert OpenAI-style tools to Anthropic format."""
        anthropic_tools = []
        
        for tool in tools:
            if tool.get("type") == "function":
                func = tool["function"]
                anthropic_tools.append({
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
                })
        
        return anthropic_tools
    
    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> LLMResponse:
        """Generate a response using Anthropic's API."""
        try:
            system_prompt, anthropic_messages = self._convert_messages_to_anthropic(messages)
            anthropic_tools = self._convert_tools_to_anthropic(tools)
            
            response = await self.client.messages.create(
                model=self.model,
                system=system_prompt if system_prompt else None,
                messages=anthropic_messages,
                tools=anthropic_tools if anthropic_tools else None,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            
            # Extract content and tool calls
            content_text = ""
            tool_calls = []
            
            for block in response.content:
                if block.type == "text":
                    content_text += block.text
                elif block.type == "tool_use":
                    tool_calls.append(ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=dict(block.input) if block.input else {},
                    ))
            
            return LLMResponse(
                content=content_text if content_text else None,
                tool_calls=tool_calls,
                finish_reason=response.stop_reason or "stop",
            )
        
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            raise
    
    async def close(self) -> None:
        """Close the underlying HTTP client (P1-20)."""
        if hasattr(self.client, 'close'):
            await self.client.close()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# =============================================================================
# Google Gemini Backend
# =============================================================================

class GeminiBackend:
    """
    Google Gemini backend for the browser agent.
    
    Uses the google-genai Python SDK to call Gemini models with function calling.
    
    Requirements:
        pip install browser-agent[gemini]
    
    Usage:
        backend = GeminiBackend(api_key="...", model="gemini-2.5-flash")
        agent = Agent(backend)
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ):
        """
        Initialize the Gemini backend.
        
        Args:
            api_key: Google AI API key. Defaults to GOOGLE_API_KEY env var.
            model: Model to use (gemini-2.5-flash, gemini-2.0-flash, etc.)
            temperature: Sampling temperature (0.0 = deterministic).
            max_tokens: Maximum tokens in response.
        """
        try:
            from google import genai
            from google.genai import types
            self._genai = genai
            self._types = types
        except ImportError:
            raise ImportError(
                "Google GenAI SDK not installed. Run: pip install browser-agent[gemini]"
            )
        
        self.api_key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Google API key required. Set GOOGLE_API_KEY env var or pass api_key."
            )
        
        self.client = genai.Client(api_key=self.api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
    
    def _convert_messages_to_gemini(
        self,
        messages: List[Dict[str, Any]],
    ) -> tuple[str, List[Any]]:
        """
        Convert OpenAI-style messages to Gemini format.
        
        Handles:
        - System message concatenation
        - Role merging for consecutive same-role messages
        - Tool response grouping
        - Proper tool_call_id to function_name mapping (P0-2 fix)
        
        Returns:
            Tuple of (system_instruction, contents)
        """
        types = self._types
        system_parts: List[str] = []
        contents: List[Any] = []
        
        # Build tool_call_id -> function_name mapping first (P0-2 fix)
        # This is needed because Gemini requires the function name for tool responses,
        # but OpenAI's tool messages only contain tool_call_id and content
        tool_call_id_to_name: Dict[str, str] = {}
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tc_id = tc.get("id", "")
                    func_name = tc.get("function", {}).get("name", "")
                    if tc_id and func_name:
                        tool_call_id_to_name[tc_id] = func_name
        
        # Track pending tool responses to group them
        pending_tool_responses: List[Any] = []
        
        def flush_tool_responses():
            """Flush pending tool responses into a single content."""
            nonlocal pending_tool_responses
            if pending_tool_responses:
                self._append_or_merge_gemini(
                    contents,
                    "user",  # Tool responses are sent as user role in Gemini
                    pending_tool_responses.copy()
                )
                pending_tool_responses.clear()
        
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            
            if role == "system":
                # Concatenate all system messages
                if content:
                    system_parts.append(content)
                    
            elif role == "user":
                # Flush any pending tool responses first
                flush_tool_responses()
                
                self._append_or_merge_gemini(
                    contents,
                    "user",
                    [types.Part.from_text(text=content or "")]
                )
                    
            elif role == "assistant":
                # Flush any pending tool responses first
                flush_tool_responses()
                
                if msg.get("tool_calls"):
                    # Assistant message with tool calls
                    parts = []
                    if content:
                        parts.append(types.Part.from_text(text=content))
                    
                    for tc in msg["tool_calls"]:
                        args = tc["function"]["arguments"]
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {}
                        
                        parts.append(types.Part.from_function_call(
                            name=tc["function"]["name"],
                            args=args,
                        ))
                    
                    self._append_or_merge_gemini(contents, "model", parts)
                else:
                    self._append_or_merge_gemini(
                        contents,
                        "model",
                        [types.Part.from_text(text=content or "")]
                    )
                    
            elif role == "tool":
                # Collect tool responses - they'll be flushed together
                tool_call_id = msg.get("tool_call_id", "")
                # Look up the actual function name from our mapping (P0-2 fix)
                func_name = tool_call_id_to_name.get(tool_call_id, "unknown")
                
                if func_name == "unknown":
                    logger.warning(
                        f"Could not find function name for tool_call_id: {tool_call_id}. "
                        "This may cause Gemini API errors."
                    )
                
                pending_tool_responses.append(
                    types.Part.from_function_response(
                        name=func_name,
                        response={"result": content},
                    )
                )
        
        # Flush any remaining tool responses
        flush_tool_responses()
        
        # Join system instructions
        system_instruction = "\n\n".join(system_parts)
        
        return system_instruction, contents
    
    def _append_or_merge_gemini(
        self,
        contents: List[Any],
        role: str,
        parts: List[Any],
    ) -> None:
        """
        Append parts to contents, merging with previous content if same role.
        """
        types = self._types
        
        if not parts:
            return
        
        if contents and contents[-1].role == role:
            # Merge with previous content of same role
            existing_parts = list(contents[-1].parts)
            existing_parts.extend(parts)
            contents[-1] = types.Content(role=role, parts=existing_parts)
        else:
            # Add new content
            contents.append(types.Content(role=role, parts=parts))
    
    def _convert_tools_to_gemini(
        self,
        tools: List[Dict[str, Any]],
    ) -> List[Any]:
        """Convert OpenAI-style tools to Gemini format."""
        types = self._types
        function_declarations = []
        
        for tool in tools:
            if tool.get("type") == "function":
                func = tool["function"]
                function_declarations.append(types.FunctionDeclaration(
                    name=func["name"],
                    description=func.get("description", ""),
                    parameters_json_schema=func.get("parameters", {"type": "object", "properties": {}}),
                ))
        
        if function_declarations:
            return [types.Tool(function_declarations=function_declarations)]
        return []
    
    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> LLMResponse:
        """Generate a response using Gemini's API."""
        try:
            types = self._types
            system_instruction, contents = self._convert_messages_to_gemini(messages)
            gemini_tools = self._convert_tools_to_gemini(tools)
            
            config = types.GenerateContentConfig(
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
                tools=gemini_tools if gemini_tools else None,
            )
            
            if system_instruction:
                config.system_instruction = system_instruction
            
            # Use async generate_content
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=contents if contents else "Hello",
                config=config,
            )
            
            # Extract content and function calls
            content_text = ""
            tool_calls = []
            
            if response.text:
                content_text = response.text
            
            if response.function_calls:
                for i, fc in enumerate(response.function_calls):
                    tool_calls.append(ToolCall(
                        id=f"{fc.name}_{i}",
                        name=fc.name,
                        arguments=dict(fc.args) if fc.args else {},
                    ))
            
            # Determine finish reason
            finish_reason = "stop"
            if tool_calls:
                finish_reason = "tool_calls"
            
            return LLMResponse(
                content=content_text if content_text else None,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
            )
        
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise
    
    async def close(self) -> None:
        """Close the underlying HTTP client (P1-20)."""
        # Gemini client may not have an async close method
        pass
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# =============================================================================
# Factory Function
# =============================================================================

def create_backend(
    provider: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs,
) -> OpenAIBackend | AnthropicBackend | GeminiBackend:
    """
    Factory function to create an LLM backend.
    
    Args:
        provider: One of "openai", "anthropic", "gemini".
        api_key: API key (optional, will use env var if not provided).
        model: Model name (optional, will use default if not provided).
        **kwargs: Additional arguments passed to the backend constructor.
    
    Returns:
        An LLM backend instance.
    
    Example:
        backend = create_backend("openai", model="gpt-4o-mini")
        backend = create_backend("anthropic")
        backend = create_backend("gemini", api_key="...")
    """
    provider = provider.lower()
    
    if provider == "openai":
        return OpenAIBackend(
            api_key=api_key,
            model=model or "gpt-4o",
            **kwargs,
        )
    elif provider == "anthropic":
        return AnthropicBackend(
            api_key=api_key,
            model=model or "claude-sonnet-4-20250514",
            **kwargs,
        )
    elif provider == "gemini":
        return GeminiBackend(
            api_key=api_key,
            model=model or "gemini-2.5-flash",
            **kwargs,
        )
    else:
        raise ValueError(
            f"Unknown provider: {provider}. Use 'openai', 'anthropic', or 'gemini'."
        )
