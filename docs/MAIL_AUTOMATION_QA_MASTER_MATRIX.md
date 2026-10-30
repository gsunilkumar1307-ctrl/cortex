# CORTEX AGENT — MAIL AUTOMATION QA MASTER MATRIX

**Date:** October 28, 2026  
**Auditor:** Cortex QA & Security Audit Team  
**Repository Working Copy:** `/Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex`  
**Test Suite Reference:** `tests/test_mail_automation_qa_audit.py` (48 Dedicated Tests) + Full Backend Suite (342 Tests)  
**Overall Status:** **PASSED** (Automated Suite: 48/48 PASSED; Live External Execution: NOT TESTED / BLOCKED by Sandbox Authorization Protocol)

---

## 1. Executive Summary Table

| Group | Subsystem / Focus Area | Total Tests | Passed | Failed | Blocked / Not Tested | Status |
|:---|:---|:---:|:---:|:---:|:---:|:---:|
| **Group 1** | Natural-Language Understanding (NLU) & Intent | 10 | 10 | 0 | 0 | **PASSED** |
| **Group 2** | Recipient & Account Resolution | 5 | 5 | 0 | 0 | **PASSED** |
| **Group 3** | Draft Generation & Lifecycle | 4 | 4 | 0 | 0 | **PASSED** |
| **Group 4** | Approval & Cryptographic Integrity (SHA-256) | 6 | 6 | 0 | 0 | **PASSED** |
| **Group 5** | Provider Execution & AppleScript Integration | 4 | 4 | 0 | 0 | **PASSED** |
| **Group 6** | Task State, Persistence & Crash Recovery | 4 | 4 | 0 | 0 | **PASSED** |
| **Group 7** | Multi-Turn Clarification, Edits & Rejection | 4 | 4 | 0 | 0 | **PASSED** |
| **Group 8** | Multilingual & Cross-Lingual Mail (5 Languages) | 5 | 5 | 0 | 0 | **PASSED** |
| **Group 9** | Security, Privacy & Injection Prevention | 3 | 3 | 0 | 0 | **PASSED** |
| **Group 10** | Desktop Frontend & IPC Safety | 3 | 3 | 0 | 0 | **PASSED** |
| **TOTAL** | **Comprehensive QA Audit Suite** | **48** | **48** | **0** | **0** | **100% PASS** |

---

## 2. Detailed Test Verification Matrix

### Group 1: Natural-Language Understanding (NLU) & Intent Extraction

| Test ID | Scenario | Preconditions | Execution Steps | Expected Result | Actual Result | Evidence Reference | Status |
|:---|:---|:---|:---|:---|:---|:---|:---:|
| **QA-G1-01** | Simple direct email command | EmailEngine instantiated | `extract_command_and_content("send email to prof.kapoor@iitb.ac.in saying meeting at 3pm")` | Recipient: `prof.kapoor@iitb.ac.in`, Body: `meeting at 3pm` | Correctly extracted recipient and body | `test_g1_01_simple_email_instruction` | **PASSED** |
| **QA-G1-02** | Subject and body extraction | EmailEngine instantiated | `extract_command_and_content("send an email to user@test.com with subject Project Report and body please find the update")` | Recipient: `user@test.com`, Subject: `Project Report` (no trailing 'and'), Body: `please find the update` | Trailing conjunction stripped; subject is `Project Report` | `test_g1_02_subject_and_body_extraction` | **PASSED** |
| **QA-G1-03** | Instruction omitting subject | EmailEngine instantiated | `extract_command_and_content("send email to dr.sharma@hospital.org saying the surgery was successful")` | Recipient extracted, engine generates intelligent subject fallback | Extracted recipient, composed draft generated non-empty relevant subject | `test_g1_03_instruction_omitting_subject` | **PASSED** |
| **QA-G1-04** | Instruction omitting body | Clean orchestrator instance | `orc.chat("draft an email to user@test.com")` | Task transitions to `NEED_INFO` asking for body; does not proceed blindly | Task status is `need_info`, prompting user for email body | `test_g1_04_instruction_omitting_body` | **PASSED** |
| **QA-G1-05** | Instruction with subject only | EmailEngine instantiated | `extract_command_and_content("send email to user@test.com with subject Annual Review")` | Recipient: `user@test.com`, Subject: `Annual Review`, Content: `""` | Pattern 1B matches subject cleanly | `test_g1_05_instruction_with_subject_only` | **PASSED** |
| **QA-G1-06** | CC and BCC extraction | EmailEngine instantiated | `extract_command_and_content("send email to user@test.com with cc manager@test.com with bcc hr@test.com saying approved")` | CC list contains `manager@test.com`, BCC contains `hr@test.com` | Both CC and BCC lists accurately populated | `test_g1_06_cc_and_bcc_extraction` | **PASSED** |
| **QA-G1-07** | Attachment extraction | EmailEngine instantiated | `extract_command_and_content("send email to client@partner.com with attachment presentation.pdf saying deck attached")` | Attachment list contains `presentation.pdf` | Attachment accurately extracted | `test_g1_07_attachment_extraction` | **PASSED** |
| **QA-G1-08** | Cancellation instruction | Orchestrator with pending draft | `orc.chat("cancel")` | Task transitions to `CANCELED`, pending action cleared | Pending action cleared, task canceled | `test_g1_08_cancellation_instruction` | **PASSED** |
| **QA-G1-09** | Unrelated instruction turn | Orchestrator with pending draft | `orc.chat("what is 2 + 2?")` | General question answered without discarding pending draft | Pending action preserved with step `confirm_send` | `test_g1_09_unrelated_instruction_preserves_pending_draft` | **PASSED** |
| **QA-G1-10** | Negation with "send" (BUG-01 Fix) | Orchestrator with pending draft | `orc.chat("do not send")` | Negation guard prevents affirmative regex matching `send`; task canceled | `has_negation` guard triggers, pending action cleared, task canceled | `test_g1_10_negation_prevents_accidental_confirmation` | **PASSED** |

---

### Group 2: Recipient and Account Resolution

| Test ID | Scenario | Preconditions | Execution Steps | Expected Result | Actual Result | Evidence Reference | Status |
|:---|:---|:---|:---|:---|:---|:---|:---:|
| **QA-G2-01** | Direct RFC 5322 email | RecipientResolver | `rr.resolve("alice@example.com")` | Status: `resolved`, Email: `alice@example.com` | Resolved with 1.0 confidence | `test_g2_01_direct_email_resolution` | **PASSED** |
| **QA-G2-02** | Invalid email syntax | RecipientResolver | `rr.resolve("invalid_user_address")` | Status: `need_clarification` | Requested clarification from user | `test_g2_02_invalid_email_syntax_requires_clarification` | **PASSED** |
| **QA-G2-03** | Multiple comma recipients (BUG-06 Fix) | RecipientResolver | `rr.resolve("alice@example.com, bob@example.com")` | Resolves all recipients without truncation | Both emails preserved and joined | `test_g2_03_multiple_recipient_resolution` | **PASSED** |
| **QA-G2-04** | Directory lookup resolution | RecipientResolver with institutional directory | `rr.resolve("Dr. Shanmukha Nagaraj")` | Status: `resolved`, Email: `hod.cse@rvce.edu.in` | Resolved from institutional directory | `test_g2_04_directory_lookup_resolution` | **PASSED** |
| **QA-G2-05** | Ambiguous recipient query | RecipientResolver with institutional directory | `rr.resolve("hod")` | Status: `multiple_candidates` or `need_clarification` | Candidates list > 1 returned for user disambiguation | `test_g2_05_ambiguous_recipient_multiple_candidates` | **PASSED** |

---

### Group 3: Draft Generation and Lifecycle

| Test ID | Scenario | Preconditions | Execution Steps | Expected Result | Actual Result | Evidence Reference | Status |
|:---|:---|:---|:---|:---|:---|:---|:---:|
| **QA-G3-01** | Canonicalization & Hash | EmailDraft instantiated with messy whitespace | Call `draft.canonicalize()` and `draft.compute_hash()` | Whitespace trimmed, lowercase recipients, valid 64-char SHA-256 | Canonicalized fields match; 64-char hex digest returned | `test_g3_01_draft_canonicalization_and_hash` | **PASSED** |
| **QA-G3-02** | Dry-run draft creation | MailAutomation in dry-run mode | Call `mail_auto.draft_mail(...)` | Returns `ok: True`, `dry_run: True`, draft record recorded | Dry-run flag and record confirmed | `test_g3_02_draft_creation_dry_run` | **PASSED** |
| **QA-G3-03** | Draft modification & re-hashing | EmailDraft instantiated | Modify subject and body via `ee.edit_draft` | Fields updated, new cryptographic hash differs from original | Fields updated and hash invalidated | `test_g3_03_draft_modification` | **PASSED** |
| **QA-G3-04** | Draft cancellation clears state | Orchestrator with draft awaiting send | Execute `orc.chat("cancel")` | Orchestrator state resets, pending draft deleted | `pending_action` cleared, task canceled | `test_g3_04_draft_cancellation_clears_state` | **PASSED** |

---

### Group 4: Approval and Cryptographic Integrity

| Test ID | Scenario | Preconditions | Execution Steps | Expected Result | Actual Result | Evidence Reference | Status |
|:---|:---|:---|:---|:---|:---|:---|:---:|
| **QA-G4-01** | Send execution without approval | Task in `WAITING_APPROVAL` | Direct call to `orc._execute(task)` | Direct execution denied, task marked `BLOCKED` | Task status set to `BLOCKED` with approval required error | `test_g4_01_no_send_without_approval` | **PASSED** |
| **QA-G4-02** | Hash invalidation on body change | Original draft created and hashed | Change body text | Hash recomputation produces different SHA-256 | Hash changed, old approval token invalid | `test_g4_02_approval_digest_invalidation_on_body_change` | **PASSED** |
| **QA-G4-03** | Hash invalidation on recipient change | Original draft created and hashed | Change recipient address | Hash recomputation produces different SHA-256 | Hash changed, tampering detected | `test_g4_03_approval_digest_invalidation_on_recipient_change` | **PASSED** |
| **QA-G4-04** | Approval replay prevention | Task approved and executed | Repeat approve call with identical token | Rejected as replay; task not re-executed | Rejected with "replay" error; status remains intact | `test_g4_04_approval_replay_prevention` | **PASSED** |
| **QA-G4-05** | Expired approval rejection | Task created > 15 minutes ago | Call `orc.approve(...)` with token | Rejected due to 15-minute expiration window | Rejected with "expired" error; task not executed | `test_g4_05_rejection_of_expired_approval` | **PASSED** |
| **QA-G4-06** | Hash invalidation on subject change | Original draft created and hashed | Change subject text | Hash recomputation produces different SHA-256 | Digest differs, preventing payload tampering | `test_g4_06_approval_digest_invalidation_on_subject_change` | **PASSED** |

---

### Group 5: Provider Execution and AppleScript Integration

| Test ID | Scenario | Preconditions | Execution Steps | Expected Result | Actual Result | Evidence Reference | Status |
|:---|:---|:---|:---|:---|:---|:---|:---:|
| **QA-G5-01** | Apple Mail dry-run send | MailAutomation dry_run=True | Call `send_mail(recipient, subject, body)` | Record appended to `_sent_records`, no external side effects | Success recorded with dry_run flag | `test_g5_01_apple_mail_dry_run_execution` | **PASSED** |
| **QA-G5-02** | Sent mailbox verification | Sent record in registry | Call `verify_mail_sent(recipient, subject)` | Returns `True` confirming presence in Sent records | Verification succeeded | `test_g5_02_sent_mail_verification` | **PASSED** |
| **QA-G5-03** | Provider error handling | Provider mocks AppleScript failure | Call `orc.approve(...)` | Task transitions to `FAILED`, does not report false completion | Task status is `FAILED` with provider error message | `test_g5_03_provider_error_handling_marks_failure` | **PASSED** |
| **QA-G5-04** | No blind retries on failure | Provider mocks transient timeout | Call `orc.approve(...)` | Execution attempt occurs exactly once; no automated loop | Provider called exactly 1 time; no blind retry | `test_g5_04_no_blind_retry_on_uncertain_failure` | **PASSED** |

---

### Group 6: Task State, Persistence & Crash Recovery

| Test ID | Scenario | Preconditions | Execution Steps | Expected Result | Actual Result | Evidence Reference | Status |
|:---|:---|:---|:---|:---|:---|:---|:---:|
| **QA-G6-01** | Rehydration of sent mail (BUG-03 Fix) | Task interrupted in `EXECUTING`; mail sent | Restart orchestrator and rehydrate | Sent record found, task reconciled to `COMPLETED` | Task successfully reconciled to `COMPLETED` | `test_g6_01_rehydration_of_interrupted_executing_task_reconciles_sent_mail` | **PASSED** |
| **QA-G6-02** | Rehydration of unsent mail | Task interrupted in `EXECUTING`; mail NOT sent | Restart orchestrator and rehydrate | Mail not in Sent box; task set to `NEEDS_ATTENTION` | Task marked `NEEDS_ATTENTION`, no duplicate send | `test_g6_02_rehydration_of_unsent_mail_marks_needs_attention` | **PASSED** |
| **QA-G6-03** | SQLite optimistic concurrency | Task at state_version 2 | Attempt concurrent update with stale expected_version=1 | SQLite rejects write and raises `ConcurrencyError` | `ConcurrencyError` raised; update rejected | `test_g6_03_optimistic_concurrency_version_conflict_prevention` | **PASSED** |
| **QA-G6-04** | Non-primitive serialization (BUG-04 Fix) | Task with MagicMock/non-primitive result | Call `task_store.save_task(task)` | No `TypeError: not JSON serializable`; stores safely | String coercion applied; stored and retrieved cleanly | `test_g6_04_serialization_of_non_primitive_results` | **PASSED** |

---

### Group 7: Multi-Turn Clarification, Edits & Rejection

| Test ID | Scenario | Preconditions | Execution Steps | Expected Result | Actual Result | Evidence Reference | Status |
|:---|:---|:---|:---|:---|:---|:---|:---:|
| **QA-G7-01** | Multi-turn draft edit | Pending draft created | `orc.chat("change subject to Urgent Update")` | Draft updated in memory and persistence; hash recomputed | Subject updated to "urgent update"; pending action updated | `test_g7_01_multi_turn_draft_edit` | **PASSED** |
| **QA-G7-02** | Multi-turn explicit rejection | Pending draft created | `orc.chat("no, do not send that email")` | Pending draft discarded, task marked `CANCELED` | Draft cleared; task status `canceled` | `test_g7_02_multi_turn_explicit_rejection` | **PASSED** |
| **QA-G7-03** | Affirmative confirmation turn | Pending draft created | `orc.chat("yes, send it")` | Pending draft approved and executed; marked `COMPLETED` | Action executed; task status `completed` | `test_g7_03_confirm_send_via_affirmative_turn` | **PASSED** |
| **QA-G7-04** | Missing body clarification turn | Task in `NEED_INFO` (no body) | `orc.chat("the body should be welcome to the team")` | Body incorporated, task transitions to `WAITING_APPROVAL` | Status transitions to `waiting_approval` with full approval card | `test_g7_04_clarification_turn_resolves_missing_info` | **PASSED** |

---

### Group 8: Multilingual and Cross-Lingual Mail

| Test ID | Scenario | Preconditions | Execution Steps | Expected Result | Actual Result | Evidence Reference | Status |
|:---|:---|:---|:---|:---|:---|:---|:---:|
| **QA-G8-01** | Hindi email drafting | Orchestrator initialized | `orc.chat("user@test.com को ईमेल भेजो कि कल मीटिंग 10 बजे है")` | Command: `send_mail`, recipient: `user@test.com`, status: `waiting_approval` | Extracted recipient, Indic body parsed, status `waiting_approval` | `test_g8_01_hindi_email_drafting` | **PASSED** |
| **QA-G8-02** | Kannada email drafting | Orchestrator initialized | `orc.chat("user@test.com ಗೆ ನಾಳೆ ಸಭೆ ಇದೆ ಎಂದು ಇಮೇಲ್ ಕಳುಹಿಸಿ")` | Command: `send_mail`, recipient: `user@test.com`, status: `waiting_approval` | Extracted recipient, Indic body parsed, status `waiting_approval` | `test_g8_02_kannada_email_drafting` | **PASSED** |
| **QA-G8-03** | Tamil email drafting | Orchestrator initialized | `orc.chat("user@test.com க்கு நாளை கூட்டம் என்று மின்னஞ்சல் அனுப்பு")` | Command: `send_mail`, recipient: `user@test.com`, status: `waiting_approval` | Extracted recipient, Indic body parsed, status `waiting_approval` | `test_g8_03_tamil_email_drafting` | **PASSED** |
| **QA-G8-04** | Telugu email drafting | Orchestrator initialized | `orc.chat("user@test.com కు రేపు మీటింగ్ ఉంది అని ఈమెయిల్ పంపండి")` | Command: `send_mail`, recipient: `user@test.com`, status: `waiting_approval` | Extracted recipient, Indic body parsed, status `waiting_approval` | `test_g8_04_telugu_email_drafting` | **PASSED** |
| **QA-G8-05** | Multilingual cancellation | Pending Hindi draft | `orc.chat("इसे मत भेजो")` | Negation recognized in Hindi; pending action canceled | Pending action discarded; task status `canceled` | `test_g8_05_multilingual_cancellation` | **PASSED** |

---

### Group 9: Security, Privacy & Injection Prevention

| Test ID | Scenario | Preconditions | Execution Steps | Expected Result | Actual Result | Evidence Reference | Status |
|:---|:---|:---|:---|:---|:---|:---|:---:|
| **QA-G9-01** | Prompt injection sanitization | EmailEngine initialized | Call `sanitize_untrusted_email_content` with system directive injection | Directive replaced with `[FILTERED UNTRUSTED DIRECTIVE]`, override prevented | Untrusted directives neutralized | `test_g9_01_prompt_injection_sanitization` | **PASSED** |
| **QA-G9-02** | Sensitive file attachment blocking (BUG-02 Fix) | Orchestrator initialized | `orc.chat("send email to user@test.com with attachment /etc/passwd saying here is the file")` | Blocked immediately with security violation; task `FAILED` | Security check blocks system path attachment; status `failed` | `test_g9_02_sensitive_file_attachment_blocking` | **PASSED** |
| **QA-G9-03** | Audit log redaction | TaskStore with audit event | Log event with passwords/secrets in metadata | Metadata sanitized; secrets redacted from SQLite logs | Secret tokens omitted/redacted from stored JSON | `test_g9_03_audit_log_redaction_and_evidence` | **PASSED** |

---

### Group 10: Desktop Frontend and IPC Safety

| Test ID | Scenario | Preconditions | Execution Steps | Expected Result | Actual Result | Evidence Reference | Status |
|:---|:---|:---|:---|:---|:---|:---|:---:|
| **QA-G10-01** | Valid session token auth | FastAPI auth subsystem | Call `verify_session_token(secret)` with active session secret | Authentication verified; returns `True` | Token matched and authorized | `test_g10_01_valid_session_token_authentication` | **PASSED** |
| **QA-G10-02** | Invalid session token auth | FastAPI auth subsystem | Call `verify_session_token("invalid_token")` | Rejected; returns `False` | Unauthorized token denied | `test_g10_02_invalid_session_token_rejection` | **PASSED** |
| **QA-G10-03** | Desktop state synchronization (BUG-07 Fix) | Orchestrator + TaskStore | Approve email via orchestrator interface | Task and TaskStore state synchronized to `COMPLETED` | SQLite store updated synchronously to `COMPLETED` | `test_g10_03_approval_endpoint_state_synchronization` | **PASSED** |

---

## 3. Live External Execution Gate Assessment

In strict accordance with Safety Rule #4 (*"Never send a real email without explicit authorization for that specific test"*) and Rule #5 (*"Never use an actual third-party recipient for testing"*):
- Real external Apple Mail / SMTP transmission was **NOT EXECUTED** in automated passes.
- All provider integrations operated with dry-run protection and controlled mocking.
- Live testing procedures, authorization gates, and local verification instructions are defined in [`docs/MAIL_AUTOMATION_LIVE_TEST_CHECKLIST.md`](./MAIL_AUTOMATION_LIVE_TEST_CHECKLIST.md).

