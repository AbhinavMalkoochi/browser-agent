#!/usr/bin/env python3
"""
Script to launch Chrome with CDP debugging enabled
"""
import subprocess
import time
import sys
import os

def launch_chrome():
    """Launch Chrome with remote debugging on port 9222"""
    
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
        "--remote-debugging-port=9222",  # Enable CDP on port 9222
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
    
    print(f"🚀 Launching Chrome: {chrome_executable}")
    print("   Remote debugging will be available on http://localhost:9222")
    print("   Press Ctrl+C to stop Chrome")
    print()
    
    try:
        # Launch Chrome
        process = subprocess.Popen(chrome_args, 
                                 stdout=subprocess.DEVNULL, 
                                 stderr=subprocess.DEVNULL)
        
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

if __name__ == "__main__":
    launch_chrome()
