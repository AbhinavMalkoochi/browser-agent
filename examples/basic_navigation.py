#!/usr/bin/env python3
"""
Basic Navigation Example

Demonstrates basic browser automation: navigating, getting state,
clicking elements, and typing text.

Prerequisites:
- Chrome must be running with debugging enabled:
  python -m browser_agent.launch_chrome
"""
import asyncio

from browser_agent import Browser, BrowserConfig


async def main():
    # Configure browser (optional - defaults work fine)
    config = BrowserConfig(
        headless=False,
        viewport_width=1280,
        viewport_height=720,
    )
    
    async with Browser(config) as browser:
        # Navigate to a page
        print("Navigating to example.com...")
        result = await browser.navigate("https://example.com")
        print(f"Navigation: {result.to_message()}")
        
        # Get page state
        print("\nGetting page state...")
        state = await browser.get_state()
        
        print(f"URL: {state.url}")
        print(f"Title: {state.title}")
        print(f"Elements found: {state.element_count}")
        print(f"\nActionable elements:")
        print(state.dom_text)
        
        # Take a screenshot
        print("\nTaking screenshot...")
        screenshot = await browser.screenshot()
        print(f"Screenshot captured: {len(screenshot)} bytes (base64)")
        
        # Scroll down
        print("\nScrolling down...")
        result = await browser.scroll(direction="down", amount=300)
        print(f"Scroll: {result.to_message()}")
        
        # Navigate to another page
        print("\nNavigating to Wikipedia...")
        await browser.navigate("https://en.wikipedia.org")
        state = await browser.get_state()
        print(f"Now at: {state.url}")
        print(f"Elements: {state.element_count}")
        
        # Go back
        print("\nGoing back...")
        result = await browser.go_back()
        print(f"Go back: {result.to_message()}")
        
        url = await browser.get_url()
        print(f"Now at: {url}")


if __name__ == "__main__":
    asyncio.run(main())
