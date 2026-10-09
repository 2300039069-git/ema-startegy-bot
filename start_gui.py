#!/usr/bin/env python3
"""
================================================================================
                    KDK TRADE BOT - WEB BROWSER LAUNCHER
================================================================================
Launches the local web server and automatically opens the interactive
trading dashboard in your default browser.
"""

import sys
import time
import threading
import webbrowser
import uvicorn

# Ensure UTF-8 output on Windows terminal
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def open_browser():
    """Waits for the server to start, then automatically opens the browser."""
    time.sleep(1.5)
    url = "http://127.0.0.1:8000"
    print(f"\n[+] Opening KDK Trade Bot Dashboard in browser: {url}\n", flush=True)
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"[-] Could not open browser automatically: {e}", flush=True)


def main():
    print("""
================================================================================
  _  ______  _  __  _____              _         ____        _   
 | |/ /  _ \| |/ / |_   _| __ __ _  __| | ___   | __ )  ___ | |_ 
 | ' /| | | | ' /    | || '__/ _` |/ _` |/ _ \  |  _ \ / _ \| __|
 | . \| |_| | . \    | || | | (_| | (_| |  __/  | |_) | (_) | |_ 
 |_|\_\____/|_|\_\   |_||_|  \__,_|\__,_|\___|  |____/ \___/ \__|
                                                                 
             Interactive Web GUI Dashboard & Trading Engine
================================================================================
    """)
    print("[*] Starting Web Server on http://127.0.0.1:8000 ...", flush=True)

    # Launch browser opener in background thread
    threading.Thread(target=open_browser, daemon=True).start()

    # Run Uvicorn server
    uvicorn.run("app:app", host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
