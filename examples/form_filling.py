#!/usr/bin/env python3
"""
Form Filling Example

Demonstrates how to fill out forms: finding inputs, typing text,
selecting dropdowns, and submitting.

Prerequisites:
- Chrome must be running with debugging enabled:
  python -m browser_agent.launch_chrome
"""
import asyncio

from browser_agent import Browser


async def main():
    async with Browser() as browser:
        # Navigate to a form page (using httpbin for demo)
        print("Navigating to form page...")
        await browser.navigate("https://httpbin.org/forms/post")
        
        # Get page state to see available elements
        state = await browser.get_state(include_screenshot=False)
        print(f"\nPage: {state.title}")
        print(f"Elements: {state.element_count}")
        print("\nActionable elements:")
        print(state.dom_text)
        
        # Find and fill form fields by looking at the state
        # In a real scenario, you'd parse the dom_text to find indices
        print("\n--- Form Filling Demo ---")
        print("(In practice, you'd use the element indices from dom_text)")
        
        # Example of how you'd interact:
        # await browser.type(1, "John Doe")  # Name field
        # await browser.type(2, "john@example.com")  # Email field
        # await browser.select(3, "medium", by="value")  # Size dropdown
        # await browser.click(4)  # Submit button
        
        # Press Enter to submit (alternative to clicking submit)
        print("\nDemo: Pressing Enter key...")
        result = await browser.press_key("Enter")
        print(f"Key press: {result.to_message()}")
        
        # Demo keyboard shortcuts
        print("\nDemo: Pressing Ctrl+A (select all)...")
        result = await browser.press_key("a", modifiers=["ctrl"])
        print(f"Key press: {result.to_message()}")


if __name__ == "__main__":
    asyncio.run(main())
