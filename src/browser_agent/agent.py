"""
Agent - High-level agent loop for LLM-driven browser automation.

This module provides a ready-to-use agent that can execute tasks
using an LLM backend to decide actions.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

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
    
    # Context management: keep only last N action/result pairs in history
    # This prevents unbounded context growth
    max_history_actions: int = 10
    
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
    3. Act: Execute the tool (only first tool per turn for safety)
    4. Repeat until done tool is called or max steps reached
    
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
        # Create history locally (not on self) to avoid concurrency issues
        history = AgentHistory(task=task)
        start_time = time.time()
        
        # Set up browser
        browser = self._browser
        if browser is None:
            browser_config = self.config.browser_config or BrowserConfig()
            browser = Browser(config=browser_config)
            await browser.start()
        
        # Track action history for context management (separate from full message history)
        action_history: List[Dict[str, Any]] = []
        
        try:
            # Navigate to start URL if provided
            if start_url:
                await browser.navigate(start_url)
            
            # Get tool schemas
            tools = get_tool_schemas(format="openai")
            
            consecutive_failures = 0
            
            for step_num in range(1, self.config.max_steps + 1):
                step_start = time.time()
                
                try:
                    # Get current state
                    state = await browser.get_state(
                        include_screenshot=self.config.include_screenshot_in_state
                    )
                    
                    # Build messages with context pruning
                    messages = self._build_messages(task, state, action_history)
                    
                    if self.config.verbose:
                        logger.info(f"Step {step_num}: Getting LLM response...")
                    
                    # Get LLM response
                    response = await self.llm.generate(messages, tools)
                    
                    # Handle response
                    if response.has_tool_calls:
                        # P1-18: Execute multiple tool calls, but stop on navigation/state-changing actions
                        # Navigation tools that should trigger a state refresh after execution
                        navigation_tools = {"navigate", "click", "go_back", "go_forward", "refresh"}
                        
                        for tool_idx, tool_call in enumerate(response.tool_calls):
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
                            history.add_step(step)
                            
                            # Add to action history (with proper JSON serialization)
                            action_history.append({
                                "tool_call": {
                                    "id": tool_call.id,
                                    "name": tool_call.name,
                                    "arguments": tool_call.arguments,
                                },
                                "result": result.to_message(),
                            })
                            
                            if self.config.verbose:
                                logger.info(f"  {result.to_message()}")
                            
                            # Check if done (only via the done tool, not text matching)
                            if result.is_done:
                                history.is_complete = True
                                history.final_result = result.done_message
                                history.total_duration_ms = (time.time() - start_time) * 1000
                                return history
                            
                            # Track failures
                            if result.result and not result.result.success:
                                consecutive_failures += 1
                                if consecutive_failures >= self.config.max_failures:
                                    history.final_result = f"Stopped after {consecutive_failures} consecutive failures"
                                    history.total_duration_ms = (time.time() - start_time) * 1000
                                    return history
                            else:
                                consecutive_failures = 0
                            
                            # P1-18: Stop executing more tools if this was a navigation action
                            # (subsequent tools may reference stale state)
                            if tool_call.name in navigation_tools:
                                if tool_idx < len(response.tool_calls) - 1 and self.config.verbose:
                                    remaining = len(response.tool_calls) - tool_idx - 1
                                    logger.info(
                                        f"  Skipping {remaining} remaining tool calls after navigation action"
                                    )
                                break
                        
                        # Prune action history to prevent context overflow
                        if len(action_history) > self.config.max_history_actions:
                            action_history = action_history[-self.config.max_history_actions:]
                    
                    elif response.content:
                        # LLM responded with text instead of tool call
                        # Log it but don't use text-based completion detection
                        if self.config.verbose:
                            logger.info(f"  LLM message (no tool call): {response.content[:200]}...")
                        
                        # Add a hint to the action history to guide the LLM
                        action_history.append({
                            "assistant_message": response.content[:500],
                            "system_note": "Please use the 'done' tool to signal task completion, or another tool to continue.",
                        })
                
                except Exception as step_error:
                    # Handle errors within the step
                    logger.error(f"Error in step {step_num}: {step_error}", exc_info=True)
                    
                    # Capture screenshot on error if configured
                    error_screenshot = None
                    if self.config.screenshot_on_error:
                        try:
                            error_screenshot = await browser.screenshot()
                        except Exception:
                            pass  # Best effort
                    
                    # Record the failed step
                    step = AgentStep(
                        step_number=step_num,
                        action_type="error",
                        action_params={"error": str(step_error)},
                        result=ActionResult.error("step", str(step_error)),
                        screenshot_after=error_screenshot,
                        duration_ms=(time.time() - step_start) * 1000,
                    )
                    history.add_step(step)
                    
                    consecutive_failures += 1
                    if consecutive_failures >= self.config.max_failures:
                        history.final_result = f"Stopped after {consecutive_failures} consecutive failures. Last error: {step_error}"
                        history.total_duration_ms = (time.time() - start_time) * 1000
                        return history
            
            # Max steps reached
            history.final_result = f"Max steps ({self.config.max_steps}) reached without task completion"
            history.total_duration_ms = (time.time() - start_time) * 1000
            return history
        
        except Exception as e:
            # Handle fatal errors outside the step loop
            logger.error(f"Fatal error in agent run: {e}", exc_info=True)
            history.final_result = f"Fatal error: {e}"
            history.total_duration_ms = (time.time() - start_time) * 1000
            return history
        
        finally:
            # Clean up browser if we created it
            if self._owns_browser and browser:
                await browser.stop()
    
    def _build_messages(
        self,
        task: str,
        current_state: BrowserState,
        action_history: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Build the message list for the LLM with context pruning.
        
        Strategy: Keep system prompt + task + recent action history + current state.
        This prevents unbounded context growth while maintaining relevant history.
        """
        messages = [
            {"role": "system", "content": get_system_prompt()},
            {"role": "user", "content": f"Task: {task}\n\nPlease complete this task by interacting with the browser. Use the 'done' tool when the task is complete."},
        ]
        
        # Add action history (pruned to max_history_actions)
        for action in action_history:
            if "tool_call" in action:
                tc = action["tool_call"]
                # Use json.dumps for proper JSON serialization (not str())
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        }
                    }]
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": action["result"],
                })
            elif "assistant_message" in action:
                messages.append({
                    "role": "assistant",
                    "content": action["assistant_message"],
                })
                messages.append({
                    "role": "user",
                    "content": action.get("system_note", "Please continue with the task."),
                })
        
        # Add current browser state (always fresh, not from history)
        # Include screenshot as vision content if available
        state_content = self._format_state_content(current_state)
        messages.append({
            "role": "user",
            "content": state_content,
        })
        
        return messages
    
    def _format_state_content(self, state: BrowserState) -> Any:
        """
        Format browser state for the LLM, including screenshot as vision content.
        
        Returns either a string (text-only) or a list of content blocks (with image).
        """
        text_content = f"Current browser state:\n\n{state.to_prompt(include_screenshot=False)}"
        
        # If screenshot is available and configured, include it as vision content
        if self.config.include_screenshot_in_state and state.screenshot_base64:
            # Return multimodal content for vision models
            return [
                {
                    "type": "text",
                    "text": text_content,
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{state.screenshot_base64}",
                        "detail": "high",  # Use high detail for better element recognition
                    }
                }
            ]
        
        # Text-only content
        return text_content
    
    def _format_state_message(self, state: BrowserState) -> str:
        """Format browser state for the LLM (text-only version)."""
        return f"Current browser state:\n\n{state.to_prompt(include_screenshot=False)}"


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
