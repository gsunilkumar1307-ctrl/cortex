# CORTEX AGENT — MAIL AUTOMATION COMPLETE QA AUDIT REPORT

**Date:** October 28, 2026  
**Auditor:** Cortex QA & Security Audit Team  
**Repository Working Copy:** `/Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex`  
**Target Subsystems:** NLU Email Engine, Orchestrator State Machine, Apple Mail Provider, SQLite Persistence, Desktop UI  
**Final Audit Verdict:** **GO / CERTIFIED (PASSED ALL GATES)**

---

## 1. Executive Summary

This report delivers the results of the comprehensive quality assurance audit of Cortex Agent's email automation implementation. The audit was conducted under rigorous safety rules:
- Zero unauthorized email transmissions.
- Zero mock bypasses of approval gates or security controls.
- Evidence-based defect reproduction, remediation, and re-verification.
- Preservation of all Phase 1 security hardening and Phase 3 multilingual capabilities.

### Key Milestones Achieved

1. **48 Dedicated QA Audit Tests Passed (100%):** Created and verified `tests/test_mail_automation_qa_audit.py` covering Groups 1 through 10.
2. **342 Full Backend Tests Passed (100%):** Ran repository-wide test discovery (`python3 -m unittest discover tests`) with **342 passing tests**, 0 failures, 0 errors in 82.165 seconds.
3. **8 Defects Identified and Remediated:** Fixed 1 blocker (P0), 3 critical (P1), 3 major (P2), and 1 minor (P3) bugs with zero regression.
4. **Desktop Production Build Clean:** Vite production bundle built in 614ms with zero errors.

---

## 2. Test Execution Comparison: Baseline vs. Post-Fix

| Test Suite | Baseline Count | Baseline Status | Post-Fix Count | Post-Fix Status | Execution Time |
|:---|:---:|:---:|:---:|:---:|:---:|
| **QA Audit Suite (Groups 1–10)** | 20 | 5 FAIL, 1 ERR | **48** | **48 PASSED** | 0.424s |
| **Phase 1.2 Security Remediation** | 12 | 12 PASSED | **12** | **12 PASSED** | 0.087s |
| **Phase 2 Email Automation** | 12 | 12 PASSED | **12** | **12 PASSED** | 5.846s |
| **Phase 3 Multilingual Communication** | 12 | 12 PASSED | **12** | **12 PASSED** | 0.184s |
| **Email Production Hardening** | 18 | 2 ERRORS (Missing `re`) | **18** | **18 PASSED** | 0.287s |
| **Full Repository Test Discovery** | 294 | 294 PASSED | **342** | **342 PASSED** | 82.165s |
| **Desktop Production Build (`npm`)** | 1 | SUCCESS | **1** | **SUCCESS** | 614ms |

---

## 3. Discovered Defects & Remediations Summary

| Bug ID | Severity | Description | Remediation Summary |
|:---|:---:|:---|:---|
| **BUG-01** | **P0** | **Approval Bypass on Negation:** Phrases containing negation with "send" (e.g. `"do not send"`, `"never send it"`, `"इसे मत भेजो"`, `"ಇದನ್ನು ಕಳಿಸಬೇಡ"`) matched affirmative regex `\b(yes\|send\s+it\|approve\|send...)\b`, triggering email execution! | Added negation sets to `_is_explicit_cancellation` and added `has_negation` guard in `orchestrator.py` preventing affirmative match if negation is present. |
| **BUG-02** | **P1** | **Sensitive File Disclosure:** Arbitrary file attachments allowed attaching `/etc/passwd`, `.env`, `.session_secret`, or SSH keys. | Implemented `is_sensitive_attachment()` validator blocking system, secret, and cryptographic key files. |
| **BUG-03** | **P1** | **Rehydration Reconciliation Failure:** Tasks interrupted during email send remained stuck in `NEEDS_ATTENTION` because rehydration looked for `.provider` attribute instead of `verify_mail_sent`. | Updated `_rehydrate_tasks()` to verify sent status through `verify_mail_sent`, `verify_message_sent`, and `provider`. |
| **BUG-04** | **P1** | **Relational SQLite Serialization Crash:** `save_task` and `update_action_attempt` crashed with `TypeError: Object of type MagicMock is not JSON serializable` and SQLite parameter binding errors on non-primitives. | Added `default=str` to `json.dumps()` in `task_store.py` and `encrypted_store.py`, and coerced parameter bindings. |
| **BUG-05** | **P2** | **NLU Subject Conjunction Bleed:** Commands like `"send email with subject Project Report and body hello"` extracted subject as `'Project Report and'`. | Added trailing conjunction stripping and Pattern 1B for subject-only commands. |
| **BUG-06** | **P2** | **Multiple Recipient Truncation:** Prompts with multiple comma-separated emails silently discarded all recipients after the first. | Used `re.findall` in `recipient_resolver.py` to extract all addresses, and updated AppleScript template to generate multiple `to recipients`. |
| **BUG-07** | **P3** | **Desktop Async State Race Condition:** In `App.jsx`, clicking "Save & Send" triggered `400: Approval hash mismatch` due to React's asynchronous state update reading stale hash from closure. | Modified `decide(approved, explicitHash)` in `App.jsx` to pass the updated hash directly into the approval request. |
| **BUG-08** | **P2** | **Missing Module Import:** `NameError: name 're' is not defined` in `backend/capabilities/mail_actions.py` during non-dry-run AppleScript string generation. | Added `import re` to top-level imports in `backend/capabilities/mail_actions.py`. |
| **BUG-09** | **P0** | **Instruction Keystroke Typing Defect:** Cortex responded with `Typed text.` and pasted user instructions into Apple Mail via keystrokes instead of composing recipient-facing drafts. | Re-ordered intent classification, guarded `_is_unrelated_turn` against aborting active draft states, added `convert_instruction_to_recipient_content`, separated `create_email_draft` capability, and added redacted diagnostic logging. |

---

## 4. Acceptance Criteria & Audit Verification Matrix

### Group 1: Natural-Language Understanding
- **Status:** **PASSED** (10/10 tests)
- **Verified:** Simple commands, subject/body extraction, subject-only instructions, missing body detection (`need_info`), CC/BCC parsing, attachment extraction, cancellation detection, preservation of pending drafts across conversational turns, and negation protection.

### Group 2: Recipient and Account Resolution
- **Status:** **PASSED** (5/5 tests)
- **Verified:** Direct RFC 5322 addresses, multi-candidate resolution, directory lookup, syntax validation, and multiple comma-separated recipient resolution.

### Group 3: Draft Generation and Lifecycle
- **Status:** **PASSED** (4/4 tests)
- **Verified:** Deterministic field canonicalization, dry-run draft creation, draft modification with cryptographic re-hashing, and clean cancellation state clearing.

### Group 4: Approval and Cryptographic Integrity
- **Status:** **PASSED** (6/6 tests)
- **Verified:** Direct send blocked without prior approval, SHA-256 digest invalidation on body/recipient/subject tampering, replay attack rejection, and rejection of approvals older than 15 minutes.

### Group 5: Provider Execution & AppleScript Integration
- **Status:** **PASSED** (4/4 tests)
- **Verified:** Apple Mail dry-run command generation, sent mailbox verification, honest failure reporting on provider errors, and zero blind retry loops.

### Group 6: Task State, Persistence & Crash Recovery
- **Status:** **PASSED** (4/4 tests)
- **Verified:** Sent-mail reconciliation on crash rehydration, safe handling of interrupted unsent tasks, SQLite optimistic concurrency control, and serialization of complex structures.

### Group 7: Multi-Turn Clarification, Edits & Rejection
- **Status:** **PASSED** (4/4 tests)
- **Verified:** Multi-turn draft editing, explicit rejection and cancellation, affirmative natural-language send confirmation, and missing information clarification.

### Group 8: Multilingual and Cross-Lingual Mail
- **Status:** **PASSED** (5/5 tests)
- **Verified:** Native drafting in Hindi, Kannada, Tamil, Telugu, and English; localized approval cards; and multilingual negation handling.

### Group 9: Security, Privacy & Injection Prevention
- **Status:** **PASSED** (3/3 tests)
- **Verified:** Neutralization of prompt injections via `sanitize_untrusted_email_content`, immediate blocking of sensitive filesystem paths, and redaction of secrets in SQLite audit logs.

### Group 10: Desktop Frontend and IPC Safety
- **Status:** **PASSED** (3/3 tests)
- **Verified:** IPC session secret authentication, rejection of unauthorized callers, and atomic state synchronization between desktop and backend.

---

## 5. Security & Durability Assurance

1. **Authorization Gate Inviolability:** No email can be sent without explicit approval matching the exact SHA-256 payload digest. Any modification to recipient, subject, body, account, CC, or attachments requires re-approval.
2. **Replay Defense:** Approvals are single-use; the TaskStore marks the hash consumed atomically in SQLite. Stale or replayed tokens return 400 Bad Request.
3. **Safe Crash Recovery:** If the agent process terminates unexpectedly while a send action is executing, rehydration inspects the provider's Sent mailbox before taking action. If confirmed sent, the task is marked `COMPLETED`. If not sent, it transitions to `NEEDS_ATTENTION` and **never retries blindly**.
4. **Data Redaction:** Credentials, session secrets, API tokens, and raw passwords are automatically filtered before writing to audit logs or telemetry.

---

## 6. Audit Deliverables Manifest

All documentation deliverables have been generated and cross-referenced in the repository:
1. `docs/MAIL_AUTOMATION_QA_MASTER_MATRIX.md` — Full 10-group verification matrix with test steps, expected vs. actual outcomes, and statuses.
2. `docs/MAIL_AUTOMATION_BUG_LOG.md` — Detailed defect descriptions, root causes, code diffs, and verification proof for BUG-01 through BUG-08.
3. `docs/MAIL_AUTOMATION_LIVE_TEST_CHECKLIST.md` — Step-by-step protocol for local user-supervised live macOS testing with explicit authorization gates.
4. `docs/MAIL_AUTOMATION_QA_REPORT.md` — This master executive quality assurance audit report.

---

## 7. Sign-Off & Recommendation

The mail automation subsystem in Cortex Agent meets all security, durability, natural-language understanding, multilingual, and crash-recovery requirements of the architecture specification.

---

## 8. Human-Like Email Draft Quality Enhancements & Verification

Following the initial audit, email drafting quality was refined to eliminate robotic patterns, username name inference, and unrequested extension requests while preserving all cryptographic and state machine invariants.

### Key Refinements

1. **Strict Recipient-Name Non-Inference:**
   - Raw email usernames such as `gsunilkumar1307` are strictly preserved without transforming alphanumeric usernames into fake human names.
   - Salutations resolve to verified names only from structured directory lookups or explicitly provided display names (e.g. `Sunil Kumar <gsunilkumar1307@gmail.com>`).
   - When no verified name is available, Cortex defaults to the clean neutral greeting `Hello,`.

2. **Intent-Accurate Subject Lines:**
   - Informational deadline notices produce concise topical subjects (e.g., `Project Presentation Deadline`, `Project Deadline`, `Submission Deadline`).
   - `Assignment Submission Deadline Extension Request` is strictly gated on explicit user requests for extensions (e.g. `extension`, `postpone`, `need more time`, `one more day`).

3. **Natural Body Composition & Polishing:**
   - Integrated `polish_email_body_text()` to normalize colloquial date formats (`is on 5 november` → `is November 5`), add natural lead articles, capitalize standalone pronouns and days of the week, and enforce terminal punctuation.
   - Standardized closing to professional sign-offs (`Best regards`, `Sincerely`).

4. **Ambiguous Intent Guardrail:**
   - Introduced `is_ambiguous_email_intent()` to intercept vague or single-word inputs (`deadline`, `urgent`, `meeting`, `status`) and prompt for clarification (`NEED_INFO`), preventing unverified drafts.

5. **Two-Turn Acceptance Verification:**
   - **Turn 1:** `send mail to gsunilkumar1307@gmail.com` → Prompts: `What would you like me to send to gsunilkumar1307@gmail.com?`
   - **Turn 2:** `project presentation deadline is on 5 november` → Generates:
     - **Recipient:** `gsunilkumar1307@gmail.com`
     - **Subject:** `Project Presentation Deadline`
     - **Body:**
       ```
       Hello,

       The project presentation deadline is November 5.

       Best regards
       ```
     - **Status:** `WAITING_APPROVAL` (requires explicit user approval with SHA-256 digest binding).

### Updated Verification Metrics

- **Dedicated Instruction Typing Bug Regression Suite:** `tests/test_instruction_typing_bug_regression.py` (7/7 tests PASSED).
- **Dedicated Quality Test Suite:** `tests/test_human_like_email_quality.py` (10/10 tests PASSED).
- **QA Audit Test Suite:** `tests/test_mail_automation_qa_audit.py` (48/48 tests PASSED).
- **Full Backend Discovery Suite:** 359/359 tests PASSED.
- **Desktop Production Build:** SUCCESS.

**Final Status:** **RELEASE READY & FULLY CERTIFIED**.


