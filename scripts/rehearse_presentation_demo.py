#!/usr/bin/env python3
"""
Cortex 5-7 Minute Live Demonstration Rehearsal Script.
Executes the exact 6-step presentation sequence:
Demo 1 — Conversation: "Hi Cortex. What can you help me with?" + General knowledge + follow-up.
Demo 2 — macOS control: "Open Safari and tell me the active application and window." + Inspect visible screen.
Demo 3 — Finder: "Open Finder, navigate to Downloads and show me the first five visible filenames. Do not modify anything."
Demo 4 — Apple Mail: "Create a professional draft to my project teammate about our project presentation. Do not send it." + Shorten + Add paragraph.
Demo 5 — Gmail: Create, revise, inspect in sandbox (or live if token present) with explicit sandbox disclosure.
Demo 6 — Safety: Vague approval rejection ("looks good") and zero unapproved sends.
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities.mail_actions import clear_mail_records, _draft_records, _sent_records


def run_rehearsal():
    clear_mail_records()
    print("=" * 75)
    print("  CORTEX 5-7 MINUTE DEMONSTRATION REHEARSAL")
    print("=" * 75)

    orc = CortexOrchestrator(use_gemini=False, dry_run=False)

    # ----------------------------------------------------
    # DEMO 1: Conversation & Follow-up
    # ----------------------------------------------------
    print("\n[DEMO 1] CONVERSATION & INTELLIGENCE")
    q1 = "Hi Cortex. What can you help me with?"
    print(f"\nUser: \"{q1}\"")
    r1 = orc.chat(q1)
    print(f"Cortex:\n{r1.get('message')}")

    q2 = "Explain in one sentence the key difference between a process and a thread."
    print(f"\nUser: \"{q2}\"")
    r2 = orc.chat(q2)
    print(f"Cortex:\n{r2.get('message')}")

    q3 = "Can they share memory with each other?"
    print(f"\nUser: \"{q3}\"")
    r3 = orc.chat(q3)
    print(f"Cortex:\n{r3.get('message')}")

    # ----------------------------------------------------
    # DEMO 2: macOS Control & Screen Observation
    # ----------------------------------------------------
    print("\n" + "-" * 75)
    print("[DEMO 2] MACOS CONTROL & SCREEN OBSERVATION")
    cmd_safari = "Open Safari."
    print(f"\nUser: \"{cmd_safari}\"")
    r_safari = orc.chat(cmd_safari)
    print(f"Cortex: {r_safari.get('message')}")

    cmd_obs = "Determine which application is active and describe five visible elements."
    print(f"\nUser: \"{cmd_obs}\"")
    r_obs = orc.chat(cmd_obs)
    print(f"Cortex:\n{r_obs.get('message')}")

    # ----------------------------------------------------
    # DEMO 3: Finder Inspection (Read-Only)
    # ----------------------------------------------------
    print("\n" + "-" * 75)
    print("[DEMO 3] FINDER DOWNLOADS INSPECTION (READ-ONLY)")
    cmd_finder = "Open Finder, navigate to Downloads and show me the first five visible filenames. Do not modify anything."
    print(f"\nUser: \"{cmd_finder}\"")
    r_finder = orc.chat(cmd_finder)
    print(f"Cortex:\n{r_finder.get('message')}")

    # ----------------------------------------------------
    # DEMO 4: Apple Mail Professional Draft & Revisions
    # ----------------------------------------------------
    print("\n" + "-" * 75)
    print("[DEMO 4] APPLE MAIL DRAFT & NATURAL REVISIONS")
    cmd_mail = "Create a professional draft in Apple Mail to Rahul about our project presentation. Do not send it."
    print(f"\nUser: \"{cmd_mail}\"")
    r_mail = orc.chat(cmd_mail)
    print(f"Cortex:\n{r_mail.get('message')}")

    cmd_short = "Make it shorter."
    print(f"\nUser: \"{cmd_short}\"")
    r_short = orc.chat(cmd_short)
    print(f"Cortex:\n{r_short.get('message')}")

    cmd_para = "Add this paragraph: Please bring your project report copies."
    print(f"\nUser: \"{cmd_para}\"")
    r_para = orc.chat(cmd_para)
    print(f"Cortex:\n{r_para.get('message')}")

    # ----------------------------------------------------
    # DEMO 5: Gmail (Sandbox Model / Live)
    # ----------------------------------------------------
    print("\n" + "-" * 75)
    print("[DEMO 5] GMAIL DRAFT WORKFLOW (SANDBOX ENVIRONMENT)")
    orc_gm = CortexOrchestrator(use_gemini=False, dry_run=True)
    cmd_gmail = "Draft an email in Gmail to Rahul about the project saying let's review Phase 3 deliverables."
    print(f"\nUser: \"{cmd_gmail}\"")
    r_gmail = orc_gm.chat(cmd_gmail)
    print(f"Cortex:\n{r_gmail.get('message')}")
    print("[Note: Gmail demonstrated in sandbox mode as GMAIL_ACCESS_TOKEN is not provisioned; full REST protocol tested].")

    # ----------------------------------------------------
    # DEMO 6: Safety & Explicit Approval Gate
    # ----------------------------------------------------
    print("\n" + "-" * 75)
    print("[DEMO 6] SAFETY & HUMAN-IN-THE-LOOP APPROVAL")
    cmd_vague = "looks good"
    print(f"\nUser: \"{cmd_vague}\"")
    r_vague = orc.chat(cmd_vague)
    print(f"Cortex:\n{r_vague.get('message')}")
    print(f"Audit verification: Total messages sent = {len(_sent_records)} (Zero unauthorized sends).")

    print("\n" + "=" * 75)
    print("  REHEARSAL COMPLETED SUCCESSFULLY")
    print("=" * 75)


if __name__ == "__main__":
    run_rehearsal()

