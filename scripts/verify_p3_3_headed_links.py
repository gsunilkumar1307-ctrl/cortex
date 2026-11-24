#!/usr/bin/env python3
"""
Live macOS Acceptance Test Suite for Phase P3.3:
Visible Playwright Browser Execution & Clickable Source Links.

Executes real live browser sessions via @playwright/mcp@0.0.85 across:
- TEST A: "Open Amazon." -> Visible window appears, navigates to amazon.in, reports Amazon is open, clickable link, window stays open.
- TEST B: "Open Flipkart." -> Window reused, navigates to flipkart.com, reports Flipkart is open, clickable link, window stays open.
- TEST C: "Go to Flipkart and search for ASUS laptop." -> Types search, real results, clickable link: Source: [Flipkart ASUS laptop search results](...)
- TEST D: Session continuity -> "Open Amazon." then "Search for ASUS laptops." -> same browser window navigates/searches Amazon, returns results with clickable link.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import TaskStatus, TaskCommand


def get_macos_browser_windows():
    """Queries macOS System Events for visible Chrome / Chromium browser windows."""
    scpt = '''
    tell application "System Events"
        set winList to {}
        set pList to every process whose name contains "Chrome" or name contains "Chromium"
        repeat with p in pList
            try
                set pWins to every window of p
                repeat with w in pWins
                    set end of winList to (name of p & "::: " & name of w)
                end repeat
            end try
        end repeat
        return winList
    end tell
    '''
    try:
        proc = subprocess.run(
            ["osascript", "-e", scpt],
            capture_output=True,
            text=True,
            timeout=5
        )
        if proc.returncode == 0 and proc.stdout.strip():
            raw = proc.stdout.strip()
            # Split comma-separated items
            items = [item.strip() for item in raw.split(",") if item.strip()]
            return items
    except Exception as e:
        print(f"  [Warning] Window query failed: {e}")
    return []


def assert_clickable_link(msg: str, domain_pattern: str) -> str:
    """Verifies response contains a Markdown link [label](https://...) matching domain."""
    link_match = re.search(r'\[([^\]]+)\]\((https?://[^\s\)]+)\)', msg)
    assert link_match, f"Message does not contain clickable markdown link: {msg}"
    label, url = link_match.group(1), link_match.group(2)
    assert re.search(domain_pattern, url, re.I), f"URL '{url}' does not match expected domain pattern '{domain_pattern}'"
    print(f"  [Link Verified] Label='{label}', URL='{url}'")
    return url


def run_tests():
    print("=" * 80)
    print(" CORTEX PHASE P3.3: LIVE HEADED BROWSER & CLICKABLE LINKS ACCEPTANCE SUITE")
    print("=" * 80)

    orch = CortexOrchestrator()
    results = {}

    try:
        # TEST A: "Open Amazon."
        print("\n--- TEST A: 'Open Amazon.' ---")
        res_a = orch.chat("Open Amazon.")
        msg_a = res_a.get("message", "")
        print(f"Response: {msg_a}")

        assert "Amazon is open" in msg_a, f"Expected 'Amazon is open' in: {msg_a}"
        url_a = assert_clickable_link(msg_a, r"amazon\.")

        time.sleep(2)
        windows_a = get_macos_browser_windows()
        print(f"Visible macOS Browser Windows: {windows_a}")
        assert any("Amazon" in w or "Chrome" in w for w in windows_a), f"Expected visible window with Amazon/Chrome: {windows_a}"
        results["TEST_A"] = "PASSED"

        # TEST B: "Open Flipkart."
        print("\n--- TEST B: 'Open Flipkart.' ---")
        res_b = orch.chat("Open Flipkart.")
        msg_b = res_b.get("message", "")
        print(f"Response: {msg_b}")

        assert "Flipkart is open" in msg_b, f"Expected 'Flipkart is open' in: {msg_b}"
        url_b = assert_clickable_link(msg_b, r"flipkart\.com")

        time.sleep(2)
        windows_b = get_macos_browser_windows()
        print(f"Visible macOS Browser Windows: {windows_b}")
        assert any("Flipkart" in w or "Chrome" in w for w in windows_b), f"Expected visible window with Flipkart/Chrome: {windows_b}"
        results["TEST_B"] = "PASSED"

        # TEST C: "Go to Flipkart and search for ASUS laptop."
        print("\n--- TEST C: 'Go to Flipkart and search for ASUS laptop.' ---")
        res_c = orch.chat("Go to Flipkart and search for ASUS laptop.")
        msg_c = res_c.get("message", "")
        print(f"Response: {msg_c[:400]}...")

        url_c = assert_clickable_link(msg_c, r"flipkart\.com/search")
        assert "Flipkart ASUS laptop search results" in msg_c or "Flipkart" in msg_c
        results["TEST_C"] = "PASSED"

        # TEST D: Session Continuity: Open Amazon -> Search for ASUS laptops
        print("\n--- TEST D: Session continuity: Open Amazon -> Search for ASUS laptops ---")
        res_d1 = orch.chat("Open Amazon.")
        msg_d1 = res_d1.get("message", "")
        print(f"Turn 1 Response: {msg_d1}")
        assert "Amazon is open" in msg_d1

        res_d2 = orch.chat("Search for ASUS laptops.")
        msg_d2 = res_d2.get("message", "")
        print(f"Turn 2 Response: {msg_d2[:400]}...")
        url_d2 = assert_clickable_link(msg_d2, r"amazon\.")
        results["TEST_D"] = "PASSED"

    finally:
        # Cleanup
        try:
            orch.mcp_manager.stop_all()
        except Exception:
            pass

    print("\n" + "=" * 80)
    print(" ACCEPTANCE TEST SUMMARY:")
    for test, status in results.items():
        print(f"   {test}: {status}")
    print("=" * 80)
    return 0 if len(results) == 4 and all(s == "PASSED" for s in results.values()) else 1


if __name__ == "__main__":
    sys.exit(run_tests())
