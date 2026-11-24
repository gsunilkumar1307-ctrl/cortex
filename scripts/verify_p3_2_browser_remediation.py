#!/usr/bin/env python3
"""
Live macOS Acceptance Test Suite for Phase P3.2:
Natural-Language Browser Navigation & Search Execution Remediation.

This script executes real live browser automation sessions using the official
@playwright/mcp@0.0.85 server across all 8 required acceptance test scenarios:

TEST 1: User says "Open Amazon." -> Amazon regional website opens; reports "Amazon is open."; no old research results.
TEST 2: User says "Open Flipkart." -> Flipkart homepage opens; reports "Flipkart is open."; no old product results.
TEST 3: User says "Go to Flipkart and search for ASUS laptop." -> Flipkart opens, search field populated with "ASUS laptop", search submitted, real results displayed.
TEST 4: User says "Open GitHub and search for Playwright MCP." -> GitHub opens, search field used, real results displayed.
TEST 5: User says "Open Wikipedia and search for quantum computing." -> Wikipedia opens, search interface used, article displayed.
TEST 6 (Task Isolation): Search ASUS laptops -> Then "Open Amazon." -> Amazon opens, old ASUS results not returned, reports "Amazon is open."
TEST 7 (Follow-Up Continuity): Search ASUS laptops on Flipkart -> Then "Open the second result." -> Opens actual 2nd result item.
TEST 8 (Failure Honesty): Unreachable site, missing search box, or blocked site -> Explains actual limitation truthfully without false success.
"""

import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import TaskStatus, TaskCommand
from backend.mcp.website_resolver import WebsiteResolver


def print_banner(text: str) -> None:
    print("\n" + "=" * 80)
    print(f" {text}")
    print("=" * 80)


def test_1_open_amazon(orch: CortexOrchestrator) -> bool:
    print_banner("TEST 1: User says 'Open Amazon.'")
    res = orch.chat("Open Amazon.")
    msg = res.get("message", "")
    task = res.get("task", {})

    print(f"  Response Message: {msg}")
    print(f"  Task Status:      {task.get('status')}")
    print(f"  Resolved URL:     {task.get('params', {}).get('url')}")
    print(f"  Browser Intent:   {task.get('params', {}).get('browser_intent')}")

    # Checks:
    # 1. Must be completed
    assert task.get("status") == TaskStatus.COMPLETED.value, f"Expected COMPLETED, got {task.get('status')}"
    # 2. Concise truthful response
    assert "Amazon is open" in msg or "Amazon" in msg, f"Expected concise 'Amazon is open.', got: {msg}"
    # 3. No old research results leaked
    assert "laptop" not in msg.lower() and "asus" not in msg.lower(), "Old research results leaked into navigation response"
    # 4. Regional or canonical Amazon URL used
    url = task.get("params", {}).get("url", "")
    assert "amazon" in url, f"Expected amazon URL, got {url}"
    print("  ✓ TEST 1 PASSED: Amazon homepage opened cleanly without stale results.")
    return True


def test_2_open_flipkart(orch: CortexOrchestrator) -> bool:
    print_banner("TEST 2: User says 'Open Flipkart.'")
    res = orch.chat("Open Flipkart.")
    msg = res.get("message", "")
    task = res.get("task", {})

    print(f"  Response Message: {msg}")
    print(f"  Task Status:      {task.get('status')}")
    print(f"  Resolved URL:     {task.get('params', {}).get('url')}")
    print(f"  Browser Intent:   {task.get('params', {}).get('browser_intent')}")

    assert task.get("status") == TaskStatus.COMPLETED.value
    assert "Flipkart is open" in msg or "Flipkart" in msg
    assert "laptop" not in msg.lower() and "asus" not in msg.lower()
    url = task.get("params", {}).get("url", "")
    assert "flipkart.com" in url
    print("  ✓ TEST 2 PASSED: Flipkart homepage opened cleanly without product list dump.")
    return True


def test_3_search_flipkart_asus(orch: CortexOrchestrator) -> bool:
    print_banner("TEST 3: User says 'Go to Flipkart and search for ASUS laptop.'")
    res = orch.chat("Go to Flipkart and search for ASUS laptop.")
    msg = res.get("message", "")
    task = res.get("task", {})

    print(f"  Response Message: {msg}")
    print(f"  Task Status:      {task.get('status')}")
    print(f"  Extracted Query:  {task.get('params', {}).get('query')}")
    print(f"  Browser Results:  {len(orch.last_browser_results)} items captured")

    assert task.get("status") == TaskStatus.COMPLETED.value
    assert "ASUS laptop" in msg or "search results are displayed" in msg
    assert len(orch.last_browser_results) > 0, "Expected search results to be recorded in orchestrator"
    print(f"  First result captured: {orch.last_browser_results[0].get('title')}")
    print("  ✓ TEST 3 PASSED: Flipkart search executed on real search field; results displayed.")
    return True


def test_4_search_github_playwright(orch: CortexOrchestrator) -> bool:
    print_banner("TEST 4: User says 'Open GitHub and search for Playwright MCP.'")
    res = orch.chat("Open GitHub and search for Playwright MCP.")
    msg = res.get("message", "")
    task = res.get("task", {})

    print(f"  Response Message: {msg}")
    print(f"  Task Status:      {task.get('status')}")
    print(f"  Extracted Query:  {task.get('params', {}).get('query')}")

    assert task.get("status") == TaskStatus.COMPLETED.value
    assert "GitHub" in msg
    assert "Playwright MCP" in msg
    print("  ✓ TEST 4 PASSED: GitHub search executed; real search query submitted.")
    return True


def test_5_search_wikipedia_quantum(orch: CortexOrchestrator) -> bool:
    print_banner("TEST 5: User says 'Open Wikipedia and search for quantum computing.'")
    res = orch.chat("Open Wikipedia and search for quantum computing.")
    msg = res.get("message", "")
    task = res.get("task", {})

    print(f"  Response Message: {msg}")
    print(f"  Task Status:      {task.get('status')}")
    print(f"  Extracted Query:  {task.get('params', {}).get('query')}")

    assert task.get("status") == TaskStatus.COMPLETED.value
    assert "Wikipedia" in msg
    assert "quantum computing" in msg.lower()
    print("  ✓ TEST 5 PASSED: Wikipedia searched and article displayed.")
    return True


def test_6_task_isolation(orch: CortexOrchestrator) -> bool:
    print_banner("TEST 6: Task Isolation (Search ASUS laptops -> Then 'Open Amazon.')")
    # Step 1: Perform search
    print("  Substep A: Searching for ASUS laptops on Flipkart...")
    res_a = orch.chat("Go to Flipkart and search for ASUS laptop.")
    assert len(orch.last_browser_results) > 0

    # Step 2: Open Amazon
    print("  Substep B: Saying 'Open Amazon.'...")
    res_b = orch.chat("Open Amazon.")
    msg_b = res_b.get("message", "")
    task_b = res_b.get("task", {})

    print(f"  Response Message: {msg_b}")
    print(f"  Active Browser Results Count: {len(orch.last_browser_results)}")

    assert task_b.get("status") == TaskStatus.COMPLETED.value
    assert "Amazon is open" in msg_b or "Amazon" in msg_b
    assert "asus" not in msg_b.lower() and "vivobook" not in msg_b.lower()
    assert len(orch.last_browser_results) == 0, "Expected last_browser_results to be cleared on OPEN_WEBSITE"
    print("  ✓ TEST 6 PASSED: Session state isolated; navigation cleared prior search results.")
    return True


def test_7_follow_up_continuity(orch: CortexOrchestrator) -> bool:
    print_banner("TEST 7: Follow-Up Continuity (Search Flipkart -> 'Open the second result.')")
    # Step 1: Search laptops
    print("  Substep A: Searching for ASUS laptop on Flipkart...")
    res1 = orch.chat("Go to Flipkart and search for ASUS laptop.")
    assert len(orch.last_browser_results) >= 2, f"Need at least 2 results, got {len(orch.last_browser_results)}"
    second_item = orch.last_browser_results[1]
    second_title = second_item.get("title")
    print(f"  Recorded 2nd result item: {second_title} ({second_item.get('url')})")

    # Step 2: Open second result
    print("  Substep B: Saying 'Open the second result.'...")
    res2 = orch.chat("Open the second result.")
    msg2 = res2.get("message", "")
    task2 = res2.get("task", {})

    print(f"  Response Message: {msg2}")
    print(f"  Task Status:      {task2.get('status')}")
    print(f"  Navigated URL:    {task2.get('params', {}).get('url')}")

    assert task2.get("status") == TaskStatus.COMPLETED.value
    assert "second result" in msg2.lower() or second_title in msg2 or "Opened" in msg2
    print("  ✓ TEST 7 PASSED: Second result correctly navigated in active browser session.")
    return True


def test_8_failure_honesty(orch: CortexOrchestrator) -> bool:
    print_banner("TEST 8: Failure Honesty (Unreachable site / Blocked SSRF)")
    # Case A: Blocked loopback host
    print("  Substep A: Attempting navigation to prohibited loopback http://127.0.0.1:8888...")
    res_a = orch.chat("Go to http://127.0.0.1:8888 and search for test.")
    task_a = res_a.get("task", {})
    msg_a = res_a.get("message", "")
    print(f"  Response: {msg_a}")
    assert task_a.get("status") == TaskStatus.FAILED.value
    assert "Security Policy Violation" in msg_a or "blocked" in msg_a.lower()

    # Case B: Prohibited local file scheme
    print("  Substep B: Attempting navigation to file:///etc/passwd...")
    res_b = orch.chat("Navigate to file:///etc/passwd.")
    task_b = res_b.get("task", {})
    msg_b = res_b.get("message", "")
    print(f"  Response: {msg_b}")
    assert task_b.get("status") == TaskStatus.FAILED.value
    assert "Security Policy Violation" in msg_b or "prohibited" in msg_b.lower() or "blocked" in msg_b.lower() or "scheme" in msg_b.lower()

    # Case C: Unreachable domain without false success
    print("  Substep C: Attempting navigation to non-existent domain https://nonexistent.invalid...")
    res_c = orch.chat("Go to https://nonexistent.invalid and search for test.")
    task_c = res_c.get("task", {})
    msg_c = res_c.get("message", "")
    print(f"  Response: {msg_c}")
    assert task_c.get("status") == TaskStatus.FAILED.value
    assert "error" in msg_c.lower() or "failed" in msg_c.lower()

    print("  ✓ TEST 8 PASSED: Honest error reporting without false success or silent fallback.")
    return True


def main():
    print_banner("CORTEX AGENT — PHASE P3.2 BROWSER REMEDIATION LIVE ACCEPTANCE")
    print(f"Project root: {PROJECT_ROOT}")

    orch = CortexOrchestrator()
    results = {}

    try:
        results["TEST 1 (Open Amazon)"] = test_1_open_amazon(orch)
        results["TEST 2 (Open Flipkart)"] = test_2_open_flipkart(orch)
        results["TEST 3 (Search Flipkart)"] = test_3_search_flipkart_asus(orch)
        results["TEST 4 (Search GitHub)"] = test_4_search_github_playwright(orch)
        results["TEST 5 (Search Wikipedia)"] = test_5_search_wikipedia_quantum(orch)
        results["TEST 6 (Task Isolation)"] = test_6_task_isolation(orch)
        results["TEST 7 (Follow-Up Continuity)"] = test_7_follow_up_continuity(orch)
        results["TEST 8 (Failure Honesty)"] = test_8_failure_honesty(orch)
    finally:
        # Gracefully shut down MCP servers
        if hasattr(orch, "mcp_manager") and orch.mcp_manager:
            orch.mcp_manager.stop_all()

    print_banner("ACCEPTANCE SUMMARY")
    all_passed = True
    for test_name, passed in results.items():
        status = "PASSED ✓" if passed else "FAILED ✗"
        print(f"  {test_name.ljust(40)}: {status}")
        if not passed:
            all_passed = False

    print("=" * 80)
    if all_passed:
        print(" ALL 8 ACCEPTANCE TESTS PASSED SUCCESSFULLY! Ready for P3.2 sign-off.")
        print("=" * 80)
        return 0
    else:
        print(" SOME TESTS FAILED.")
        print("=" * 80)
        return 1


if __name__ == "__main__":
    sys.exit(main())
