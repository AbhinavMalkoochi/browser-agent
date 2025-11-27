#!/usr/bin/env python3
"""
Agent Demo

Demonstrates the Agent class with a dummy LLM backend.
For real usage, implement your own LLMBackend that calls
OpenAI, Anthropic, or another LLM API.

Prerequisites:
- Chrome must be running with debugging enabled:
  python -m browser_agent.launch_chrome
"""
import asyncio

from browser_agent import Agent, AgentConfig, LLMResponse, ToolCall, BrowserConfig


class SimpleDemoBackend:
    """
    A simple demo backend that performs a predefined sequence of actions.
    
    In a real implementation, you would:
    1. Send messages to your LLM API
    2. Parse the response to extract tool calls
    3. Return them as LLMResponse
    """
    
    def __init__(self):
        self.step = 0
        self.actions = [
            ToolCall(id="1", name="scroll", arguments={"direction": "down", "amount": 300}),
            ToolCall(id="2", name="scroll", arguments={"direction": "down", "amount": 300}),
            ToolCall(id="3", name="done", arguments={"message": "Demo completed - scrolled the page twice"}),
        ]
    
    async def generate(self, messages, tools):
        """Generate the next action in the sequence."""
        if self.step >= len(self.actions):
            return LLMResponse(
                tool_calls=[ToolCall(
                    id="done",
                    name="done", 
                    arguments={"message": "All demo actions completed"}
                )]
            )
        
        action = self.actions[self.step]
        self.step += 1
        return LLMResponse(tool_calls=[action])


async def main():
    print("=== Browser Agent Demo ===\n")
    
    # Configure the agent
    config = AgentConfig(
        max_steps=10,
        verbose=True,
        browser_config=BrowserConfig(headless=False),
    )
    
    # Use our demo backend (replace with real LLM in production)
    backend = SimpleDemoBackend()
    
    # Create and run the agent
    agent = Agent(backend, config=config)
    
    print("Running agent with task: 'Explore the page'\n")
    history = await agent.run(
        task="Explore the page",
        start_url="https://example.com"
    )
    
    # Print results
    print("\n=== Agent Results ===")
    print(f"Task: {history.task}")
    print(f"Completed: {history.is_complete}")
    print(f"Final result: {history.final_result}")
    print(f"Total steps: {len(history.steps)}")
    print(f"Duration: {history.total_duration_ms:.0f}ms")
    print(f"Success rate: {history.success_rate():.0%}")
    
    print("\n=== Step History ===")
    for step in history.steps:
        status = "✓" if step.result and step.result.success else "✗"
        print(f"  {status} Step {step.step_number}: {step.action_type}")


if __name__ == "__main__":
    asyncio.run(main())
