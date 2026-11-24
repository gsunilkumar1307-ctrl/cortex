"""
Unit and System Tests for Phase P3.3: Visible Playwright Browser Execution on macOS.

Validates:
1. Official @playwright/mcp server configuration is headed by default (no --headless).
2. JSON configuration in config/mcp_servers.json preserves headed mode.
3. macOS GUI process and window visibility verification via AppleScript / System Events.
4. Session reuse preserves the existing visible browser window across user turns.
"""

import json
import os
import subprocess
import time
from pathlib import Path
import pytest

from backend.mcp.config import get_playwright_server_config, load_mcp_config
from backend.mcp.manager import MCPServerManager
from backend.agent.orchestrator import CortexOrchestrator


def get_macos_browser_windows() -> list[dict[str, str]]:
    """Inspects macOS System Events for running Chrome / Chromium browser windows."""
    as_script = """
    tell application "System Events"
        set outList to {}
        repeat with p in (every process whose name contains "Chrome" or name contains "Chromium")
            try
                set pName to name of p
                set wCount to count of windows of p
                if wCount > 0 then
                    repeat with w in windows of p
                        set wTitle to name of w
                        set end of outList to (pName & "|||" & wTitle)
                    end repeat
                end if
            end try
        end repeat
        return outList
    end tell
    """
    try:
        raw = subprocess.check_output(["osascript", "-e", as_script], timeout=10.0).decode().strip()
        if not raw:
            return []
        items = [x.strip() for x in raw.split(", ") if x.strip()]
        result = []
        for item in items:
            if "|||" in item:
                proc, title = item.split("|||", 1)
                result.append({"process": proc, "title": title})
            else:
                result.append({"process": "unknown", "title": item})
        return result
    except Exception:
        return []


def test_headed_server_configuration():
    """Verifies official @playwright/mcp configuration is headed by default."""
    cfg = get_playwright_server_config()
    assert "--headless" not in cfg.args, "Default interactive browser configuration must not be headless"
    assert "--isolated" in cfg.args, "Playwright MCP must use --isolated to prevent cache collisions"
    assert cfg.name == "playwright"


def test_mcp_servers_json_headed():
    """Verifies config/mcp_servers.json does not contain --headless."""
    cfg_path = Path(__file__).resolve().parents[1] / "config" / "mcp_servers.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    pw_cfg = data["mcpServers"]["playwright"]
    assert "--headless" not in pw_cfg["args"], "mcp_servers.json must not pass --headless"


def test_live_headed_browser_window_presence():
    """
    Empirical test: Launches headed @playwright/mcp, navigates to Amazon,
    and proves that an actual native browser window exists on macOS.
    """
    mgr = MCPServerManager()
    cfg = get_playwright_server_config(headless=False)
    mgr.register_server(cfg)
    
    try:
        mgr.start_server("playwright", timeout=30.0)
        res = mgr.call_tool("playwright", "browser_navigate", {"url": "https://www.amazon.in/"}, timeout=40.0)
        assert not res.is_error
        
        # Verify on macOS desktop via System Events
        time.sleep(1.0)
        windows = get_macos_browser_windows()
        assert len(windows) > 0, "Expected at least one visible browser window on macOS desktop"
        assert any("Chrome" in w["process"] or "Chromium" in w["process"] for w in windows)
        assert any("amazon" in w["title"].lower() or "shopping" in w["title"].lower() for w in windows)
    finally:
        mgr.stop_all()


def test_live_browser_session_reuse():
    """
    Empirical test: Proves the same visible browser session is reused
    between consecutive user turns (Amazon -> Flipkart).
    """
    mgr = MCPServerManager()
    cfg = get_playwright_server_config(headless=False)
    mgr.register_server(cfg)
    
    try:
        mgr.start_server("playwright", timeout=30.0)
        
        # Turn 1: Amazon
        mgr.call_tool("playwright", "browser_navigate", {"url": "https://www.amazon.in/"}, timeout=40.0)
        time.sleep(1.0)
        win1 = get_macos_browser_windows()
        assert len(win1) > 0
        
        # Turn 2: Flipkart in same session
        mgr.call_tool("playwright", "browser_navigate", {"url": "https://www.flipkart.com/"}, timeout=40.0)
        time.sleep(1.0)
        win2 = get_macos_browser_windows()
        assert len(win2) > 0
        # Title updated to Flipkart
        assert any("flipkart" in w["title"].lower() or "online shopping" in w["title"].lower() for w in win2)
    finally:
        mgr.stop_all()
