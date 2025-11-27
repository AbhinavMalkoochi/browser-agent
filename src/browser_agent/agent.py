"""
Agent - High-level agent loop for LLM-driven browser automation.

This module provides a ready-to-use agent that can execute tasks
using an LLM backend to decide actions.
"""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

from browser_agent.browser import Browser, BrowserConfig
from browser_agent.core.models import ActionResult, AgentHistory, AgentStep, BrowserState
from browser_agent.core.types import LLMResponse, ToolCall
from browser_agent.llm.tools import (
    ToolExecutionResult,
    execute_tool,
    get_system_prompt,
    get_tool_schemas,
)

logger = logging.getLogger("browser_agent")


# =============================================================================
# LLM Backend Protocol
# =============================================================================

@runtime_checkable
class LLMBackend(Protocol):
    """Protocol for LLM backends that can generate tool calls."""
    
    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> LLMResponse:
        """
        Generate a response given messages and available tools.
        
        Args:
            messages: Conversation history in OpenAI format.
            tools: Available tools in OpenAI format.
            
        Returns:
            LLMResponse with either a message or tool calls.
        """
        ...


# =============================================================================
# Agent Configuration
# =============================================================================

@dataclass
class AgentConfig:
    """Configuration for the Agent."""
    
    max_steps: int = 50
    max_failures: int = 5
    screenshot_on_error: bool = True
    include_screenshot_in_state: bool = True
    verbose: bool = False
    
    # Browser config (will be used if no browser is provided)
    browser_config: Optional[BrowserConfig] = None


# =============================================================================
# Agent Class
# =============================================================================

class Agent:
    """
    Browser automation agent powered by an LLM.
    
    The agent follows a ReAct-style loop:
    1. Observe: Get browser state
    2. Think: Send state to LLM, get tool call
    3. Act: Execute the tool
    4. Repeat until done or max steps reached
    
    Usage:
        backend = OpenAIBackend(api_key="...")  # or AnthropicBackend, etc.
        agent = Agent(backend)
        
        result = await agent.run("Search for Python tutorials on Google")
    """
    
    def __init__(
        self,
        llm: LLMBackend,
        config: Optional[AgentConfig] = None,
        browser: Optional[Browser] = None,
    ):
        """
        Initialize the agent.
        
        Args:
            llm: LLM backend for generating actions.
            config: Agent configuration.
            browser: Optional pre-configured Browser instance.
        """
        self.llm = llm
        self.config = config or AgentConfig()
        self._browser = browser
        self._owns_browser = browser is None
        self._history: Optional[AgentHistory] = None
    
    async def run(
        self,
        task: str,
        start_url: Optional[str] = None,
    ) -> AgentHistory:
        """
        Run the agent to complete a task.
        
        Args:
            task: Natural language description of the task to complete.
            start_url: Optional URL to navigate to before starting.
            
        Returns:
            AgentHistory containing all steps and the final result.
        """
        self._history = AgentHistory(task=task)
        start_time = time.time()
        
        # Set up browser
        browser = self._browser
        if browser is None:
            browser_config = self.config.browser_config or BrowserConfig()
            browser = Browser(config=browser_config)
            await browser.start()
        
        try:
            # Navigate to start URL if provided
            if start_url:
                await browser.navigate(start_url)
            
            # Initialize conversation
            messages = self._init_messages(task)
            tools = get_tool_schemas(format="openai")
            
            consecutive_failures = 0
            
            for step_num in range(1, self.config.max_steps + 1):
                step_start = time.time()
                
                # Get current state
                state = await browser.get_state(
                    include_screenshot=self.config.include_screenshot_in_state
                )
                
                # Add state to messages
                messages.append({
                    "role": "user",
                    "content": self._format_state_message(state),
                })
                
                if self.config.verbose:
                    logger.info(f"Step {step_num}: Getting LLM response...")
                
                # Get LLM response
                response = await self.llm.generate(messages, tools)
                
                # Handle response
                if response.has_tool_calls:
                    # Execute tool calls
                    for tool_call in response.tool_calls:
                        result = await execute_tool(
                            browser,
                            tool_call.name,
                            tool_call.arguments,
                        )
                        
                        # Record step
                        step = AgentStep(
                            step_number=step_num,
                            action_type=tool_call.name,
                            action_params=tool_call.arguments,
                            result=result.result,
                            url_before=state.url,
                            duration_ms=(time.time() - step_start) * 1000,
                        )
                        self._history.add_step(step)
                        
                        # Add tool result to messages
                        messages.append({
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{
                                "id": tool_call.id,
                                "type": "function",
                                "function": {
                                    "name": tool_call.name,
                                    "arguments": str(tool_call.arguments),
                                }
                            }]
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result.to_message(),
                        })
                        
                        if self.config.verbose:
                            logger.info(f"  {result.to_message()}")
                        
                        # Check if done
                        if result.is_done:
                            self._history.is_complete = True
                            self._history.final_result = result.done_message
                            self._history.total_duration_ms = (time.time() - start_time) * 1000
                            return self._history
                        
                        # Track failures
                        if result.result and not result.result.success:
                            consecutive_failures += 1
                            if consecutive_failures >= self.config.max_failures:
                                self._history.final_result = f"Stopped after {consecutive_failures} consecutive failures"
                                self._history.total_duration_ms = (time.time() - start_time) * 1000
                                return self._history
                        else:
                            consecutive_failures = 0
                
                elif response.content:
                    # LLM responded with text instead of tool call
                    messages.append({
                        "role": "assistant",
                        "content": response.content,
                    })
                    
                    if self.config.verbose:
                        logger.info(f"  LLM message: {response.content[:200]}...")
                    
                    # Check if this looks like a completion message
                    if any(phrase in response.content.lower() for phrase in [
                        "task complete", "done", "finished", "accomplished", "completed"
                    ]):
                        self._history.is_complete = True
                        self._history.final_result = response.content
                        break
            
            # Max steps reached
            if not self._history.is_complete:
                self._history.final_result = f"Max steps ({self.config.max_steps}) reached"
            
            self._history.total_duration_ms = (time.time() - start_time) * 1000
            return self._history
        
        finally:
            # Clean up browser if we created it
            if self._owns_browser and browser:
                await browser.stop()
    
    def _init_messages(self, task: str) -> List[Dict[str, Any]]:
        """Initialize the conversation with system prompt and task."""
        return [
            {"role": "system", "content": get_system_prompt()},
            {"role": "user", "content": f"Task: {task}\n\nPlease complete this task by interacting with the browser."},
        ]
    
    def _format_state_message(self, state: BrowserState) -> str:
        """Format browser state for the LLM."""
        return state.to_prompt(include_screenshot=self.config.include_screenshot_in_state)
    
    @property
    def history(self) -> Optional[AgentHistory]:
        """Get the history from the last run."""
        return self._history


# =============================================================================
# Example LLM Backend (for reference)
# =============================================================================

class DummyLLMBackend:
    """
    A dummy LLM backend for testing.
    
    This backend doesn't actually call an LLM - it just returns
    a "done" action after a few steps. Useful for testing the
    agent loop without LLM costs.
    """
    
    def __init__(self, max_steps: int = 3):
        self.max_steps = max_steps
        self.step_count = 0
    
    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> LLMResponse:
        self.step_count += 1
        
        if self.step_count >= self.max_steps:
            return LLMResponse(
                tool_calls=[ToolCall(
                    id=f"call_{self.step_count}",
                    name="done",
                    arguments={"message": "Dummy agent completed after max steps"}
                )]
            )
        
        # Default action: scroll down
        return LLMResponse(
            tool_calls=[ToolCall(
                id=f"call_{self.step_count}",
                name="scroll",
                arguments={"direction": "down", "amount": 300}
            )]
        )
