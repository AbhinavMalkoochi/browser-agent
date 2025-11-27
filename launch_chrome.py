#!/usr/bin/env python3
"""
Script to launch Chrome with CDP debugging enabled.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time


def launch_chrome(*, headless: bool = False, remote_debugging_port: int = 9222) -> bool:
    """
    Launch Chrome with remote debugging enabled.

    Args:
        headless: When True, launch Chrome without a visible window.
        remote_debugging_port: CDP port to expose.

    Returns:
        True if Chrome starts successfully, False otherwise.
    """
    
    # Common Chrome/Chromium executable paths
    chrome_paths = [
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser", 
        "/usr/bin/chromium",
        "/snap/bin/chromium",
        "/opt/google/chrome/chrome",
        "google-chrome",  # if in PATH
        "chromium-browser",  # if in PATH
    ]
    
    chrome_executable = None
    for path in chrome_paths:
        if os.path.exists(path) or subprocess.run(["which", path], capture_output=True).returncode == 0:
            chrome_executable = path
            break
    
    if not chrome_executable:
        print("❌ Chrome/Chromium not found. Please install Chrome or Chromium:")
        print("   sudo apt install chromium-browser")
        print("   # or")
        print("   sudo apt install google-chrome-stable")
        return False
    
    # Chrome flags for CDP debugging
    chrome_args = [
        chrome_executable,
        f"--remote-debugging-port={remote_debugging_port}",
        "--no-first-run",                # Skip first-run setup
        "--no-default-browser-check",    # Don't check if Chrome is default
        "--disable-extensions",          # Disable extensions for cleaner testing
        "--disable-background-timer-throttling",  # Keep timers running
        "--disable-renderer-backgrounding",       # Keep renderers active
        "--disable-backgrounding-occluded-windows",  # Keep windows active
        "--user-data-dir=/tmp/chrome-cdp-data",  # Separate profile
        "--window-size=1280,720",        # Set window size
        "about:blank"                    # Start with blank page
    ]

    if headless:
        chrome_args.extend(
            [
                "--headless=new",
                "--disable-gpu",
            ]
        )
        mode_description = "headless"
    else:
        mode_description = "visible"
    
    print(f"🚀 Launching Chrome: {chrome_executable}")
    print(f"   Remote debugging will be available on http://localhost:{remote_debugging_port}")
    print(f"   Mode: {mode_description}")
    print("   Press Ctrl+C to stop Chrome")
    print()
    
    try:
        # Launch Chrome
        process = subprocess.Popen(
            chrome_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        
        # Give Chrome time to start
        time.sleep(2)
        
        # Check if Chrome is still running
        if process.poll() is not None:
            print("❌ Chrome failed to start")
            return False
            
        print("✅ Chrome started successfully!")
        print("   You can now run your CDP scripts")
        print("   Chrome will stay open until you press Ctrl+C")
        print()
        
        # Keep the script running
        try:
            process.wait()
        except KeyboardInterrupt:
            print("\n🛑 Stopping Chrome...")
            process.terminate()
            process.wait()
            print("✅ Chrome stopped")
            
        return True
        
    except Exception as e:
        print(f"❌ Error launching Chrome: {e}")
        return False


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch Chrome with CDP debugging enabled.")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chrome without a visible window (default: visible window).",
    )
    parser.add_argument(
        "--remote-debugging-port",
        type=int,
        default=9222,
        help="Port to expose for the DevTools protocol (default: 9222).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> bool:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    return launch_chrome(
        headless=args.headless,
        remote_debugging_port=args.remote_debugging_port,
    )


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
