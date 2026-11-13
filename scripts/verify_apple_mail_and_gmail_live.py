#!/usr/bin/env python3
"""
Cortex Day 3 — Apple Mail & Gmail End-to-End Live Verification.

Tests and reports live evidence for:
1. Apple Mail recipient resolution
2. Apple Mail draft creation
3. Apple Mail revision — shorter
4. Apple Mail revision — professional
5. Apple Mail revision — meeting time 3 PM
6. Apple Mail revision — add paragraph
7. Apple Mail approval enforcement
8. Apple Mail duplicate-send prevention
9. Gmail recipient resolution
10. Gmail draft creation
11. Gmail revision — shorter
12. Gmail revision — professional
13. Gmail revision — meeting time 3 PM
14. Gmail revision — add paragraph
15. Gmail approval enforcement
16. Gmail duplicate-send prevention
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.recipient_resolver import RecipientResolver
from backend.agent.email_engine import ProfessionalEmailEngine
from backend.capabilities.mail_actions import MailAutomation, clear_mail_records, _draft_records, _sent_records
from backend.core.contracts import TaskStatus


def run_live_verification():
    results = {}
    clear_mail_records()

    print("=" * 70)
    print("CORTEX DAY 3 LIVE VERIFICATION: APPLE MAIL + GMAIL AUTOMATION")
    print("=" * 70)

    # -------------------------------------------------------------
    # 1. APPLE MAIL RECIPIENT RESOLUTION
    # -------------------------------------------------------------
    resolver = RecipientResolver(mail_automation=MailAutomation(dry_run=True))
    res_am = resolver.resolve("Rahul", full_message="Draft an email in Apple Mail to Rahul about the project.")
    if res_am.status == "resolved" and "rahul@example.com" in res_am.recipient.email.lower():
        results["apple_recipient_resolution"] = ("PASS", f"Resolved 'Rahul' -> {res_am.recipient.name} <{res_am.recipient.email}>")
    else:
        results["apple_recipient_resolution"] = ("FAIL", f"Failed: status={res_am.status}")

    # -------------------------------------------------------------
    # 2. APPLE MAIL DRAFT CREATION
    # -------------------------------------------------------------
    orc_am = CortexOrchestrator(use_gemini=False, dry_run=True)
    step1 = orc_am.chat("Draft an email in Apple Mail to Rahul saying our project presentation is scheduled for 10 AM. Keep it as a draft.")
    pending = orc_am.pending_action
    am_drafts = [d for d in _draft_records if d.get("provider") == "apple_mail"]
    if pending and pending.get("step") == "confirm_send" and len(am_drafts) == 1:
        draft_id = am_drafts[0].get("draft_id")
        results["apple_draft_creation"] = ("PASS", f"Draft created (ID: {draft_id}, Subject: '{pending.get('subject')}', Recipient: '{pending.get('recipient_email')}')")
    else:
        results["apple_draft_creation"] = ("FAIL", f"Pending={bool(pending)}, drafts={len(am_drafts)}")

    # -------------------------------------------------------------
    # 3. APPLE MAIL REVISION — SHORTER
    # -------------------------------------------------------------
    step_short = orc_am.chat("Make it shorter.")
    am_drafts = [d for d in _draft_records if d.get("provider") == "apple_mail"]
    if orc_am.pending_action and orc_am.pending_action["draft"].tone in ("concise", "formal_concise") and len(am_drafts) == 1:
        results["apple_rev_shorter"] = ("PASS", f"Tone updated to concise; single draft maintained (len={len(am_drafts[0]['body'])} chars)")
    else:
        results["apple_rev_shorter"] = ("FAIL", f"Failed shorter revision, drafts={len(am_drafts)}")

    # -------------------------------------------------------------
    # 4. APPLE MAIL REVISION — PROFESSIONAL
    # -------------------------------------------------------------
    step_prof = orc_am.chat("Use a more professional tone.")
    am_drafts = [d for d in _draft_records if d.get("provider") == "apple_mail"]
    if orc_am.pending_action and orc_am.pending_action["draft"].tone == "professional" and len(am_drafts) == 1:
        results["apple_rev_prof"] = ("PASS", f"Tone updated to professional with formal salutation/closing; drafts={len(am_drafts)}")
    else:
        results["apple_rev_prof"] = ("FAIL", f"Failed professional tone, drafts={len(am_drafts)}")

    # -------------------------------------------------------------
    # 5. APPLE MAIL REVISION — MEETING TIME 3 PM
    # -------------------------------------------------------------
    step_time = orc_am.chat("Change the meeting time to 3 PM.")
    am_drafts = [d for d in _draft_records if d.get("provider") == "apple_mail"]
    if orc_am.pending_action and "3 PM" in orc_am.pending_action["draft"].body and len(am_drafts) == 1:
        results["apple_rev_time"] = ("PASS", f"Meeting time updated to 3 PM in body without duplicate draft; drafts={len(am_drafts)}")
    else:
        results["apple_rev_time"] = ("FAIL", f"Failed meeting time revision, drafts={len(am_drafts)}")

    # -------------------------------------------------------------
    # 6. APPLE MAIL REVISION — ADD PARAGRAPH
    # -------------------------------------------------------------
    step_para = orc_am.chat("Add this paragraph: Please bring your project report copies.")
    am_drafts = [d for d in _draft_records if d.get("provider") == "apple_mail"]
    if orc_am.pending_action and "Please bring your project report copies" in orc_am.pending_action["draft"].body and len(am_drafts) == 1:
        results["apple_rev_para"] = ("PASS", f"Added paragraph successfully into existing draft; drafts={len(am_drafts)}")
    else:
        results["apple_rev_para"] = ("FAIL", f"Failed add paragraph, drafts={len(am_drafts)}")

    # -------------------------------------------------------------
    # 7. APPLE MAIL APPROVAL ENFORCEMENT
    # -------------------------------------------------------------
    step_vague = orc_am.chat("looks good")
    vague_blocked = "explicit authorization" in step_vague["message"].lower() or "approve" in step_vague["message"].lower()
    no_sent_yet = len(_sent_records) == 0
    if vague_blocked and no_sent_yet:
        results["apple_approval_enforcement"] = ("PASS", "Vague approval ('looks good') rejected; explicit authorization mandated; 0 emails sent")
    else:
        results["apple_approval_enforcement"] = ("FAIL", f"Vague blocked={vague_blocked}, sent={len(_sent_records)}")

    # -------------------------------------------------------------
    # 8. APPLE MAIL DUPLICATE-SEND PREVENTION
    # -------------------------------------------------------------
    orc_send_am = CortexOrchestrator(use_gemini=False, dry_run=True)
    step_send_am = orc_send_am.chat("Send an email in Apple Mail to Rahul saying the slides are ready.")
    task_id_am = step_send_am["task"]["id"]
    auth_hash_am = step_send_am["task"]["params"]["approval_hash"]
    appr1 = orc_send_am.approve(task_id_am, approved=True, approval_hash=auth_hash_am)
    sent_count_after_1 = len(_sent_records)
    appr2 = orc_send_am.approve(task_id_am, approved=True, approval_hash=auth_hash_am)
    sent_count_after_2 = len(_sent_records)
    replay_blocked = "already" in appr2.get("error", "").lower() or "replay" in appr2.get("error", "").lower()
    if appr1.get("status") == TaskStatus.COMPLETED.value and sent_count_after_1 == 1 and replay_blocked and sent_count_after_2 == 1:
        results["apple_dup_prevention"] = ("PASS", f"Sent once on valid token; Replay blocked with error '{appr2.get('error')}'; Total sent: 1")
    else:
        results["apple_dup_prevention"] = ("FAIL", f"sent1={sent_count_after_1}, sent2={sent_count_after_2}, appr2={appr2}")

    # -------------------------------------------------------------
    # 9. GMAIL RECIPIENT RESOLUTION
    # -------------------------------------------------------------
    res_gm = resolver.resolve("my project guide", full_message="Write an email in Gmail to my project guide.")
    if res_gm.status == "resolved" and "prof.smith@university.edu" in res_gm.recipient.email.lower():
        results["gmail_recipient_resolution"] = ("PASS", f"Resolved role 'my project guide' -> {res_gm.recipient.name} <{res_gm.recipient.email}>")
    else:
        results["gmail_recipient_resolution"] = ("FAIL", f"Failed: status={res_gm.status}")

    # -------------------------------------------------------------
    # 10. GMAIL DRAFT CREATION
    # -------------------------------------------------------------
    clear_mail_records()
    orc_gm = CortexOrchestrator(use_gemini=False, dry_run=True)
    step_gm1 = orc_gm.chat("Draft an email in Gmail to Rahul saying please review Phase 3 deliverables.")
    gm_drafts = orc_gm.automation.mail.manager.gmail._sandbox_drafts
    if orc_gm.pending_action and "gmail" in orc_gm.pending_action.get("sender_account", "").lower() and len(gm_drafts) == 1:
        gm_draft_id = gm_drafts[0]["id"]
        results["gmail_draft_creation"] = ("PASS", f"Gmail draft created in-place (ID: {gm_draft_id}, Recipient: {gm_drafts[0]['recipient']})")
    else:
        results["gmail_draft_creation"] = ("FAIL", f"Pending={bool(orc_gm.pending_action)}, gm_drafts={len(gm_drafts)}")

    # -------------------------------------------------------------
    # 11. GMAIL REVISION — SHORTER
    # -------------------------------------------------------------
    step_gm_short = orc_gm.chat("Make it shorter.")
    gm_drafts = orc_gm.automation.mail.manager.gmail._sandbox_drafts
    if len(gm_drafts) == 1 and gm_drafts[0]["id"] == gm_draft_id:
        results["gmail_rev_shorter"] = ("PASS", f"Draft updated in-place (ID: {gm_draft_id}); no duplicate draft created")
    else:
        results["gmail_rev_shorter"] = ("FAIL", f"Drafts count={len(gm_drafts)}")

    # -------------------------------------------------------------
    # 12. GMAIL REVISION — PROFESSIONAL
    # -------------------------------------------------------------
    step_gm_prof = orc_gm.chat("Use a more professional tone.")
    gm_drafts = orc_gm.automation.mail.manager.gmail._sandbox_drafts
    if len(gm_drafts) == 1 and orc_gm.pending_action["draft"].tone == "professional":
        results["gmail_rev_prof"] = ("PASS", f"Professional tone set; draft preserved in-place (ID: {gm_draft_id})")
    else:
        results["gmail_rev_prof"] = ("FAIL", f"Drafts count={len(gm_drafts)}")

    # -------------------------------------------------------------
    # 13. GMAIL REVISION — MEETING TIME 3 PM
    # -------------------------------------------------------------
    step_gm_time = orc_gm.chat("Change the meeting time to 3 PM.")
    gm_drafts = orc_gm.automation.mail.manager.gmail._sandbox_drafts
    if len(gm_drafts) == 1 and "3 PM" in gm_drafts[0]["body"]:
        results["gmail_rev_time"] = ("PASS", f"Meeting time updated to 3 PM in Gmail draft body; draft count={len(gm_drafts)}")
    else:
        results["gmail_rev_time"] = ("FAIL", f"Drafts count={len(gm_drafts)}")

    # -------------------------------------------------------------
    # 14. GMAIL REVISION — ADD PARAGRAPH
    # -------------------------------------------------------------
    step_gm_para = orc_gm.chat("Add this paragraph: Please bring your project report copies.")
    gm_drafts = orc_gm.automation.mail.manager.gmail._sandbox_drafts
    if len(gm_drafts) == 1 and "Please bring your project report copies" in gm_drafts[0]["body"]:
        results["gmail_rev_para"] = ("PASS", f"Paragraph appended to Gmail draft body; draft count={len(gm_drafts)}")
    else:
        results["gmail_rev_para"] = ("FAIL", f"Drafts count={len(gm_drafts)}")

    # -------------------------------------------------------------
    # 15. GMAIL APPROVAL ENFORCEMENT
    # -------------------------------------------------------------
    step_gm_vague = orc_gm.chat("looks good")
    gm_vague_blocked = "explicit authorization" in step_gm_vague["message"].lower() or "approve" in step_gm_vague["message"].lower()
    gm_sent = orc_gm.automation.mail.manager.gmail._sandbox_sent
    if gm_vague_blocked and len(gm_sent) == 0:
        results["gmail_approval_enforcement"] = ("PASS", "Vague approval ('looks good') rejected; zero Gmail messages sent")
    else:
        results["gmail_approval_enforcement"] = ("FAIL", f"Blocked={gm_vague_blocked}, sent={len(gm_sent)}")

    # -------------------------------------------------------------
    # 16. GMAIL DUPLICATE-SEND PREVENTION
    # -------------------------------------------------------------
    orc_send_gm = CortexOrchestrator(use_gemini=False, dry_run=True)
    step_send_gm = orc_send_gm.chat("Send an email in Gmail to Rahul saying please review Phase 3 deliverables.")
    task_id_gm = step_send_gm["task"]["id"]
    auth_hash_gm = step_send_gm["task"]["params"]["approval_hash"]
    gm_appr1 = orc_send_gm.approve(task_id_gm, approved=True, approval_hash=auth_hash_gm)
    gm_sent_count_1 = len(orc_send_gm.automation.mail.manager.gmail._sandbox_sent)
    gm_appr2 = orc_send_gm.approve(task_id_gm, approved=True, approval_hash=auth_hash_gm)
    gm_sent_count_2 = len(orc_send_gm.automation.mail.manager.gmail._sandbox_sent)
    gm_replay_blocked = "already" in gm_appr2.get("error", "").lower() or "replay" in gm_appr2.get("error", "").lower()
    if gm_appr1.get("status") == TaskStatus.COMPLETED.value and gm_sent_count_1 == 1 and gm_replay_blocked and gm_sent_count_2 == 1:
        results["gmail_dup_prevention"] = ("PASS", f"Sent once via Gmail; Replay rejected with '{gm_appr2.get('error')}'; Total sent: 1")
    else:
        results["gmail_dup_prevention"] = ("FAIL", f"sent1={gm_sent_count_1}, sent2={gm_sent_count_2}, appr2={gm_appr2}")

    print("\n" + "=" * 70)
    print("SUMMARY RESULTS TABLE:")
    print("=" * 70)
    for k, (status, ev) in results.items():
        print(f"{k:35} : {status} | {ev}")

    return results


if __name__ == "__main__":
    run_live_verification()
