# CORTEX P7.3 — INDEPENDENT ACCEPTANCE AUDIT
## INTELLIGENT EMAIL SEARCH & MULTI-ACCOUNT INTELLIGENCE
### STRICT READ-ONLY ARCHITECTURAL & EMPIRICAL ACCEPTANCE AUDIT

**Date:** November 18, 2026  
**Audit Type:** Strict Read-Only Acceptance Audit  
**Host Environment:** macOS Darwin 27.0.1 (arm64 Apple Silicon)  
**Safety Gate:** REAL SENDING STRICTLY DISABLED (`CORTEX_ALLOW_REAL_EMAIL_SEND` OFF)  
**Final Verdict:** **ACCEPTED WITH MINOR BLOCKERS**

---

## 1. EXECUTIVE AUDIT SUMMARY

This independent acceptance audit evaluated the Phase P7.3 implementation within the Cortex Agent codebase. The audit inspected actual source files, configuration schemas, SQLite transaction behavior, Apple Mail AppleScript/MCP integration, and test suites.

### Key Audit Findings:
1. **P0 Safety Deficiencies (P0-A, P0-B, P0-C, P0-D):** **FULLY RESOLVED & PASS.** Atomic SQLite idempotency reservations, bounded Sent verification timestamp correlation, auditable BLOCKED reauthorization, and 15-minute sliding approval lifecycle tokens are solidly implemented and verified under concurrency.
2. **Safety Enforcement:** **PASS.** Real email sending remains completely disabled. All unauthorized MCP and native send paths are hard-blocked. Zero external emails were transmitted.
3. **Multi-Account Discovery:** **PASS.** Hardcoded mock identities (`me@cortex.internal`, `student@university.edu`) were purged from production paths. Live Apple Mail account query dynamically resolves host accounts (`Google -> gsunilkumar1307@gmail.com`).
4. **Conversational Editing:** **PASS.** Non-destructive editing preserves greetings, body context, and sign-offs, with automatic SHA-256 approval hash recalculation upon any modification.
5. **Minor Blocker 1 (MCP Dispatch Discrepancy):** **PARTIAL.** Natural-language `SEARCH_MAIL` dispatches via `DeviceAutomation` -> `MailAutomation` (native AppleScript), NOT via the `apple-mail` MCP server (`search-messages`). While the MCP server is connected, allowed, and tested in isolation, the main task execution engine routes search requests through AppleScript.
6. **Minor Blocker 2 (Date Filtering Omission in Filter Loop):** **PARTIAL.** While `_extract_mail_search_params()` in `orchestrator.py` correctly extracts natural-language date expressions (`today`, `yesterday`, `this week`, `last week`, `between Monday and Friday`, specific months) into `date_from` and `date_to`, `MailAutomation.search_mail()` does not evaluate these date boundaries against email timestamps during candidate filtering.
7. **Minor Blocker 3 (Granular Partial Account Failure Reporting):** **PARTIAL.** Search queries execute against Apple Mail's unified `inbox` rather than iterating through accounts individually. Complete Apple Mail failures set `task.status = FAILED`, but partial per-account sync degradation is not isolated or reported.

---

## 2. DETAILED REQUIREMENT-BY-REQUIREMENT EVALUATION

### Requirement 1: Trace Natural-Language SEARCH_MAIL Dispatch
- **Status:** **PARTIAL**
- **Trace Route:**
  1. *User Input:* Natural language query (e.g. `"Do I have any mail from Apple?"`, `"Find emails from RVCE"`).
  2. *Intent Classification:* [`backend/core/contracts.py:command_from_intent()`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/core/contracts.py#L650) classifies the intent into `TaskCommand.SEARCH_MAIL`.
  3. *Parameter Extraction:* [`backend/agent/orchestrator.py:_extract_mail_search_params()`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/agent/orchestrator.py#L5112) extracts `query`, `sender`, `subject`, `unread_only`, `account`, `mailbox`, `date_from`, `date_to`, and `limit`.
  4. *Task Execution:* [`backend/agent/orchestrator.py:_execute_task()`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/agent/orchestrator.py#L4329) calls `self.automation.execute(TaskCommand.SEARCH_MAIL, task.params)`.
  5. *Device Dispatch:* [`backend/capabilities/device_actions.py:execute()`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/capabilities/device_actions.py#L522) calls `self._get_mail().search_mail(...)`.
  6. *Capability Execution:* [`backend/capabilities/mail_actions.py:search_mail()`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/capabilities/mail_actions.py#L794) calls `self.read_mail(limit=fetch_limit, unread_only=unread_only)`.
  7. *Underlying Provider:* Native AppleScript (`osascript -e ...`) queries Mail.app `messages of inbox`.
  8. *Frontend Presentation:* [`apps/desktop/src/App.jsx`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/apps/desktop/src/App.jsx#L950) renders rich result cards with account/mailbox badges, unread indicators, sender, subject, date, and body snippet.
- **Evidence / Discrepancy:**
  The implementation operates reliably end-to-end, but **does not invoke Apple Mail MCP (`apple-mail-mcp`)** for natural-language search queries; it uses the native AppleScript provider. The MCP tool `mcp__apple-mail__search-messages` is registered in `ToolRegistry` and verified in `test_mcp_apple_mail.py`, but `DeviceAutomation` dispatches directly to `MailAutomation`.

---

### Requirement 2: Account Discovery & Multi-Account Traversal
- **Status:** **PARTIAL**
- **File / Method:** [`backend/capabilities/mail_actions.py:get_accounts()`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/capabilities/mail_actions.py#L930) & [`read_mail()`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/capabilities/mail_actions.py#L98)
- **Findings:**
  - Account discovery dynamically queries Apple Mail accounts via AppleScript:
    ```applescript
    tell application "Mail"
        repeat with acc in accounts
            set accName to name of acc
            set accEmail to email addresses of acc
    ```
  - Discovered real connected account on host system: `Google` (`gsunilkumar1307@gmail.com`).
  - Search traversal queries `messages of inbox`. In Apple Mail, `inbox` represents the unified inbox across all accounts.
  - However, non-inbox mailboxes (Archive, Sent, custom folders) or accounts with detached inboxes are not individually traversed during a general search.

---

### Requirement 3: Real Mailbox Data vs Mock Testing
- **Status:** **PASS**
- **Evidence & Breakdown:**
  - **Real macOS Data & Services Tested:**
    - `test_live_apple_mail_mcp_lifecycle` in [`tests/test_mcp_apple_mail.py`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/tests/test_mcp_apple_mail.py#L231): Real process launch of `apple-mail-mcp@2.20.57`, live JSON-RPC handshake, live `health-check`, live `list-mailboxes`, live `search-messages`, live `create-draft` in Mail.app, draft verification in drafts mailbox, cleanup, and live security policy enforcement.
    - `test_07_dynamic_account_discovery_no_mock_accounts` in [`tests/test_mail_search_and_accounts.py`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/tests/test_mail_search_and_accounts.py#L134): Real AppleScript query against Apple Mail accounts.
    - `test_01_draft_mail_resolution_and_content` in [`tests/test_task6_apple_mail.py`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/tests/test_task6_apple_mail.py#L30): Real natural-language draft generation and parameter binding.
  - **Mock / Controlled Unit Fixtures (Safety & Idempotency Testing):**
    - `test_05` & `test_06` in `test_mail_search_and_accounts.py`: Mocked `search_mail` results to verify orchestrator formatting and empty result handling.
    - `test_10` in `test_mail_search_and_accounts.py`: Injected `_mock_sent_verifier` to test age thresholds without transmitting actual emails.
    - `test_mail_send_safety.py`: Mocked subprocess/send paths to verify that `SEND_BLOCKED_BY_POLICY` and bounded verification behave deterministically without transmitting external emails.

---

### Requirement 4: Filtering Across Sender, Organization, Subject, Content, Unread & Date
- **Status:** **PARTIAL**
- **File / Method:** [`backend/capabilities/mail_actions.py:search_mail()`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/capabilities/mail_actions.py#L828) & [`backend/agent/orchestrator.py:_extract_mail_search_params()`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/agent/orchestrator.py#L5112)
- **Detailed Audit:**
  - `sender`: **PASS.** Filters against both `sender` display name and `sender_email` (lines 838-842).
  - `organization`: **PASS.** Captured in query/sender extraction and matched against sender name or snippet.
  - `subject`: **PASS.** Evaluated in line 845 (`if sbj_lower not in e.get("subject", "").lower(): continue`).
  - `content`: **PASS.** Evaluated via `snippet` in lines 834-835.
  - `unread`: **PASS.** Evaluated in lines 855-857 (`if unread_only and e.get("is_read") is True: continue`).
  - `date`: **FAIL / NOT APPLIED IN FILTER LOOP.** In `orchestrator.py`, lines 5153-5176 parse `today`, `yesterday`, `this week`, `last week`, `between Monday and Friday`, and months into `date_from` and `date_to`. These parameters are passed into `search_mail()`, but inside lines 828-870 of `mail_actions.py`, `date_from` and `date_to` are **never checked** against `e.get("date")`. Emails outside the date range are not filtered out.

---

### Requirement 5: Partial Account Failure Reporting
- **Status:** **PARTIAL**
- **File / Method:** [`backend/capabilities/mail_actions.py:read_mail()`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/capabilities/mail_actions.py#L148)
- **Findings:**
  - If Mail.app encounters an AppleScript error, `read_mail` returns `{"ok": False, "message": "Mail error: ..."}` which marks `task.status = TaskStatus.FAILED`. Total failures are thus reported.
  - However, because queries target the unified `inbox` rather than executing discrete queries per connected account, Cortex cannot observe whether one specific account (e.g. Exchange or IMAP) failed while another succeeded. Partial account degradation cannot be surfaced.

---

### Requirement 6: Atomic SQLite Reservation Under Concurrent Requests
- **Status:** **PASS**
- **File / Method:** [`backend/persistence/task_store.py:reserve_mail_send_attempt()`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/persistence/task_store.py#L827)
- **Findings:**
  - Operates inside an immediate SQLite connection transaction (`with self._get_connection() as conn:`).
  - Queries `SELECT * FROM mail_send_attempts WHERE payload_hash = ?;`.
  - Atomically transitions status from `NOT_ATTEMPTED` to `SEND_ATTEMPTED`, incrementing `attempt_count`.
  - Rejects reservation if status is already `SENT_VERIFIED`, `SEND_ATTEMPTED`, `DELIVERY_UNCONFIRMED`, or `BLOCKED`.
  - If concurrent threads attempt insertion simultaneously, SQLite enforces `UNIQUE(payload_hash)`, throwing `IntegrityError` which re-invokes the reservation check to block duplicate dispatch.
  - Empirically validated in `test_11_atomic_idempotency_reservation_concurrency`: 10 simultaneous threads attempted reservation; exactly 1 succeeded and 9 were rejected.

---

### Requirement 7: Timestamp Correlation in Sent Mailbox Verification
- **Status:** **PASS**
- **File / Method:** [`backend/capabilities/mail_actions.py:verify_mail_sent()`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/capabilities/mail_actions.py#L622)
- **Findings:**
  - Accepts `since_timestamp: float | None`. Computes `max_age_seconds = max(5, int(now_ts - since_val) + 10)`.
  - AppleScript routine calculates:
    ```applescript
    set mDate to (date sent of m)
    set ageSec to ((current date) - mDate)
    if ageSec <= maxAge then
        -- valid match candidate
    ```
  - Historical emails in the Sent mailbox matching recipient and subject are ignored. If no recently sent messages match, returns `"NOT_FOUND"`, producing `DELIVERY_UNCONFIRMED`.

---

### Requirement 8: BLOCKED Reauthorization & Audit Trail
- **Status:** **PASS**
- **File / Method:** [`backend/persistence/task_store.py:reauthorize_mail_send_attempt()`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/persistence/task_store.py#L912)
- **Findings:**
  - Verifies that the attempt is strictly in `BLOCKED` status before reauthorizing.
  - Updates status to `NOT_ATTEMPTED` with updated timestamp.
  - Logs a durable audit record to `audit_events` via `record_audit_event("mail_send_reauthorized", ...)` recording `payload_hash`, `reason`, `authorized_by`, and `attempt_id`.
  - Verified empirically in `test_12_blocked_state_auditable_reauthorization`.

---

### Requirement 9: Approval Expiry, Replay Prevention & Modification Invalidation
- **Status:** **PASS**
- **File / Method:** [`backend/persistence/task_store.py:consume_approval()`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/persistence/task_store.py#L982) & [`backend/agent/email_engine.py:compute_hash()`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/agent/email_engine.py#L91)
- **Findings:**
  - `_format_approval_card()` persists a sliding 15-minute (`expires_in_seconds=900`) approval record upon draft creation or update.
  - `consume_approval()` checks `expires_at < now_iso` and atomically transitions status from `pending` to `consumed`.
  - Attempting to re-use a consumed approval returns `"Approval already consumed (replay detected)"`.
  - `EmailDraft.compute_hash()` digests `sender_account`, `to`, `cc`, `bcc`, `subject`, `body`, and `attachments`. Modifying any field (including account or attachment) alters the hash, immediately invalidating the prior approval token.

---

### Requirement 10: Unauthorized Send Execution Paths Remain Blocked
- **Status:** **PASS**
- **File / Method:** [`backend/mcp/config.py`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/mcp/config.py#L292), [`backend/mcp/client.py`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/mcp/client.py#L125), [`backend/capabilities/mail_actions.py:send_mail()`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/capabilities/mail_actions.py#L469)
- **Findings:**
  - `BLOCKED_APPLE_MAIL_TOOLS = {"send-email", "send-serial-email", "reply-to-message", "forward-message"}` enforced at config, client, and manager levels (`MCPSecurityError`).
  - `MailAutomation.send_mail()` checks `allow_real_send = os.environ.get("CORTEX_ALLOW_REAL_EMAIL_SEND") == "1"`. When unset, returns `SEND_BLOCKED_BY_POLICY`.
  - `CORTEX_ALLOW_REAL_EMAIL_SEND` remained unset throughout all audit executions. No real emails transmitted.

---

### Requirement 11: Conversational Editing Body Preservation
- **Status:** **PASS**
- **File / Method:** [`backend/agent/email_engine.py:update_draft_with_edit()`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/agent/email_engine.py#L1318)
- **Findings:**
  - Specialized regex handlers handle time updates, date changes, account switches, CC changes, attachments, and paragraph insertions non-destructively.
  - General refinement handler (lines 1731-1743) preserves greeting (`lines[0]`), existing middle paragraphs (`lines[1:-1]`), appends the user's edit, and preserves sign-off (`lines[-1]`).
  - Accidental full-body overwrites do not occur. Empirically verified in `test_09_non_destructive_draft_refinement`.

---

### Requirement 12: Regressions Against P7.1 and P7.2
- **Status:** **PASS**
- **Evidence:**
  Full test regression pass executed:
  - `tests/test_mail_search_and_accounts.py`: **13 passed / 13 passed**
  - `tests/test_mail_send_safety.py`: **16 passed / 16 passed**
  - `tests/test_mcp_apple_mail.py`: **7 passed / 7 passed**
  - `tests/test_task6_apple_mail.py`: **6 passed / 6 passed**
  - **Total:** **42 passed / 42 passed in 108.85s**. Zero regressions.

---

## 3. AUDIT CLASSIFICATION SUMMARY TABLE

| # | Requirement | Classification | Primary File & Method |
| :---: | :--- | :---: | :--- |
| 1 | Trace natural-language SEARCH_MAIL dispatch | **PARTIAL** | `backend/capabilities/device_actions.py:522` (routes to AppleScript, not MCP) |
| 2 | Account discovery & multi-account traversal | **PARTIAL** | `backend/capabilities/mail_actions.py:930` (discovers accounts; searches unified inbox) |
| 3 | Real mailbox data vs mock testing | **PASS** | `tests/test_mcp_apple_mail.py` (real MCP/Mail.app); mocks used for send safety |
| 4 | Multi-criteria filtering (sender, org, sbj, body, unread, date) | **PARTIAL** | `backend/capabilities/mail_actions.py:828` (date_from/to not applied in loop) |
| 5 | Partial account failure reporting | **PARTIAL** | `backend/capabilities/mail_actions.py:148` (unified inbox query; no per-account health) |
| 6 | Atomic SQLite reservation under concurrency | **PASS** | `backend/persistence/task_store.py:827` (`reserve_mail_send_attempt`) |
| 7 | Sent mailbox verification timestamp correlation | **PASS** | `backend/capabilities/mail_actions.py:622` (`verify_mail_sent`) |
| 8 | BLOCKED reauthorization & audit trail | **PASS** | `backend/persistence/task_store.py:912` (`reauthorize_mail_send_attempt`) |
| 9 | Approval expiry, replay prevention & hash invalidation | **PASS** | `backend/persistence/task_store.py:982` & `backend/agent/email_engine.py:91` |
| 10 | Unauthorized send paths remain blocked | **PASS** | `backend/capabilities/mail_actions.py:469` (`CORTEX_ALLOW_REAL_EMAIL_SEND` gate) |
| 11 | Conversational editing body preservation | **PASS** | `backend/agent/email_engine.py:1731` (`update_draft_with_edit`) |
| 12 | Regression verification against P7.1 and P7.2 | **PASS** | 42/42 tests passing across all 4 suites |

---

## 4. FINAL VERDICT & RECOMMENDATIONS

### Final Verdict: **ACCEPTED WITH MINOR BLOCKERS**

### Rationale:
The core safety, idempotency, approval lifecycle, and multi-account discovery requirements are robustly implemented and empirically validated. The system is completely safe: no emails can be sent accidentally or without valid, non-expired, single-use approval.

The minor blockers identified do not compromise system safety or cause user-facing crashes, but represent functional gaps against the final product specifications:
1. **Route SEARCH_MAIL to Apple Mail MCP:** When Apple Mail MCP is running, `DeviceAutomation.execute(TaskCommand.SEARCH_MAIL)` should route queries to `mcp__apple-mail__search-messages` rather than falling back directly to native AppleScript.
2. **Apply Date Filtering in Candidate Evaluation Loop:** In `backend/capabilities/mail_actions.py:search_mail()`, parse `e.get("date")` and filter against `date_from` and `date_to` so that temporal queries (e.g. `"between Monday and Friday"`) discard messages outside the target window.
3. **Per-Account Query Fallback:** For multi-account resilience, support iterating over discovered accounts individually when the unified inbox query fails or when the user asks to inspect a specific account's folders.
