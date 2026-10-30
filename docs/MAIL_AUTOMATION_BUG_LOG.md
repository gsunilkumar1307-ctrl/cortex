# CORTEX AGENT — MAIL AUTOMATION BUG LOG

**Date:** October 28, 2026  
**Auditor:** Cortex QA & Security Audit Team  
**Scope:** Email Engine, Orchestrator, Task Store, Apple Mail Provider, Frontend Approval UI  

---

## Index of Remediated Defects

| Bug ID | Severity | Subsystem | Description | Status |
|:---|:---|:---|:---|:---:|
| **BUG-01** | **P0 (Blocker)** | Orchestrator NLU | Negation phrases with "send" (e.g. "do not send") triggered email send | **REMEDIATED** |
| **BUG-02** | **P1 (Critical)** | Email Engine / Security | Arbitrary system file attachments allowed (/etc/passwd, .env, SSH keys) | **REMEDIATED** |
| **BUG-03** | **P1 (Critical)** | Crash Recovery | Rehydration check failed due to missing `.provider` attribute; tasks stuck | **REMEDIATED** |
| **BUG-04** | **P1 (Critical)** | Persistence Store | SQLite crashed on non-primitive objects (`TypeError: MagicMock not serializable`) | **REMEDIATED** |
| **BUG-05** | **P2 (Major)** | Email Engine NLU | Subject parsing extracted trailing "and" or failed on subject-only commands | **REMEDIATED** |
| **BUG-06** | **P2 (Major)** | Recipient Resolver | Multiple comma-separated recipients silently truncated to first recipient | **REMEDIATED** |
| **BUG-07** | **P3 (Minor)** | Desktop App.jsx | Asynchronous React state race condition caused stale approval hash on save & send | **REMEDIATED** |
| **BUG-08** | **P2 (Major)** | Capabilities / Mail Actions | Missing `import re` caused `NameError` during AppleScript string construction | **REMEDIATED** |
| **BUG-09** | **P0 (Critical)** | Core Intent Routing & Execution | Cortex typed user instructions into Apple Mail via keystrokes instead of composing emails | **REMEDIATED** |

---

## Detailed Bug Reports

### BUG-01: Critical Approval Bypass via Negation Phrase

- **Severity:** P0 — Blocker (Security / Authorization Bypass)
- **Subsystem:** `backend/agent/orchestrator.py`
- **Symptom:** When an email draft was pending user confirmation, if the user responded with `"do not send"`, `"never send it"`, `"don't send"`, or Indic equivalents (`"इसे मत भेजो"`, `"ಇದನ್ನು ಕಳಿಸಬೇಡ"`), the system sent the email instead of canceling it.
- **Root Cause:**
  1. `_is_explicit_cancellation` checked only narrow keywords like `cancel`, `discard`, `abort`.
  2. In `orchestrator.py` line 731, `is_confirm` evaluated regex `\b(yes|send\s+it|approve|send...)\b`.
  3. The word `"send"` in `"do not send"` matched the confirmation regex, triggering `approve()` and executing the irreversible send against the user's explicit directive!
- **Remediation:**
  1. Added broad negation phrases to `_is_explicit_cancellation()` covering English and all 4 Indic languages:
     - English: `"do not send"`, `"don't send"`, `"never send"`, `"stop"`, `"halt"`, `"reject"`
     - Hindi: `"मत भेजो"`, `"नहीं भेजो"`, `"रद्द करो"`, `"मत भेजना"`
     - Kannada: `"ಕಳಿಸಬೇಡ"`, `"ಕಳುಹಿಸಬೇಡಿ"`, `"ರದ್ದುಮಾಡು"`
     - Tamil: `"அனுப்பாதே"`, `"அனுப்ப வேண்டாம்"`, `"ரத்து செய்"`
     - Telugu: `"పంపవద్దు"`, `"పంపకండి"`, `"రద్దు చేయండి"`
  2. Added an explicit `has_negation` guard in `orchestrator.py` line 740 preventing `is_confirm` from being true whenever any negation particle is present.
- **Verification Evidence:** `test_g1_10_negation_prevents_accidental_confirmation` and `test_g8_05_multilingual_cancellation` pass.

---

### BUG-02: Sensitive File System Information Disclosure via Attachments

- **Severity:** P1 — Critical (Data Exfiltration / Security Boundary)
- **Subsystem:** `backend/agent/orchestrator.py`, `backend/agent/email_engine.py`
- **Symptom:** An email draft request could attach critical system and credential files (e.g. `/etc/passwd`, `.env`, `.session_secret`, `~/.ssh/id_rsa`).
- **Root Cause:** Attachment validation only checked `if not os.path.exists(a)`. If the file existed on the host filesystem, it was accepted into the draft.
- **Remediation:**
  Implemented `is_sensitive_attachment()` validator in `orchestrator.py` and `email_engine.py` blocking:
  - System files: `/etc/passwd`, `/etc/shadow`, `/etc/sudoers`, `/etc/hosts`
  - Secrets & environments: `.env`, `.env.local`, `.session_secret`
  - Cryptographic keys: `.ssh`, `id_rsa`, `id_ed25519`, `*.pem`, `*.key`
  Any attempt to attach these files immediately fails the task with a security violation.
- **Verification Evidence:** `test_g9_02_sensitive_file_attachment_blocking` passes.

---

### BUG-03: Crash Recovery Failure on Rehydration of Sent Mail

- **Severity:** P1 — Critical (Durability / State Invariant Violation)
- **Subsystem:** `backend/agent/orchestrator.py` (`_rehydrate_tasks`)
- **Symptom:** When Cortex Agent restarted after a crash while executing an email send, tasks where the email had already been delivered were never reconciled to `COMPLETED` and remained stuck in `NEEDS_ATTENTION`.
- **Root Cause:** Line 292 checked `hasattr(mail_auto, "provider")`. `MailAutomation` does not have a `.provider` attribute; it implements `verify_mail_sent` directly on `MailAutomation` and `DeviceAutomation`.
- **Remediation:**
  Updated `_rehydrate_tasks()` to verify sent status through all standard interfaces:
  `hasattr(mail_auto, "verify_mail_sent")`, `hasattr(mail_auto, "verify_message_sent")`, and `mail_auto.provider`.
- **Verification Evidence:** `test_g6_01_rehydration_of_interrupted_executing_task_reconciles_sent_mail` passes.

---

### BUG-04: Relational SQLite Serialization Crash on Non-Primitive Values

- **Severity:** P1 — Critical (Crash / Persistence Failure)
- **Subsystem:** `backend/persistence/task_store.py`, `backend/persistence/encrypted_store.py`
- **Symptom:** `save_task()` or `update_action_attempt()` crashed with:
  `TypeError: Object of type MagicMock is not JSON serializable`
  and SQLite threw `Error binding parameter 11 - probably unsupported type`.
- **Root Cause:** `json.dumps()` lacked `default=str`, and direct parameter tuples passed objects that SQLite could not bind natively.
- **Remediation:**
  Added `default=str` to all `json.dumps` calls in `task_store.py` and `encrypted_store.py`. Explicitly coerced SQLite parameter bindings (`str(task.result) if task.result is not None else None`).
- **Verification Evidence:** `test_g6_04_serialization_of_non_primitive_results` passes.

---

### BUG-05: NLU Conjunction Bleed and Subject-Only Failure

- **Severity:** P2 — Major (NLU Inaccuracy)
- **Subsystem:** `backend/agent/email_engine.py` (`extract_command_and_content`)
- **Symptom:**
  - `"send email to X with subject Project Report and body hello"` produced subject `'Project Report and'`.
  - `"send email to X with subject Annual Review"` (without body) extracted empty subject and put the subject into body.
- **Root Cause:**
  - Regex group matched trailing conjunction `"and"`.
  - Missing pattern for commands specifying subject without body.
- **Remediation:**
  - Added trailing conjunction stripping: `subj = re.sub(r"\s+\band\b\s*$", "", subj, flags=re.IGNORECASE)`.
  - Added Pattern 1B matching `with subject <subj>` when no body is provided.
- **Verification Evidence:** `test_g1_02_subject_and_body_extraction` and `test_g1_05_instruction_with_subject_only` pass.

---

### BUG-06: Truncation of Multiple Comma-Separated Recipients

- **Severity:** P2 — Major (Functional Defect)
- **Subsystem:** `backend/agent/recipient_resolver.py`, `backend/capabilities/mail_actions.py`
- **Symptom:** Prompts with multiple recipients (e.g. `"send email to alice@example.com, bob@example.com"`) discarded Bob and only sent to Alice.
- **Root Cause:** `recipient_resolver.resolve()` used `re.search` on the first email match and returned immediately. The AppleScript generator also added only a single recipient line.
- **Remediation:**
  - Updated `recipient_resolver.py` to extract all direct email matches via `re.findall` and return comma-separated recipients.
  - Updated `mail_actions.py` and `apple_mail_provider.py` to iterate over split recipients and append `make new to recipient at end of to recipients` for each address.
- **Verification Evidence:** `test_g2_03_multiple_recipient_resolution` passes.

---

### BUG-07: Desktop React Async State Stale Hash Race Condition

- **Severity:** P3 — Minor (UI / UX Friction)
- **Subsystem:** `apps/desktop/src/App.jsx`
- **Symptom:** Clicking "Save & Send" in the desktop approval card caused a `400: Approval hash mismatch` error.
- **Root Cause:** `handleSaveAndApprove` called `handleSaveEdit` followed by `decide(true)`. Because React state updates are asynchronous, `decide()` read `task.params.approval_hash` from the current render closure (the old hash before edit), which did not match the newly calculated hash.
- **Remediation:**
  Modified `decide(approved, explicitHash = null)` in `App.jsx` to accept an explicit hash override, and updated `handleSaveAndApprove` to forward `newHash` directly into `decide(true, newHash)`.
- **Verification Evidence:** Desktop production build (`npm run build --prefix apps/desktop`) built cleanly; `test_g10_03_approval_endpoint_state_synchronization` passes.

---

### BUG-08: Missing `re` Import in `mail_actions.py`

- **Severity:** P2 — Major (Runtime Crash in Non-Dry-Run Execution)
- **Subsystem:** `backend/capabilities/mail_actions.py`
- **Symptom:** `test_email_production_hardening.py` failed with `NameError: name 're' is not defined` when executing `send_mail` with multiple recipients.
- **Root Cause:** `to_recipients = [r.strip() for r in re.split(r"[,;]|\band\b", recipient) if r.strip()]` called `re.split` without `import re` at the top of the file.
- **Remediation:** Added `import re` to module imports in `backend/capabilities/mail_actions.py`.
- **Verification Evidence:** Full backend suite (342 tests) passed cleanly with 0 errors.

---

### BUG-09: Cortex Typed User Instructions via Keystrokes Instead of Composing Emails

- **Severity:** P0 — Critical (Core Intent Routing & Execution Defect)
- **Subsystem:** `backend/core/contracts.py`, `backend/agent/orchestrator.py`, `backend/agent/email_engine.py`, `backend/capabilities/device_actions.py`
- **Symptom:**
  When prompted with a multi-turn email drafting request:
  1. `send mail to gsunilkumar1307@gmail.com`
  2. `Write a polite email asking whether the project presentation deadline can be extended by two days. Do not invent a reason.`
  Cortex responded with `"Typed text."` and used desktop AppleScript keystroke emulation (`_type_text`) to paste the raw user instruction into Apple Mail, incorrectly reporting `Task executed and verified successfully.` In informational emails, raw instruction wrappers (`Inform them that...`) also leaked into the recipient body.
- **Root Cause:**
  1. In `contracts.py`: Generic text typing (`text.startswith(("type ", "write ", ...))`) was evaluated *before* Mail Automation intent matching. When the prompt started with `"Write a polite email..."`, it was classified as `TaskCommand.TYPE_TEXT`.
  2. In `orchestrator.py`: `_is_unrelated_turn()` checked `cmd = command_from_intent(text)`. Seeing `TaskCommand.TYPE_TEXT`, it classified the user's body input as an unrelated command, aborting the pending email draft turn and immediately dispatching `_type_text`.
  3. In `email_engine.py`: Missing Pattern 0C for drafting prompts without explicit recipients, regex delimiters consumed question indicators (`asking whether`), and there was no converter to translate indirect meta-directives into recipient-facing direct phrasing while stripping constraint instructions (`do not invent a reason`).
- **Remediation:**
  1. Priority re-ordering in `contracts.py`: Prioritized Mail Automation (`DRAFT_MAIL`, `SEND_MAIL`) before generic text typing. Isolated `TYPE_TEXT` to non-email instructions.
  2. Orchestrator guard in `_is_unrelated_turn()`: Added a priority guard ensuring that while in `waiting_for_body` or `waiting_for_edit`, conversational input is strictly processed as email content unless an explicit desktop control command (e.g. `open_app`, `shutdown`, `calculate`) is requested.
  3. Structured email composition pipeline: Implemented `convert_instruction_to_recipient_content()` in `email_engine.py` to extract constraints (`no_invented_reason`), extract tones (`polite`, `formal`), and convert indirect phrasing into direct questions (`Could the project presentation deadline please be extended by two days?`).
  4. Capability isolation: Added explicit `create_email_draft()` in `device_actions.py` and `mail_actions.py` strictly decoupled from keystroke typing.
  5. Diagnostic logging: Added audit logging on capability selection with sensitive parameters (`body`, `formatted_body`, credentials) redacted.
- **Verification Evidence:** `tests/test_instruction_typing_bug_regression.py` passes all 7 tests covering Scenarios 1 through 5, single-turn drafting, and diagnostic logging.

