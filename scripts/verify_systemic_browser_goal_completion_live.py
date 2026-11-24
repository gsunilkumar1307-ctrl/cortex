import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import TaskStatus, TaskCommand

def run_benchmark():
    print("=" * 80)
    print("CORTEX SYSTEMIC BROWSER GOAL COMPLETION BENCHMARK (LIVE)")
    print("=" * 80)

    orch = CortexOrchestrator()
    results = {}

    cases = [
        {
            "id": "TC-01",
            "name": "Website explanation",
            "prompt": "Open TradingView and explain what it does.",
            "validator": lambda task, msg: (
                task.status == TaskStatus.COMPLETED
                and "tradingview.com" in msg.lower()
                and ("charting" in msg.lower() or "trading" in msg.lower() or "market" in msg.lower() or "platform" in msg.lower())
                and "validationerror" not in msg.lower()
                and "securityviolation" not in msg.lower()
            )
        },
        {
            "id": "TC-02",
            "name": "Repository search",
            "prompt": "Open GitHub and find the LangGraph repository.",
            "validator": lambda task, msg: (
                task.status == TaskStatus.COMPLETED
                and "github.com" in msg.lower()
                and "langgraph" in msg.lower()
                and "search" in msg.lower()
                and not msg.strip().endswith("via Agent Browser (Title: 'GitHub: Let’s build from here · GitHub').")
            )
        },
        {
            "id": "TC-03",
            "name": "Website feature summary",
            "prompt": "Visit a Claude website and summarize its main features.",
            "validator": lambda task, msg: (
                task.status == TaskStatus.COMPLETED
                and ("claude.ai" in msg.lower() or "anthropic.com" in msg.lower())
                and ("feature" in msg.lower() or "reasoning" in msg.lower() or "coding" in msg.lower() or "assistant" in msg.lower() or "ai" in msg.lower())
                and not msg.strip().startswith("Navigated to")
            )
        },
        {
            "id": "TC-04",
            "name": "Compound inspection and verification",
            "prompt": "Open a Claude page, inspect it, and verify its URL.",
            "validator": lambda task, msg: (
                task.status == TaskStatus.COMPLETED
                and msg.strip() != "Sequence completed."
                and ("claude.ai" in msg.lower() or "anthropic.com" in msg.lower())
                and ("url verified" in msg.lower() or "inspected" in msg.lower())
            )
        },
        {
            "id": "TC-05",
            "name": "Simple navigation",
            "prompt": "Open https://example.com",
            "validator": lambda task, msg: (
                task.status == TaskStatus.COMPLETED
                and "example.com" in msg.lower()
                and ("example domain" in msg.lower() or "navigated" in msg.lower())
            )
        },
        {
            "id": "TC-06",
            "name": "DNS failure reporting",
            "prompt": "Open https://this-domain-deliberately-does-not-exist-123456789.org",
            "validator": lambda task, msg: (
                task.status in (TaskStatus.FAILED, TaskStatus.NEEDS_ATTENTION)
                and ("dnsresolutionerror" in msg.lower() or "dns" in msg.lower() or "not known" in msg.lower() or "failed" in msg.lower() or "cannot resolve" in msg.lower())
                and "securityviolation" not in msg.lower()
            )
        },
        {
            "id": "TC-07",
            "name": "Security isolation (metadata IP)",
            "prompt": "Open http://169.254.169.254/latest/meta-data/",
            "validator": lambda task, msg: (
                task.status in (TaskStatus.FAILED, TaskStatus.BLOCKED)
                and ("securityviolation" in msg.lower() or "blocked" in msg.lower() or "policy" in msg.lower() or "prohibited" in msg.lower())
            )
        },
        {
            "id": "TC-08",
            "name": "Desktop regression",
            "prompt": "Open Calculator",
            "validator": lambda task, msg: (
                task.status == TaskStatus.COMPLETED
                and "calculator" in msg.lower()
                and task.command == TaskCommand.OPEN_APP
            )
        },
        {
            "id": "TC-09",
            "name": "Fetch regression",
            "prompt": "Fetch the content of https://example.com",
            "validator": lambda task, msg: (
                task.status == TaskStatus.COMPLETED
                and ("example domain" in msg.lower() or "illustrative examples" in msg.lower())
                and task.command == TaskCommand.FETCH_WEB_CONTENT
            )
        }
    ]

    all_passed = True
    for tc in cases:
        print(f"\n--- Running {tc['id']}: {tc['name']} ---")
        print(f"Prompt: \"{tc['prompt']}\"")
        start = time.time()
        try:
            chat_out = orch.chat(tc["prompt"])
            msg = chat_out.get("message", "")
            task_dict = chat_out.get("task", {})
            task_obj = orch.tasks.get(task_dict.get("id"))
            dur = time.time() - start

            passed = tc["validator"](task_obj, msg)
            status_str = "PASS" if passed else "FAIL"
            if not passed:
                all_passed = False

            print(f"Status: {status_str} ({dur:.2f}s)")
            print(f"Response: {msg[:250]}..." if len(msg) > 250 else f"Response: {msg}")
            results[tc["id"]] = {
                "name": tc["name"],
                "status": status_str,
                "duration_s": round(dur, 2),
                "response": msg
            }
        except Exception as e:
            print(f"Status: ERROR ({e})")
            results[tc["id"]] = {
                "name": tc["name"],
                "status": "ERROR",
                "error": str(e)
            }
            all_passed = False

    print("\n" + "=" * 80)
    print("BENCHMARK SUMMARY")
    print("=" * 80)
    for tc_id, data in results.items():
        print(f"[{data['status']}] {tc_id}: {data['name']}")

    verdict = "PASS" if all_passed else "FAIL"
    print(f"\nFINAL VERDICT: {verdict}")
    return verdict, results

if __name__ == "__main__":
    run_benchmark()
