#!/usr/bin/env python3
"""
Agent with OpenAI Backend

Demonstrates using the Agent class with a real OpenAI backend.

Prerequisites:
- Chrome must be running with debugging enabled:
  python -m browser_agent.launch_chrome
- Set OPENAI_API_KEY environment variable
- Install openai: pip install browser-agent[openai]

Usage:
    export OPENAI_API_KEY="sk-..."
    python examples/agent_with_openai.py
"""
import asyncio
import os
import sys

from browser_agent import Agent, AgentConfig, BrowserConfig, OpenAIBackend


async def main():
    # Check for API key
    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set")
        print("Usage: export OPENAI_API_KEY='sk-...'")
        sys.exit(1)
    
    print("=== Browser Agent with OpenAI ===\n")
    
    # Create the OpenAI backend
    backend = OpenAIBackend(
        model="gpt-4o-mini",  # Use gpt-4o for better results
        temperature=0.0,
    )
    
    # Configure the agent
    config = AgentConfig(
        max_steps=15,
        max_failures=3,
        verbose=True,
        browser_config=BrowserConfig(
            headless=False,
            viewport_width=1280,
            viewport_height=720,
        ),
    )
    
    # Create and run the agent
    agent = Agent(backend, config=config)
    
    task = "Go to example.com and tell me what the page is about"
    print(f"Task: {task}\n")
    
    history = await agent.run(
        task=task,
        start_url="https://example.com"
    )
    
    # Print results
    print("\n=== Results ===")
    print(f"Completed: {history.is_complete}")
    print(f"Final result: {history.final_result}")
    print(f"Total steps: {len(history.steps)}")
    print(f"Duration: {history.total_duration_ms:.0f}ms")
    print(f"Success rate: {history.success_rate():.0%}")
    
    if history.errors():
        print(f"\nErrors encountered:")
        for error in history.errors():
            print(f"  - {error}")


if __name__ == "__main__":
    asyncio.run(main())
