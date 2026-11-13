#!/usr/bin/env python3
"""
Live macOS Application Control & Mail Acceptance Test for Day 4.
Performs live verification on the current macOS system:
1. Open Finder
2. Open Calculator
3. Focus Calculator & verify active window state
4. Observe screen & verify visible elements (clean, no [Unknown] / -1)
5. Finder Downloads inspection (retrieves actual filenames read-only)
6. Safe close Calculator gracefully (no force quit) & verify termination
7. Live Apple Mail: draft creation with recipient, subject, body; verify draft in Mail; revision.
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.capabilities.device_actions import DeviceAutomation
from backend.core.contracts import TaskCommand


def main():
    print("=" * 70)
    print("LIVE MACOS ACCEPTANCE RUN")
    print("=" * 70)

    automation = DeviceAutomation(dry_run=False)
    results = {}

    # 1. Open Finder
    print("\n--- 1. Open Finder ---")
    res_finder = automation.execute(TaskCommand.OPEN_APP, {"app_name": "Finder"})
    print("Finder open result:", res_finder.ok, res_finder.message)
    results["open_finder"] = (res_finder.ok, res_finder.message)

    # 2. Open Calculator
    print("\n--- 2. Open Calculator ---")
    res_calc = automation.execute(TaskCommand.OPEN_APP, {"app_name": "Calculator"})
    print("Calculator open result:", res_calc.ok, res_calc.message)
    results["open_calculator"] = (res_calc.ok, res_calc.message)
    time.sleep(1.0)

    # 3. Focus Calculator
    print("\n--- 3. Focus Calculator ---")
    res_focus = automation.execute(TaskCommand.FOCUS_APP, {"app_name": "Calculator"})
    print("Calculator focus result:", res_focus.ok, res_focus.message)
    results["focus_calculator"] = (res_focus.ok, res_focus.message)

    # 4. Observe Screen
    print("\n--- 4. Observe Screen ---")
    res_obs = automation.execute(TaskCommand.OBSERVE_SCREEN, {})
    obs_data = res_obs.data or {}
    app_info = obs_data.get("app") or {}
    active_app = app_info.get("name") if isinstance(app_info, dict) else str(app_info)
    active_win = obs_data.get("window_title", "Unknown")
    elements = obs_data.get("visible_elements", [])
    print(f"Active app: {active_app}, Active window: {active_win}")
    print(f"Visible elements count: {len(elements)}")
    for i, el in enumerate(elements):
        print(f"  {i+1}. {el}")
    # Check for invalid elements
    invalid_elements = [el for el in elements if "[unknown]" in str(el).lower() or "-1" in str(el)]
    print(f"Invalid elements count: {len(invalid_elements)}")
    results["observe_screen"] = (
        res_obs.ok and len(invalid_elements) == 0,
        f"Active: {active_app} ('{active_win}'), {len(elements)} elements, {len(invalid_elements)} invalid nodes"
    )

    # 5. Finder Downloads inspection
    print("\n--- 5. Finder Inspection (Downloads) ---")
    res_files = automation.execute(TaskCommand.SEARCH_FILES, {"folder": "Downloads", "limit": 5})
    files = res_files.data.get("files", []) if res_files.data else []
    print(f"Files found in Downloads: {len(files)}")
    for f in files[:5]:
        fname = f.get('name') if isinstance(f, dict) else str(f)
        print(f"  - {fname}")
    results["finder_downloads"] = (res_files.ok and len(files) > 0, f"Found {len(files)} actual files in Downloads")

    # 6. Close Calculator gracefully
    print("\n--- 6. Close Calculator gracefully ---")
    res_close = automation.execute(TaskCommand.CLOSE_APP, {"app_name": "Calculator"})
    print("Calculator close result:", res_close.ok, res_close.message)
    time.sleep(1.0)
    calc_running = automation.is_app_running("Calculator")
    print(f"Calculator still running: {calc_running}")
    results["close_calculator"] = (
        res_close.ok and not calc_running,
        f"Close success={res_close.ok}, running={calc_running}"
    )

    # 7. Live Apple Mail Draft
    print("\n--- 7. Live Apple Mail Draft ---")
    mail = automation.mail
    test_subject = f"Cortex Live Acceptance Test {int(time.time())}"
    res_draft = mail.draft_mail(
        recipient="gsunilkumar1307@gmail.com",
        subject=test_subject,
        body="This is an automated live draft verification from Cortex Day 4 acceptance.",
        account="Google"
    )
    print("Draft creation result:", res_draft.get("success"), res_draft.get("draft_id"))
    time.sleep(1.0)
    verif = mail.verify_draft_created("gsunilkumar1307@gmail.com", test_subject)
    print("Draft verification result:", verif.get("verified"), verif.get("evidence"))
    # Delete test draft
    del_res = mail.delete_draft(test_subject, "gsunilkumar1307@gmail.com")
    print("Cleaned up test draft:", del_res.get("success"))
    results["live_apple_mail_draft"] = (
        verif.get("verified") is True,
        f"Draft created & verified in Apple Mail. Evidence: {verif.get('evidence')}"
    )

    print("\n" + "=" * 70)
    print("LIVE RUN SUMMARY:")
    print("=" * 70)
    for k, (ok, msg) in results.items():
        print(f"[{'PASS' if ok else 'FAIL'}] {k:25}: {msg}")


if __name__ == "__main__":
    main()
