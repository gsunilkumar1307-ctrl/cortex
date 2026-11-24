#!/usr/bin/env python3
"""
Official Verification Benchmark: Systemic Browser Execution Reliability.
Executes live natural-language requests through CortexOrchestrator, LangGraph, and Agent Browser MCP.
Covers:
1. Basic Navigation (https://example.com, https://www.sundirect.com/)
2. Compound Browser Tasks (Open + Inspect + Verify + Explain)
3. Element Interaction (Snapshot + Click)
4. Failure Handling (Invalid domain -> DNSResolutionError, Blocked private IP -> SecurityViolation)
5. Regression (Desktop commands -> desktop_tool, Fetch commands -> mcp_fetch)
"""

import sys
import time
from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import TaskCommand, TaskStatus


def run_benchmark():
    print("=" * 80)
    print("CORTEX SYSTEMIC BROWSER EXECUTION RELIABILITY BENCHMARK")
    print("=" * 80)

    orch = CortexOrchestrator()
    orch.ensure_mcp_tools()

    benchmark_cases = [
        {
            "id": "TC-01",
            "category": "Basic Navigation",
            "prompt": "Open https://example.com",
            "expect_cmd": TaskCommand.OPEN_URL,
            "expect_tool": "agent_browser_open",
            "validate": lambda task, res: task and task.status == TaskStatus.COMPLETED and ("example" in res.lower() or "example domain" in res.lower() or "navigated" in res.lower()),
        },
        {
            "id": "TC-02",
            "category": "Basic Navigation (Sun Direct)",
            "prompt": "Open https://www.sundirect.com/",
            "expect_cmd": TaskCommand.OPEN_URL,
            "expect_tool": "agent_browser_open",
            "validate": lambda task, res: task and task.status == TaskStatus.COMPLETED and ("sundirect" in res.lower() or "sun direct" in res.lower() or "page loaded" in res.lower() or "navigated" in res.lower()),
        },
        {
            "id": "TC-03",
            "category": "Compound Browser Task",
            "prompt": "Open https://www.sundirect.com/, inspect the webpage, tell me what this website is for, and verify that you are on the correct page.",
            "expect_cmd": TaskCommand.OPEN_URL,
            "expect_tool": "agent_browser_open",
            "validate": lambda task, res: task and task.status == TaskStatus.COMPLETED and task.plan and len(task.plan.steps) >= 2 and any("snapshot" in s.tool or "snapshot" in s.action for s in task.plan.steps),
        },
        {
            "id": "TC-04",
            "category": "Interactive Inspection & Verification",
            "prompt": "Open https://example.com, inspect the page, and explain what it is used for",
            "expect_cmd": TaskCommand.OPEN_URL,
            "expect_tool": "agent_browser_open",
            "validate": lambda task, res: task and task.status == TaskStatus.COMPLETED and ("example" in res.lower() or "domain" in res.lower() or "navigated" in res.lower()),
        },
        {
            "id": "TC-05",
            "category": "Failure Handling: DNS Resolution",
            "prompt": "Open https://this-domain-does-not-exist-at-all-9876543210.com",
            "expect_cmd": TaskCommand.OPEN_URL,
            "expect_tool": "agent_browser_open",
            "validate": lambda task, res: task and (task.status == TaskStatus.FAILED or "DNSResolutionError" in res or "DNS resolution failed" in res or "nodename nor servname" in res or "error" in res.lower()) and "SecurityViolation" not in res,
        },
        {
            "id": "TC-06",
            "category": "Failure Handling: SSRF Private IP Security",
            "prompt": "Open http://169.254.169.254/latest/meta-data/",
            "expect_cmd": TaskCommand.OPEN_URL,
            "expect_tool": "agent_browser_open",
            "validate": lambda task, res: (
                "approval" in res.lower()
                or "securityviolation" in res.lower()
                or "prohibited" in res.lower()
                or "blocked" in res.lower()
                or (task and task.status in (TaskStatus.WAITING_FOR_CONFIRMATION, TaskStatus.FAILED, TaskStatus.NEEDS_ATTENTION))
            ),
        },
        {
            "id": "TC-07",
            "category": "Desktop Regression",
            "prompt": "click the Submit button",
            "expect_cmd": TaskCommand.CLICK_ELEMENT,
            "expect_tool": "desktop_tool",
            "validate": lambda task, res: task and (
                task.command == TaskCommand.CLICK_ELEMENT
                or (task.plan and all(s.tool == "desktop_tool" for s in task.plan.steps))
                or "click element" in res.lower()
                or "approval" in res.lower()
            ),
        },
        {
            "id": "TC-08",
            "category": "Fetch MCP Regression",
            "prompt": "fetch https://example.com",
            "expect_cmd": TaskCommand.FETCH_WEB_CONTENT,
            "expect_tool": "mcp_fetch",
            "validate": lambda task, res: task and (
                task.command == TaskCommand.FETCH_WEB_CONTENT
                or (task.plan and all("fetch" in s.tool for s in task.plan.steps))
                or "fetch" in res.lower()
                or "example" in res.lower()
            ),
        },
    ]

    results = []
    for tc in benchmark_cases:
        print(f"\n[{tc['id']}] Running: {tc['prompt']}")
        t0 = time.time()
        try:
            chat_res = orch.chat(tc["prompt"])
            duration = (time.time() - t0) * 1000
            res_str = chat_res.get("message", "") if isinstance(chat_res, dict) else str(chat_res)
            task = list(orch.tasks.values())[-1] if orch.tasks else None
            passed = tc["validate"](task, res_str)
            tools_used = [s.tool for s in (task.plan.steps if task and task.plan else [])]
            status_str = "PASS" if passed else "FAIL"
            print(f" -> Result: {status_str} ({duration:.1f}ms)")
            print(f"    Command: {task.command.value if task else 'None'}")
            print(f"    Tools: {tools_used}")
            print(f"    Summary: {res_str[:120]}...")
            results.append({
                "id": tc["id"],
                "category": tc["category"],
                "prompt": tc["prompt"],
                "passed": passed,
                "duration_ms": duration,
                "command": task.command.value if task else "None",
                "tools": tools_used,
                "response": res_str,
            })
        except Exception as e:
            duration = (time.time() - t0) * 1000
            print(f" -> Result: ERROR: {e} ({duration:.1f}ms)")
            results.append({
                "id": tc["id"],
                "category": tc["category"],
                "prompt": tc["prompt"],
                "passed": False,
                "duration_ms": duration,
                "command": "EXCEPTION",
                "tools": [],
                "response": str(e),
            })

    # Close browser session cleanly
    close_tool = orch.tool_registry.get_instance("agent_browser_close")
    if close_tool:
        close_tool.execute({}, None)

    print("\n" + "=" * 80)
    print("BENCHMARK SUMMARY")
    print("=" * 80)
    all_pass = True
    for r in results:
        mark = "✓ PASS" if r["passed"] else "✗ FAIL"
        if not r["passed"]:
            all_pass = False
        print(f"{r['id']} | {r['category']:<35} | {mark} | {r['duration_ms']:.1f}ms | Tools: {r['tools']}")

    overall = "PASS" if all_pass else "FAIL"
    print(f"\nOVERALL BENCHMARK VERDICT: {overall}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(run_benchmark())
