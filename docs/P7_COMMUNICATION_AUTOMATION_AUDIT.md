# CORTEX AGENT — P7 COMMUNICATION AUTOMATION COMPREHENSIVE AUDIT
## Apple Mail & WhatsApp Desktop Automation Architecture, Safety & Live macOS Readiness

**Audit Date:** November 18, 2026  
**Auditor:** Autonomous Systems & Security Assurance (Cortex Agent Architecture Team)  
**Target Codebase:** Cortex Agent (`backend/`, `tests/`, `scripts/`, `Codex/2026-06-17/files-mentioned-by-the-user-cortex`)  
**Scope:** Architecture Inspection, BaseTool Lifecycle, ToolRegistry, AutonomousPlanner, ExecutionEngine, PolicyEngine, TaskStore, Multi-Turn Rehydration, Apple Mail Provider, WhatsApp Desktop Adapter, Security & Cryptographic Approvals, Live macOS Environment Readiness  
**Host Environment:** macOS 27.0.1 (Darwin 27.0.0 arm64, Apple Silicon)  
**Deliverable Document:** `docs/P7_COMMUNICATION_AUTOMATION_AUDIT.md`  

---

## FINAL VERDICT

### **CONDITIONALLY READY — SPECIFIC BLOCKERS**

> **Verdict Rationale:**  
> Cortex possesses a robust, mathematically sound, and tamper-evident security core: cryptographic SHA-256 draft-payload binding, single-use approval token consumption in SQLite WAL, strict approval gates, and a native compiled Swift accessibility helper (`cortex_screen_helper`).
>
> However, **P7 cannot be certified as immediately ready for production autonomous deployment** due to **four critical architectural and verification blockers**:
> 1. **Mail Safe-Test Domain Interception & In-Memory Verification Bypass (P0):** `MailAutomation.send_mail` and `verify_mail_sent` intercept test domains (`@example.com`, `@test.com`, `@cortex.internal`) and return synthetic success records from an in-memory list (`_sent_records`) without ever invoking AppleScript dispatch or validating the physical Apple Mail `Sent` mailbox.
> 2. **WhatsApp Hardcoded Accessibility UI Path Fragility (P0):** `WhatsAppDesktopAdapter` relies on hardcoded AX element indices (`0/0/0/0/1/2/1/0/2`) for composer focusing in WhatsApp Catalyst. Any UI hierarchy refactor or localized update breaks element discovery.
> 3. **Unbounded AppleScript Sent Mailbox Iteration (P1):** Live verification of sent emails executes an unbounded `repeat with m in (messages of sent mailbox)` loop in AppleScript without date bounding or batching, triggering timeout failures on mailboxes with large message counts.
> 4. **Architectural Duplication & Monolithic Orchestration (P1):** Apple Mail automation is duplicated across `capabilities/mail_actions.py` and `integrations/email/apple_mail_provider.py`. Orchestrator contains over 7,400 lines where email and WhatsApp handling are fragmented across disparate switch-cases rather than running on a unified, supervised communication engine.
>
> Remediation of these specific blockers following the implementation sequence in Section 9 will elevate Cortex to **FULL PRODUCTION READINESS**.

---

## 1. EXISTING ARCHITECTURE — INSPECTION & SUBSYSTEM AUDIT

### 1.1 BaseTool Lifecycle Contract (`backend/tools/base.py`)
Cortex enforces an empirical four-stage execution lifecycle on all universal tools:
```
┌───────────┐      ┌───────────┐      ┌──────────┐      ┌───────────┐
│  EXECUTE  │ ───► │  OBSERVE  │ ───► │  VERIFY  │ ───► │  RECOVER  │
└───────────┘      └───────────┘      └──────────┘      └───────────┘
```
1. `execute(inputs, context)`: Interacts with external system to perform action. Returns `ExecutionResult(step_id, ok, message, error, data, duration_ms)`.
2. `observe(inputs, execution_result)`: Inspects real-world system state post-execution to collect empirical facts. Returns `Observation(target, state_data, raw_output, evidence_type)`.
3. `verify(inputs, observation, execution_result)`: Evaluates independent evidence against expected outcome. Never relies on `execution_result.ok` alone. Returns `VerificationResult(verified, confidence, evidence, uncertainty_reason)`.
4. `recover(inputs, error, attempt)`: Provides safe recovery or escalation. For irreversible operations (`is_irreversible=True`), automatic retries are strictly prohibited (`can_retry=False, strategy="escalate"`).

- **Implementation in Apple Mail:** `MailTool` (`backend/tools/mail_tool.py`) implements this contract. In `recover()`, if sending mail is uncertain, it checks the Sent mailbox before taking any action, preventing duplicate sends.
- **Implementation in WhatsApp:** `WhatsAppAdapter` (`backend/adapters/whatsapp_adapter.py`) implements `ApplicationAdapter` and is wrapped by `AdapterToolWrapper` (`backend/adapters/base.py`) to expose the identical `BaseTool` lifecycle to the `ExecutionEngine`.

### 1.2 ToolRegistry (`backend/tools/registry.py`)
- Centralized catalog registering both universal tool definitions (`ToolDefinition`) and concrete `BaseTool` instances.
- Concrete instances registered at startup:
  - `mail_tool`: `MailTool(mail_automation=self.automation.mail)`
  - `whatsapp_adapter`: `AdapterToolWrapper(WhatsAppAdapter, "whatsapp_adapter")`
  - `notes_adapter`, `file_tool`, `desktop_tool`, `browser_tool`, `web_search_tool`
- **Architectural Gap:** `mail_tool` is registered as a standalone `BaseTool`, whereas `whatsapp_adapter` is registered as an `ApplicationAdapter` wrapped in `AdapterToolWrapper`. They do not share a common communication base class.

### 1.3 AutonomousPlanner (`backend/agent/planner.py`)
- Decomposes high-level natural language goals into a structured `Plan` containing `PlanStep` elements.
- **Current Behavior for Email:**
  - `TaskCommand.DRAFT_MAIL` / `TaskCommand.SEND_MAIL`: Generates a **single-step** plan pointing to `mail_tool` with action `draft_mail` or `send_mail`.
- **Current Behavior for WhatsApp:**
  - `TaskCommand.DRAFT_WHATSAPP` / `TaskCommand.SEND_WHATSAPP` / `TaskCommand.SEND_MESSAGE`: Generates a **single-step** plan pointing to `whatsapp_adapter` with action `prepare_draft` or `send_message`.
- **Architectural Gap:** The planner treats communication dispatch as an atomic single-step execution rather than planning a verifiable multi-stage pipeline (e.g. Ensure Application Foreground -> Resolve Recipient Identity -> Verify Composer Text -> Obtain Approved Dispatch -> Confirm Delivery Evidence).

### 1.4 ExecutionEngine (`backend/agent/execution_engine.py`)
- Core execution loop enforcing:
  - Idempotency key evaluation before executing irreversible steps.
  - Independent observation and verification.
  - Safe recovery loop (`attempt <= max_retries`).
  - Mandatory Recovery Safety: Never converts an uncertain outcome to success without positive independent proof; prevents resuming canceled tasks.
- Works reliably for both `mail_tool` and `whatsapp_adapter`.

### 1.5 PolicyEngine (`backend/agent/policy.py`)
- Centralized safety rules, risk classification, and duplicate-action protection:
  - `TaskCommand.DRAFT_MAIL`: `RiskLevel.LOW`, `requires_approval=False`, `is_irreversible=False`
  - `TaskCommand.SEND_MAIL`: `RiskLevel.HIGH`, `requires_approval=True`, `is_irreversible=True`
  - `TaskCommand.DRAFT_WHATSAPP`: `RiskLevel.LOW`, `requires_approval=False`, `is_irreversible=False`
  - `TaskCommand.SEND_WHATSAPP`: `RiskLevel.HIGH`, `requires_approval=True`, `is_irreversible=True`
  - `TaskCommand.SEND_MESSAGE`: `RiskLevel.HIGH`, `requires_approval=True`, `is_irreversible=True`
- Idempotency hashing: `compute_idempotency_key()` derives SHA-256 digest from normalized parameters.
  - For Email: `send_mail:{recipient}:{subject}:{body}`
  - For WhatsApp: `send_whatsapp:{recipient}:{phone}:{body}:{channel}`
- **Architectural Blocker:** The PolicyEngine maintains its duplicate execution registry (`_executed_actions`) **in-memory only** (`dict`). If Cortex restarts during an interrupted send, in-memory duplicate protection is lost unless recovered from `TaskStore`.

### 1.6 TaskStore & Persistence (`backend/persistence/task_store.py`)
- Authoritative relational SQLite persistence with WAL journaling, foreign keys, and atomic versioned migrations.
- Tables:
  - `tasks`: Core task attributes, status, state_version, approval_hash, params_json.
  - `task_steps`: Ordered plan steps and execution state.
  - `approvals`: Cryptographic approval records with 15-minute expiration and atomic single-use consumption (`consume_approval`).
  - `action_attempts`: Durable side-effect intent logging before and after physical dispatch.
  - `whatsapp_send_attempts`: Durable capability-level attempt logging for WhatsApp.
  - `audit_events`: Tamper-evident structured metadata-first event trail.
- **Architectural Gap:** `whatsapp_send_attempts` exists, but there is NO dedicated `mail_send_attempts` table. Email sends rely solely on `action_attempts`.

### 1.7 Multi-Turn Context & Rehydration (`backend/agent/orchestrator.py`)
- State machine tracks active pending actions via `self.pending_action` and `self._pending_tasks`.
- Step types supported:
  - `waiting_for_recipient`: Prompt user when recipient is absent or ambiguous.
  - `waiting_for_recipient_disambiguation`: Prompt user when multiple contacts match.
  - `waiting_for_body`: Prompt user for missing message content or email purpose.
  - `confirm_send` / `confirm_direct_number`: Supervised approval gate before dispatch.
  - `draft_only_review`: Review card for draft-only requests (prevents accidental send).
- Crash Recovery (`_rehydrate_tasks()`):
  - On orchestrator initialization, queries active non-terminal tasks from `task_store.list_active_tasks()`.
  - Reconstructs pending action structures and revalidates whether interrupted tasks were already delivered.

### 1.8 Native macOS Automation & Helper Architecture
- **Apple Mail:** Uses AppleScript via `/usr/bin/osascript`. Does not use native binaries.
- **WhatsApp Desktop:** Uses a hybrid architecture:
  1. `open -a WhatsApp` and system URL scheme `whatsapp://send?phone=...` for navigation.
  2. Native Swift compiled helper `backend/native/cortex_screen_helper` (`cortex_screen_helper action <pid> <path> AXPress`) for direct accessibility element manipulation in the Catalyst UI.
  3. AppleScript System Events for window detection and final keystroke emission (`key code 36`).
- **MCPManager:** Configured exclusively for `playwright`, `fetch`, and `filesystem`. Neither Mail nor WhatsApp currently runs through MCP.

---

## 2. APPLE MAIL CAPABILITY MATRIX

### Detailed Evaluation of the 14 Real Workflows

| # | Workflow Operation | Classification | Source File & Class/Function | Evidence & Technical Findings |
|---|---|---|---|---|
| **1** | **Launch Apple Mail** | **Fully implemented and live-tested** | `backend/capabilities/mail_actions.py`<br>`MailAutomation.draft_mail`<br>`backend/capabilities/device_actions.py`<br>`DeviceAutomation.open_app` | AppleScript executes `tell application "Mail" activate`. Successfully activates `/System/Applications/Mail.app`. Empirically verified in `scripts/test_live_apple_mail_workflow.py`. |
| **2** | **Identify intended recipient** | **Fully implemented and live-tested** | `backend/agent/recipient_resolver.py`<br>`RecipientResolver.resolve` | Direct email extraction via regex `[\w\.-]+@[\w\.-]+\.\w+`. Normalizes name from query prefix. Tested in `test_task6_apple_mail.py::test_01`. |
| **3** | **Search & select correct recipient** | **Fully implemented and live-tested** | `backend/agent/recipient_resolver.py`<br>`RecipientResolver._search_mailbox`<br>`_search_contacts` | Searches connected inbox messages and directory. If multiple candidates exist, transitions to `waiting_for_recipient_disambiguation` with numbered prompt. Tested in `test_task6_apple_mail.py::test_02`. |
| **4** | **Create new email** | **Fully implemented and live-tested** | `backend/capabilities/mail_actions.py`<br>`MailAutomation.draft_mail` | AppleScript constructs `make new outgoing message with properties {subject:..., content:..., visible:true}` and calls `save newMsg`. Real draft created in Apple Mail. |
| **5** | **Ask user for email purpose** | **Fully implemented and live-tested** | `backend/agent/orchestrator.py`<br>`CortexOrchestrator.chat`<br>`backend/agent/email_engine.py`<br>`is_ambiguous_email_intent` | When command is `DRAFT_MAIL` or `SEND_MAIL` without body, transitions to `NEED_INFO` (`waiting_for_body`) and responds asking for purpose/body. |
| **6** | **Generate suitable draft** | **Fully implemented and live-tested** | `backend/agent/email_engine.py`<br>`ProfessionalEmailEngine.compose_email`<br>`run_quality_control` | Analyzes relationship, role, and formality. Eliminates AI filler and placeholder brackets. Grounded against known facts. |
| **7** | **Populate recipient, subject & body** | **Fully implemented and live-tested** | `backend/capabilities/mail_actions.py`<br>`MailAutomation.draft_mail` | Script populates `to recipients`, `subject`, and `content`. Safely escapes quotes, null bytes, and newlines via `_apple_string()`. |
| **8** | **Conversational draft editing** | **Fully implemented and live-tested** | `backend/agent/orchestrator.py`<br>`CortexOrchestrator.chat` (lines 1879–1940)<br>`MailAutomation.update_draft` | Follow-ups ("make it shorter", "more formal", "change subject to...") update `EmailDraft`, invoke `update_draft`, purge previous draft, and recompute approval hash. |
| **9** | **Handle CC and BCC** | **Implemented but not live-tested** | `backend/capabilities/mail_actions.py`<br>`MailAutomation.draft_mail` (lines 255–260)<br>`backend/agent/email_engine.py`<br>`EmailDraft.canonicalize` | Script constructs `make new cc recipient` and `make new bcc recipient`. Supported in data models and hashing. Unit-tested; not exercised in live UI acceptance script. |
| **10** | **Attach files when requested** | **Implemented but not live-tested** | `backend/capabilities/mail_actions.py`<br>`MailAutomation.draft_mail` (lines 178, 261)<br>`backend/agent/orchestrator.py`<br>`is_sensitive_attachment` | Validates file existence. Strictly blocks security paths (`/etc/passwd`, `.env`, `.ssh`). Generates `make new attachment with properties {file name:(POSIX file ...)}`. Not live-tested with real files in Mail GUI. |
| **11** | **Display & verify complete draft** | **Fully implemented and live-tested** | `backend/agent/orchestrator.py`<br>`_format_approval_card`<br>`backend/capabilities/mail_actions.py`<br>`verify_draft_created` | Renders approval card with Recipient, Subject, Account, Body, and SHA-256 hash. Queries Apple Mail drafts mailbox to verify real draft existence. |
| **12** | **Explicit final approval** | **Fully implemented and live-tested** | `backend/agent/orchestrator.py`<br>`CortexOrchestrator.approve`<br>`backend/persistence/task_store.py`<br>`TaskStore.consume_approval` | Requires explicit user confirmation ("send it", "approve"). Rejects vague phrases ("looks good") and negations ("do not send"). Consumes single-use token from SQLite. Replays blocked. |
| **13** | **Send the message** | **Partially implemented (Bypassed in test/mock mode)** | `backend/capabilities/mail_actions.py`<br>`MailAutomation.send_mail` (lines 359–482) | AppleScript contains `tell newMsg ... send`. **BLOCKER:** Lines 416–434 define `is_safe_test`. In test runs or when recipient is `@example.com` / `@test.com`, it bypasses AppleScript, records to `_sent_records`, and deletes draft. True remote SMTP dispatch has never been executed in automated tests. |
| **14** | **Verify in Sent mailbox** | **Partially implemented / Flawed implementation** | `backend/capabilities/mail_actions.py`<br>`MailAutomation.verify_mail_sent` (lines 545–583) | **BLOCKER 1:** Step 1 checks in-memory `_sent_records` and returns `verified=True` immediately, masking whether message reached Mail.app.<br>**BLOCKER 2:** AppleScript queries `messages of sent mailbox` in an unbounded loop, hanging on large mailboxes.<br>**BLOCKER 3:** Does not verify recipient address in AppleScript, only subject. |

---

## 3. WHATSAPP CAPABILITY MATRIX

### Detailed Evaluation of the 13 Real Workflows

| # | Workflow Operation | Classification | Source File & Class/Function | Evidence & Technical Findings |
|---|---|---|---|---|
| **1** | **Launch WhatsApp** | **Fully implemented and live-tested** | `backend/adapters/whatsapp_adapter.py`<br>`WhatsAppAdapter.launch`<br>`backend/capabilities/whatsapp_actions.py`<br>`WhatsAppDesktopAdapter.is_whatsapp_running` | Detects running process via `pgrep -x WhatsApp`. If not running, launches via `open -a WhatsApp` and waits for window availability. Empirically tested in `test_whatsapp_live_execution.py::test_01`. |
| **2** | **Search for a contact** | **Fully implemented and live-tested** | `backend/agent/recipient_resolver.py`<br>`RecipientResolver.resolve_messaging_contact`<br>`backend/capabilities/whatsapp_actions.py`<br>`WhatsAppDesktopAdapter.search_visible_contacts` | Searches user-authorized contacts first. Queries visible UI via `Cmd+F` AppleScript inspection. Strictly rejects substring hallucination and unverified guessing. |
| **3** | **Disambiguate contacts** | **Fully implemented and live-tested** | `backend/agent/orchestrator.py`<br>`CortexOrchestrator.chat` (lines 2366–2415)<br>`RecipientResolver.resolve_messaging_contact` | Multiple matching contacts (e.g. Alex Morgan vs Alex Chen) return `MULTIPLE_MATCHES`. Orchestrator presents numbered list; user disambiguates by index or name. Tested in `test_task6_whatsapp.py::test_03`. |
| **4** | **Open intended conversation** | **Fully implemented and live-tested** | `backend/capabilities/whatsapp_actions.py`<br>`WhatsAppDesktopAdapter.open_conversation`<br>`observe_current_conversation` | Routes directly via `whatsapp://send?phone=<phone>`. Verifies active chat header via macOS accessibility tree (`\u200eMessages in chat with <Name/Phone>`). Tested on live Catalyst PID 6672. |
| **5** | **Ask for message content** | **Fully implemented and live-tested** | `backend/agent/orchestrator.py`<br>`CortexOrchestrator.chat` (lines 3273–3293)<br>`NEED_INFO` transition | When recipient is known but message body is missing, transitions task to `NEED_INFO` (`waiting_for_body`) and prompts user for message text. Tested in `test_task6_whatsapp.py`. |
| **6** | **Compose the message** | **Fully implemented and live-tested** | `backend/capabilities/whatsapp_actions.py`<br>`compose_whatsapp_message`<br>`WhatsAppDesktopAdapter.prepare_draft` | Formats message appropriately. Focuses native `AXTextArea` (`\u200eCompose message`) using `cortex_screen_helper action <pid> <path> AXPress`, clears field, and injects text via clipboard paste. Verified live. |
| **7** | **Edit message via follow-up** | **Partially implemented** | `backend/agent/orchestrator.py`<br>`CortexOrchestrator.chat` (lines 2752–2782) | Follow-up instructions adjusting tone/brevity reformat the seed text via `compose_whatsapp_message` and recompute the approval hash. **Gap:** Freeform semantic diffs (e.g. "change venue to Starbucks") are not parsed, and programmatic `edit_pending_draft` does not support WhatsApp. |
| **8** | **Display exact recipient & message** | **Fully implemented and live-tested** | `backend/capabilities/whatsapp_actions.py`<br>`format_whatsapp_approval_card`<br>`backend/agent/orchestrator.py` | Renders structured card with Recipient, Phone Number, Channel, Full Message Text, Contact Provenance Badge, and SHA-256 Approval Hash. |
| **9** | **Obtain explicit final approval** | **Fully implemented and live-tested** | `backend/agent/orchestrator.py`<br>`CortexOrchestrator.approve`<br>`backend/persistence/task_store.py`<br>`TaskStore.consume_approval` | Halts in `WAITING_APPROVAL`. User must confirm explicitly. Single-use token consumed atomically from SQLite. Replays blocked. Draft-only tasks cannot be sent. Tested in `test_task6_whatsapp.py::test_04, 05`. |
| **10** | **Send the message** | **Fully implemented and live-tested on macOS Catalyst** | `backend/capabilities/whatsapp_actions.py`<br>`WhatsAppDesktopAdapter.execute_send` | Validates single-use token. Re-validates that active window header still matches intended contact. Dispatches Return keystroke (`key code 36`) to WhatsApp process. Tested live on PID 6672. |
| **11** | **Verify sent in intended conversation** | **Partially implemented (UI-heuristic verification only)** | `backend/capabilities/whatsapp_actions.py`<br>`WhatsAppDesktopAdapter.execute_send`<br>`observe_current_conversation` | Re-inspects accessibility tree post-send to confirm: (1) Composer text is empty, (2) `AXButton` (`\u200eSend`) is removed. **Limitation:** WhatsApp Catalyst does not expose message bubbles or delivery checkmarks to macOS Accessibility. Real remote delivery cannot be confirmed via AX alone. |
| **12** | **Handle delays, interruptions & recovery** | **Partially implemented** | `backend/agent/orchestrator.py`<br>`_rehydrate_tasks`<br>`backend/persistence/task_store.py` | Tasks rehydrate from SQLite upon restart. Action attempts logged to database. **Gap:** Cold launch timing relies on static sleeps; interrupted sends during keystroke dispatch cannot verify bubble state and remain in `UNVERIFIED`. |
| **13** | **Prevent duplicate sends** | **Fully implemented and live-tested** | `backend/agent/policy.py`<br>`compute_idempotency_key`<br>`backend/persistence/task_store.py`<br>`consume_approval` | PolicyEngine computes parameter-bound idempotency key. TaskStore ensures approval token can never be consumed twice. Automatic resend on uncertain outcome is strictly rejected. |

---

## 4. SHARED COMMUNICATION ENGINE AUDIT

### 4.1 Evaluation of a Unified Multi-Turn Supervised Workflow
Both Apple Mail and WhatsApp fundamentally execute the same supervised communication lifecycle:
```
[User Natural Request]
          │
          ▼
1. Intent Recognition & Channel Resolution (Email vs WhatsApp)
          │
          ▼
2. Recipient / Contact Resolution & Disambiguation (Strict Exact Matching)
          │
          ▼
3. Missing Information Collection (Recipient / Subject / Body / Attachments)
          │
          ▼
4. Grounded Draft Composition & Quality Control (Zero Fabricated Facts)
          │
          ▼
5. Draft Staging (Apple Mail Drafts Mailbox / WhatsApp Visible Composer)
          │
          ▼
6. Cryptographic Approval Presentation (Canonical SHA-256 Payload Hash)
          │
          ▼
7. Conversational Editing Loop (Automatic Hash Invalidation on Mutation)
          │
          ▼
8. Pre-Dispatch Target & Active Window Re-Verification
          │
          ▼
9. Supervised Dispatch Execution (Atomic Single-Use Token Consumption)
          │
          ▼
10. Independent Observation & Verification (Sent Mailbox / Composer Clearance)
          │
          ▼
11. Durable Audit Event Logging & Honest State Reporting
```

### 4.2 Identified Duplications & Architectural Inconsistencies

```
Existing Fragmented Architecture:
┌────────────────────────────────────────────────────────────────────────┐
│ CortexOrchestrator (7,426 lines — tangled if/elif blocks)               │
├───────────────────────────────────┬────────────────────────────────────┤
│ EMAIL CODE PATH:                  │ WHATSAPP CODE PATH:                │
│ • ProfessionalEmailEngine         │ • compose_whatsapp_message         │
│ • MailTool (BaseTool)             │ • WhatsAppAdapter (AppAdapter)     │
│ • MailAutomation (AppleScript)    │ • WhatsAppDesktopAdapter (AX tree) │
│ • AppleMailProvider (Duplicate!)  │ • cortex_screen_helper (Swift AX)  │
│ • ResolvedRecipient (dataclass)   │ • VerifiedContact (dataclass)      │
│ • action_attempts table           │ • whatsapp_send_attempts table     │
│ • edit_pending_draft (Email only!)│ • (No structured edit method!)     │
└───────────────────────────────────┴────────────────────────────────────┘
```

1. **Parallel Email Provider Implementations:**
   - `backend/capabilities/mail_actions.py` (`MailAutomation`) contains ~780 lines implementing AppleScript for Mail.
   - `backend/integrations/email/apple_mail_provider.py` (`AppleMailProvider`) contains ~560 lines implementing nearly identical AppleScript for Mail.
   - `MailProviderManager` (`backend/integrations/email/manager.py`) manages `AppleMailProvider`, yet `MailAutomation` bypasses it for Apple Mail and only calls it for Gmail.
2. **Recipient Data Model Inconsistency:**
   - Email uses `ResolvedRecipient` (`backend/agent/recipient_resolver.py` line 221) with fields `name, email, phone, role, confidence, source, department, institution`.
   - WhatsApp uses `VerifiedContact` (`backend/core/contracts.py` line 440) with fields `id, name, phone, source, is_verified, metadata`.
   - Both reside in `recipient_resolver.py` but have divergent interfaces and serialization schemas.
3. **Structured Draft Editing Gap:**
   - `CortexOrchestrator.edit_pending_draft()` (`backend/agent/orchestrator.py` line 4176) unconditionally constructs `EmailDraft` and calls `TaskCommand.DRAFT_MAIL`. It does not support WhatsApp drafts.
4. **TaskStore Attempt Table Discrepancy:**
   - WhatsApp has a dedicated `whatsapp_send_attempts` table (`task_store.py` line 116).
   - Apple Mail has no dedicated table, logging only to generic `action_attempts`.

---

## 5. SECURITY AND APPROVAL AUDIT

### 5.1 Cryptographic Parameter Binding

Both communication channels implement strict parameter binding via canonical SHA-256 digest computation:

#### Email Draft Binding (`backend/agent/email_engine.py` lines 57–86):
```python
material = {
    "sender_account": mat["sender_account"],
    "to": mat["to"],
    "cc": mat["cc"],
    "bcc": mat["bcc"],
    "subject": mat["subject"],
    "body": mat["body"],
    "attachments": mat["attachments"],
}
canonical_json = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
approval_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
```

#### WhatsApp Draft Binding (`backend/core/contracts.py` lines 533–553):
```python
material = {
    "channel": "whatsapp",
    "recipient": (self.recipient or "").strip(),
    "phone": re.sub(r"[^\d+]", "", (self.phone or "").strip()),
    "body": (self.body or "").strip(),
}
canonical_json = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
approval_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
```

### 5.2 Approval Invalidation on Mutation
- If the user provides conversational edits (e.g. "make it formal", "change recipient"), the orchestrator updates the draft fields and recomputes `approval_hash`.
- In `CortexOrchestrator.approve()`:
  - If the incoming approval request supplies an outdated hash, execution is blocked (`approval_rejected: token mismatch`).
  - If the task content was modified after the card was presented, `current_hash != expected_hash` triggers:
    `"Approval invalidated: recipient or message content was modified. Please review and approve again."`
  - Empirically verified in `scripts/verify_mail_live.py` and `tests/test_personal_whatsapp_visible_ui.py`.

### 5.3 Single-Use Token Consumption & Replay Prevention
- In `TaskStore.consume_approval(task_id, payload_hash)`:
  - Checks SQLite `approvals` table within an atomic transaction.
  - If already marked `consumed`, rejects with `"Approval already consumed (replay detected)"`.
  - If expired (> 15 minutes), updates status to `expired` and rejects.
  - Atomically marks `status = 'consumed', consumed_at = CURRENT_TIMESTAMP`.
- Verified in `test_task6_apple_mail.py::test_06` and `test_task6_whatsapp.py::test_06`.

### 5.4 Pre-Execution Authorization Check
- In `CortexOrchestrator._execute()` (`backend/agent/orchestrator.py` lines 5198–5207):
  ```python
  if task.command == TaskCommand.SEND_MAIL or (task.requires_approval and task.risk_level == RiskLevel.HIGH):
      has_approval = any(
          getattr(e, "event_type", getattr(e, "name", "")) == "approval_granted"
          for e in getattr(task, "audit_trail", getattr(task, "events", []))
      )
      if not has_approval:
          task.status = TaskStatus.BLOCKED
          task.error = "Execution blocked: explicit user approval is required before sending."
          return
  ```
- Direct execution without explicit approval is impossible.

---

## 6. LIVE MACOS READINESS

### 6.1 Host System & Permission Status
- **Operating System:** macOS 27.0.1 (Build 26A434, Darwin 27.0.0 arm64)
- **Apple Silicon Hardware:** Tested on Apple M-series hardware
- **Permissions Audit Output (`backend/native/cortex_screen_helper permissions`):**
  ```json
  {
    "data": {
      "accessibility": true,
      "screenRecording": true,
      "statusMessage": "Accessibility: GRANTED, Screen Recording: GRANTED"
    },
    "ok": true,
    "timestamp": "2026-11-18T11:12:09Z"
  }
  ```
  - **macOS Accessibility:** `GRANTED`
  - **Screen Recording:** `GRANTED`
  - **AppleEvents Automation:** Responsive for `com.apple.mail` and `net.whatsapp.WhatsApp`.

### 6.2 Application Availability
1. **Apple Mail:**
   - Present at `/System/Applications/Mail.app` (macOS 11+ system location).
   - Bundle Identifier: `com.apple.mail`
   - Background daemon `maild` active (PID 872).
   - Responds to AppleScript bundle queries.
2. **WhatsApp Desktop:**
   - Present at `/Applications/WhatsApp.app`.
   - Bundle Identifier: `net.whatsapp.WhatsApp`
   - Compiled via Mac Catalyst (`UIKit` on AppKit).
   - Responds to AppleScript bundle queries.

### 6.3 Native Automation Helper (`cortex_screen_helper`)
- Binary: `backend/native/cortex_screen_helper` (240 KB, Mach-O 64-bit arm64 executable).
- Source: `backend/native/cortex_screen_helper.swift` (480 lines).
- Capabilities:
  - `permissions`: Preflights AX and ScreenCapture access.
  - `frontmost`: Identifies frontmost active application process.
  - `apps`: Lists running application processes with PIDs and bundle IDs.
  - `windows`: Inspects window layer, frame bounds, and on-screen status.
  - `ax-tree`: Deep recursive traversal of accessibility elements with depth and count bounding.
  - `action`: Performs parameterized accessibility actions (`AXPress`) on targeted element paths.
  - `capture` / `ocr`: Screen capture and Vision framework OCR.

### 6.4 Verification Limitations & Failure Modes on Live macOS
1. **Apple Mail Verification Loop Timeout:**
   `MailAutomation.verify_mail_sent` loops over `messages of sent mailbox` in AppleScript without date bounds. If the user's account contains thousands of sent messages, the AppleScript process exceeds the 5-second timeout and fails.
2. **WhatsApp Catalyst UI Path Fragility:**
   In WhatsApp Catalyst, composer path `0/0/0/0/1/2/1/0/2` is based on fixed child index hierarchy. An update to WhatsApp Desktop that adds a navigation sidebar item, banner, or banner group shifts child indices, breaking `AXPress`.
3. **WhatsApp AX Bubble Invisibility:**
   The WhatsApp Catalyst framework does not expose individual message bubbles, read receipts, or checkmarks in the accessibility tree. Accessibility inspection can verify that composer text was emptied, but cannot confirm delivery to Meta's servers.

---

## 7. EXISTING BUGS AND BLOCKERS (RANKED P0 / P1 / P2)

### P0 — BLOCKERS (Must be fixed before P7 certification)

#### BUG-P0-01: Synthetic Sent Verification Bypass in Apple Mail
- **Subsystem:** `backend/capabilities/mail_actions.py` (`send_mail`, `verify_mail_sent`)
- **Impact:** False-positive test reporting; real email dispatch never verified on live macOS.
- **Details:** `send_mail` checks `is_safe_test`. If recipient domain ends in `@example.com`, `@test.com`, or `PYTEST_CURRENT_TEST` is set, it appends to `_sent_records` and deletes the draft without calling AppleScript `send`. Then `verify_mail_sent` checks `_sent_records` first and reports `"Verified delivery... in sent mailbox register"` without querying Apple Mail!
- **Remediation:** Remove reliance on `_sent_records` in `verify_mail_sent`. Require genuine Apple Mail `Sent` mailbox inspection. In test mode, distinguish explicitly between simulated dry-run and live macOS dispatch.

#### BUG-P0-02: Hardcoded UI Element Paths in WhatsApp Desktop
- **Subsystem:** `backend/capabilities/whatsapp_actions.py` (`WhatsAppDesktopAdapter`)
- **Impact:** Total failure of WhatsApp composer interaction if WhatsApp UI hierarchy shifts.
- **Details:** Composer element path is hardcoded as `0/0/0/0/1/2/1/0/2`. Send button path is hardcoded as `0/0/0/0/1/2/1/0/4`.
- **Remediation:** Replace fixed index paths with dynamic attribute-based accessibility lookup (search for element with role `AXTextArea` and description matching `Compose message`, regardless of tree depth).

---

### P1 — CRITICAL DEFECTS (High risk of runtime failure or data corruption)

#### BUG-P1-01: Unbounded AppleScript Loop on Apple Mail Sent Mailbox
- **Subsystem:** `backend/capabilities/mail_actions.py` (`verify_mail_sent`)
- **Impact:** Subprocess timeout (`TimeoutExpired: 5s`) on live user mailboxes.
- **Details:** The AppleScript query executes:
  `repeat with m in (messages of sent mailbox)`
  `  if (subject of m) contains ... then return "FOUND"`
  On accounts with large sent mailboxes, iterating sequentially through thousands of messages over AppleEvents exceeds the 5-second timeout.
- **Remediation:** Add date bounding (limit search to messages received in the last 15 minutes) and limit iteration count (e.g. `messages 1 thru 20 of sent mailbox`).

#### BUG-P1-02: Programmatic `edit_pending_draft` Assumes Email Only
- **Subsystem:** `backend/agent/orchestrator.py` (`edit_pending_draft`, lines 4176–4250)
- **Impact:** Programmatic API editing of pending WhatsApp tasks fails or attempts to create an email draft.
- **Details:** Method hardcodes `draft = EmailDraft(...)` and calls `self.automation.execute(TaskCommand.DRAFT_MAIL, ...)`.
- **Remediation:** Inspect `task.command` and `task.params["channel"]`. Branch to `WhatsAppDraft` and update WhatsApp composer accordingly.

#### BUG-P1-03: In-Memory PolicyEngine Idempotency Wiped on Process Restart
- **Subsystem:** `backend/agent/policy.py` (`PolicyEngine._executed_actions`)
- **Impact:** Re-execution of duplicate commands possible after Cortex process restart.
- **Details:** `PolicyEngine` tracks executed action hashes in `self._executed_actions` (an in-memory dictionary). Upon crash or restart, this history is lost.
- **Remediation:** Back `PolicyEngine` idempotency checks with the SQLite `action_attempts` table in `TaskStore`.

#### BUG-P1-04: Dual Parallel Apple Mail Provider Implementations
- **Subsystem:** `backend/capabilities/mail_actions.py` vs `backend/integrations/email/apple_mail_provider.py`
- **Impact:** Maintenance divergence, duplicated AppleScript logic, inconsistency between manager and direct capability calls.
- **Details:** `MailAutomation` and `AppleMailProvider` duplicate accounts, signatures, drafts, sending, and verification.
- **Remediation:** Consolidate Apple Mail logic into `AppleMailProvider` and have `MailAutomation` and `MailTool` delegate directly to it.

---

### P2 — MAJOR DEFECTS (Edge cases, usability & resilience)

#### BUG-P2-01: Static Sleep Delays During App Launch & Navigation
- **Subsystem:** `backend/capabilities/whatsapp_actions.py`, `backend/adapters/whatsapp_adapter.py`
- **Impact:** Race conditions on slow/busy machines; unnecessary latency on fast machines.
- **Details:** Uses hardcoded delays (`delay 0.2`, `delay 0.4`, `time.sleep(0.5)`).
- **Remediation:** Implement event-driven polling with a timeout (poll until AX window exists and is ready).

#### BUG-P2-02: Missing Dedicated `mail_send_attempts` Table in TaskStore
- **Subsystem:** `backend/persistence/task_store.py`
- **Impact:** Asymmetric persistence auditing between WhatsApp and Email.
- **Details:** `whatsapp_send_attempts` tracks WhatsApp attempts, but Email lacks a dedicated table.
- **Remediation:** Create `email_send_attempts` table in Migration 3 or unify into a generic `communication_send_attempts` table.

#### BUG-P2-03: Freeform Conversational Edits in WhatsApp Lack Semantic Parsing
- **Subsystem:** `backend/agent/orchestrator.py` (lines 2752–2782)
- **Impact:** Specific content modifications (e.g. "change time to 5pm") reset or fail to apply cleanly.
- **Details:** Follow-up edits in WhatsApp check for tone words ("formal", "casual", "without time") and re-run `compose_whatsapp_message(raw_seed)`. If the user specifies new information, it is not injected into `raw_seed`.
- **Remediation:** Integrate instruction-to-content extraction similar to `EmailEngine.update_draft_with_edit()`.

---

## 8. REDUNDANT IMPLEMENTATIONS TO REUSE OR SIMPLIFY

1. **Consolidate Mail Implementations:**
   - Eliminate duplicated AppleScript code between `backend/capabilities/mail_actions.py` and `backend/integrations/email/apple_mail_provider.py`.
   - Make `AppleMailProvider` the authoritative implementation, subclassing a common communication adapter contract.
2. **Unify Contact Resolution Models:**
   - Merge `ResolvedRecipient` (`recipient_resolver.py`) and `VerifiedContact` (`contracts.py`) into a unified `CommunicationContact` schema supporting email addresses, phone numbers, verified flags, and provenance metadata.
3. **Abstract Common Supervised Communication Pipeline:**
   - Extract the 11-step communication lifecycle out of `orchestrator.py` into a reusable `SupervisedCommunicationEngine`.
   - Email and WhatsApp should be channel drivers under this engine, drastically simplifying `orchestrator.py`.
4. **Unify Idempotency Persistence:**
   - Deprecate in-memory `PolicyEngine._executed_actions` in favor of querying `TaskStore.action_attempts`.

---

## 9. RECOMMENDED IMPLEMENTATION SEQUENCE FOR P7

To achieve production-grade communication automation cleanly without regressions, follow this staged 5-step sequence:

```
┌────────────────────────────────────────────────────────┐
│ Phase P7.1: Unified Communication Controller & Contracts │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ Phase P7.2: Apple Mail Provider Hardening & Live Sent   │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ Phase P7.3: WhatsApp Dynamic AX Discovery & Resilience │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┘
│ Phase P7.4: Shared Multi-Turn Dialogue & Structured Edits│
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ Phase P7.5: Live macOS Acceptance Suite & Zero Mocks   │
└────────────────────────────────────────────────────────┘
```

### Phase P7.1: Unified Communication Controller & Contract Alignment
- Create `backend/agent/communication_engine.py` defining `BaseCommunicationChannel`.
- Standardize `CommunicationDraft` (unifying `EmailDraft` and `WhatsAppDraft`) and `CommunicationContact`.
- Back `PolicyEngine` idempotency with SQLite `action_attempts`.

### Phase P7.2: Apple Mail Provider Hardening & Real Sent Mailbox Verification
- Consolidate all Mail AppleScript into `AppleMailProvider`.
- Fix `verify_mail_sent`: remove in-memory `_sent_records` bypass; implement bounded Sent mailbox query (last 15 minutes, limit 25 messages, matching both subject and recipient).
- Eliminate synthetic send bypass; provide strict live vs dry-run mode isolation.

### Phase P7.3: WhatsApp Dynamic AX Discovery & Resilience
- Upgrade `cortex_screen_helper` and `WhatsAppDesktopAdapter` to dynamically search for `AXTextArea` with description `Compose message` instead of hardcoded index path `0/0/0/0/1/2/1/0/2`.
- Replace static sleep delays with event-driven window readiness polling.
- Document clear delivery status boundaries (composer cleared vs remote network receipt).

### Phase P7.4: Shared Multi-Turn Dialogue, Disambiguation & Structured Edits
- Implement semantic content modification for WhatsApp follow-ups (matching Email's capabilities).
- Update `edit_pending_draft()` in `orchestrator.py` to support both Email and WhatsApp.
- Streamline `orchestrator.py` communication handling through the unified controller.

### Phase P7.5: End-to-End Live macOS Acceptance Suite
- Execute full automated test suite without mock bypasses.
- Verify real draft creation and update in Apple Mail.
- Verify real conversation opening and composer staging in WhatsApp Desktop.
- Validate cryptographic hash invalidation and single-use token consumption.

---

## 10. ACCEPTANCE TESTS FOR EVERY P7 SUBPHASE

### P7.1 Acceptance Tests: Unified Communication Foundation
- **Test P7.1-01 (Idempotency Durability):**
  - *Action:* Record send attempt in `PolicyEngine`, restart orchestrator/policy process, attempt duplicate send with identical parameters.
  - *Expected:* Idempotency check detects prior execution via `TaskStore` and blocks duplicate.
- **Test P7.1-02 (Unified Contact Model):**
  - *Action:* Resolve recipient for email ("Alice <alice@test.com>") and WhatsApp ("Alex (+91 98765 11111)").
  - *Expected:* Both return unified `CommunicationContact` instances with verified provenance flags.

### P7.2 Acceptance Tests: Apple Mail Hardening
- **Test P7.2-01 (Bounded Sent Mailbox Query):**
  - *Action:* Execute `verify_mail_sent` on a live mailbox with > 500 messages.
  - *Expected:* Query completes in < 2.0 seconds without osascript timeout; correctly verifies subject and recipient address.
- **Test P7.2-02 (Zero-Mock Live Draft & Revision):**
  - *Action:* Run live script creating draft in Apple Mail, revise subject, revise body.
  - *Expected:* Mail.app contains exactly one updated draft; zero duplicate draft accumulation; hash recomputed on each revision.

### P7.3 Acceptance Tests: WhatsApp Dynamic AX Discovery
- **Test P7.3-01 (Dynamic Composer Focusing):**
  - *Action:* Open WhatsApp Desktop, resize window or trigger layout change, prepare draft.
  - *Expected:* Screen helper dynamically resolves `AXTextArea` and stages message text; does not rely on static path `0/0/0/0/1/2/1/0/2`.
- **Test P7.3-02 (Dynamic Readiness Polling):**
  - *Action:* Launch WhatsApp from cold state.
  - *Expected:* Adapter polls until AX tree reports ready; no timing race condition failures.

### P7.4 Acceptance Tests: Multi-Turn Dialogue & Structured Edits
- **Test P7.4-01 (WhatsApp Freeform Content Edit):**
  - *Action:* "Prepare WhatsApp to Rahul saying let's meet at 10 AM", followed by "Change meeting time to 2 PM and venue to Library".
  - *Expected:* WhatsApp draft updates with new time and venue; approval hash recomputed; approval card presented.
- **Test P7.4-02 (Programmatic Draft Edit for Both Channels):**
  - *Action:* Invoke `orch.edit_pending_draft(task_id, ...)` on both email and WhatsApp pending tasks.
  - *Expected:* Both update their respective drafts and stage them in Mail.app / WhatsApp Desktop.

### P7.5 Acceptance Tests: Final End-to-End macOS Acceptance
- **Test P7.5-01 (Tamper Detection & Cancellation):**
  - *Action:* Present approval card, mutate draft in background, attempt approval with original token.
  - *Expected:* Rejection with `approval_invalidated`; task returns to `WAITING_APPROVAL`.
- **Test P7.5-02 (Replay Prevention):**
  - *Action:* Approve task, verify execution, attempt to resubmit approval token.
  - *Expected:* Rejection with `TOKEN_ALREADY_USED`.
- **Test P7.5-03 (Draft-Only Containment):**
  - *Action:* "Draft email to X / Prepare WhatsApp to Y. Do not send it." Reply "send it".
  - *Expected:* System blocks dispatch with `"Cannot send: task designated as draft-only"`.
