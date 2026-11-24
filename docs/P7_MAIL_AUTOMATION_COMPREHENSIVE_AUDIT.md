# CORTEX AGENT — P7 MAIL AUTOMATION
## COMPREHENSIVE AUDIT: CURRENT IMPLEMENTATION VS FINAL PRODUCT REQUIREMENTS

**Audit Status:** `AUDIT-ONLY (READ-ONLY)`  
**Date:** November 18, 2026  
**Host Environment:** macOS Darwin 27.0.1 (arm64 Apple Silicon)  
**Evaluator:** Antigravity Agent  
**Repository Scope:** `Codex/2026-06-17/files-mentioned-by-the-user-cortex`  

---

## A. EXECUTIVE VERDICT

```
================================================================================
EXECUTIVE VERDICT:
READY WITH BLOCKERS
================================================================================
```

### Rationale

Cortex has established a remarkably robust foundation for Apple Mail communication automation. The integration of `apple-mail-mcp` (Phase P7.1) is genuine, active, and dynamically discoverable. The safety hardening (Phase P7.2) successfully eliminated the previous synthetic-send bypass, established SQLite-backed duplicate send protection (`mail_send_attempts`), bound approval tokens to cryptographic draft hashes (including attachment byte fingerprints), and enforced strict blocking of all send operations at every execution boundary.

However, **Cortex is not yet ready to behave as the finalized, capable human email assistant defined in the product objective.** 

Four critical blockers prevent full product readiness:
1. **Email Search Execution Gap (P1):** While `TaskCommand.SEARCH_MAIL` is defined in contracts and parsed by regex, `orchestrator.py` **completely lacks an execution handler** for `SEARCH_MAIL`. Asking natural-language search questions (e.g., *"Do I have any mail from Apple?"* or *"Find the latest email from Rahul Hulikatti"*) falls back to general question answering or an un-filtered `READ_MAIL` that only inspects the first 10 messages of the default inbox.
2. **Multi-Account Intelligence Gaps (P1):** The product requirement mandates treating all connected accounts as a unified environment. In the current implementation, sending accounts are largely defaulted to a hardcoded string (`"Primary Account"` / `"me@cortex.internal"`), account selection is not contextually inferred from recipient domains or history, and search does not span accounts.
3. **Sent Verification Timestamp Vulnerability (P0):** The bounded AppleScript verification in `MailAutomation.verify_mail_sent` matches recipient and subject without filtering by `since_timestamp` or checking message timestamps. An older, historical sent email with an identical subject and recipient will cause a false-positive `SENT_VERIFIED` match.
4. **Concurrency Race Condition in Send Idempotency (P0):** `check_mail_send_duplicate()` and `record_mail_send_attempt()` are two non-atomic SQLite operations. Under rapid concurrent requests for the same payload, two execution threads could pass duplicate inspection before either records the attempt.

---

## B. EXISTING ARCHITECTURE MAP

The diagram and table below show the actual runtime flow from a user request to macOS Mail.app and back.

```
+---------------------------------------------------------------------------------------------------------+
|                                              USER REQUEST                                               |
|                    (Desktop UI / Electron IPC / Audio Chat / REST API: POST /chat)                       |
+---------------------------------------------------------------------------------------------------------+
                                                     |
                                                     v
+---------------------------------------------------------------------------------------------------------+
|                                        CORTEX ORCHESTRATOR                                              |
|                                    (backend/agent/orchestrator.py)                                      |
|  - Manages task lifecycle, turn sessions, memory, policy enforcement, and execution dispatch             |
+---------------------------------------------------------------------------------------------------------+
         |                                           |                                           |
         v (Intent & Recipient)                      v (Draft Generation)                        v (Safety)
+----------------------------------+  +----------------------------------+  +-----------------------------+
|        RECIPIENT RESOLVER        |  |           EMAIL ENGINE           |  |        POLICY ENGINE        |
| (backend/agent/recipient_...py)  |  |   (backend/agent/email_engine.py)|  |  (backend/agent/policy.py)  |
| - Direct syntax extraction       |  | - Contextual role prompt (Gemini)|  | - Idempotency calculation   |
| - Contacts / Address book lookup |  | - Deterministic role fallback    |  | - Risk classification       |
| - Recent correspondence search   |  | - Canonical SHA-256 draft hash   |  | - Approval requirement rule |
| - Directory & Ambiguity handling |  | - Rule-based conversational edit |  | - Sensitive attachment block|
+----------------------------------+  +----------------------------------+  +-----------------------------+
                                                     |
                                                     v
+---------------------------------------------------------------------------------------------------------+
|                                            TASK STORE (SQLite)                                          |
|                                    (backend/persistence/task_store.py)                                  |
|  - Schema V3: tasks, task_steps, approvals, action_attempts, recovery_checkpoints                       |
|  - Persistent Table: mail_send_attempts (UNIQUE payload_hash index, status, attempt_count)              |
+---------------------------------------------------------------------------------------------------------+
                                                     |
                                                     v
+---------------------------------------------------------------------------------------------------------+
|                                             EXECUTION LAYER                                             |
|                                                                                                         |
|    +-----------------------------+                           +-------------------------------------+    |
|    |          MAIL TOOL          |                           |         MCP SERVER MANAGER          |    |
|    | (backend/tools/mail_tool.py)|                           |      (backend/mcp/manager.py)       |    |
|    | BaseTool Lifecycle:         |                           | - Manages apple-mail MCP child proc |    |
|    | execute -> observe -> verify|                           | - Blocklist enforcement             |    |
|    +-----------------------------+                           +-------------------------------------+    |
|                   |                                                             |                       |
|                   v                                                             v                       |
|    +-----------------------------------------------+         +-------------------------------------+    |
|    |           NATIVE MAIL AUTOMATION              |         |          APPLE-MAIL MCP             |    |
|    |     (backend/capabilities/mail_actions.py)    |         |        (backend/mcp/client.py)      |    |
|    | - MailAutomation (AppleScript / System Events)|         | - Stdio JSON-RPC client             |    |
|    | - AppleMailProvider (backend/integrations/...) |         | - Pinned v2.20.57                   |    |
|    +-----------------------------------------------+         +-------------------------------------+    |
+---------------------------------------------------------------------------------------------------------+
                                                     |
                                                     v
+---------------------------------------------------------------------------------------------------------+
|                                         macOS APPLE MAIL.APP                                            |
|                                   (Local Mailboxes, Accounts & Drafts)                                  |
+---------------------------------------------------------------------------------------------------------+
```

### Architectural Component Reference

| Layer / Component | File Path | Primary Classes / Methods | Responsibilities & Observed Implementation |
| :--- | :--- | :--- | :--- |
| **API Boundary** | `backend/api/server.py` | `post_chat`, `post_approve`, `post_edit_draft`, `get_email_accounts` | Exposes REST endpoints to Desktop UI; enforces approval hash validation before calling `orchestrator.approve()`. |
| **Desktop UI** | `apps/desktop/src/App.jsx` | `MailDraftCard`, `ApprovalCard`, `EditDraftModal` | Renders prepared drafts, displays cryptographic approval hash, provides structured modal editor, prevents accidental dispatch. |
| **Orchestration** | `backend/agent/orchestrator.py` | `CortexOrchestrator.chat()`, `approve()`, `edit_pending_draft()` | Central intent router, turn management, task state persistence, single-use approval consumption, and replay rejection. |
| **Identity Resolution** | `backend/agent/recipient_resolver.py` | `RecipientResolver.resolve()`, `_search_mailbox()`, `_search_contacts()` | Multi-stage resolver: direct address -> mailbox correspondence -> contacts -> directory -> conversational clarification. |
| **Email Composition** | `backend/agent/email_engine.py` | `EmailEngine.compose_email()`, `EmailDraft.compute_hash()`, `edit_draft()` | Role-adaptive email composition (Gemini + deterministic fallback), canonical SHA-256 payload hashing, rule-based editing. |
| **Persistence** | `backend/persistence/task_store.py` | `TaskStore.record_mail_send_attempt()`, `check_mail_send_duplicate()` | SQLite relational store (Schema V3); manages `mail_send_attempts` table with unique constraint on `payload_hash`. |
| **Security Policy** | `backend/agent/policy.py` | `PolicyEngine.evaluate()`, `compute_idempotency_key()` | Evaluates risk level (`HIGH` for email), enforces approval requirement, computes canonical idempotency keys. |
| **Tool Execution** | `backend/tools/mail_tool.py` | `MailTool.execute()`, `observe()`, `recover()` | `BaseTool` lifecycle implementation: checks durable duplicate state before execution, observes result, aborts unconfirmed retries. |
| **MCP Management** | `backend/mcp/manager.py`, `backend/mcp/client.py` | `MCPServerManager`, `MCPClient`, `MCPProcess` | Spawns, monitors, and stops MCP servers over stdio; dynamically discovers tools; enforces server-level tool blocklists. |
| **Native Capabilities** | `backend/capabilities/mail_actions.py` | `MailAutomation.draft_mail()`, `send_mail()`, `verify_mail_sent()` | Native macOS automation via `osascript`; bounded Sent mailbox verification; strictly blocks real send execution. |
| **Mail Provider** | `backend/integrations/email/apple_mail_provider.py` | `AppleMailProvider.create_draft()`, `verify_message_sent()` | Direct AppleScript provider for Apple Mail; extracts accounts, manages drafts, verifies sent messages. |

---

## C. REQUIREMENT COMPLIANCE MATRIX

| Product Requirement | Final Specification | Current Implementation | Source Evidence | Status | Identified Gap |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **Multi-Account Search** | Search across all connected accounts when no account is specified. | Searches only default `inbox` of Apple Mail; limited to top 10 messages. | `mail_actions.py:97-121` (`eff_limit = min(limit, 10)`) | **FAIL** | No cross-account mailbox iteration; query restricted to default inbox slice. |
| **Account Identification** | Identify which account received a message. | Only extracts sender, subject, date, snippet. Does not record receiving account. | `apple_mail_provider.py:175-185` | **FAIL** | Inbound messages lack receiving account metadata. |
| **Contextual Account Selection** | Select sending account using verified context (domain, correspondence). | Defaults to `"Primary Account"`. Only changes if user prompt matches mock keywords. | `email_engine.py:46, 1425-1453` | **PARTIAL** | Hardcoded mock account strings (`me@cortex.internal`, `student@university.edu`); no dynamic matching to real accounts. |
| **Account Disambiguation** | Ask user when account selection is ambiguous. | Never prompts for sending account; silently defaults. | `orchestrator.py:2030, 2154` | **FAIL** | No clarification question triggered when multiple accounts are configured. |
| **Sending Account Display** | Display sending account before approval. | Displayed in `MailDraftCard` and `ApprovalCard` (`From: {sender_account}`). | `App.jsx:352, 2209` | **PASS** | UI clearly shows sending account before user approves. |
| **Account Approval Binding** | Account changes invalidate approval. | `sender_account` is included in canonical SHA-256 draft hash. Changing account produces hash mismatch. | `email_engine.py:81, 98` | **PASS** | Cryptographic approval binding covers sending account. |
| **Identity: Contacts** | Query authorized contacts. | Queries `UserAuthorizedContactStore` and provider `search_contacts`. | `recipient_resolver.py:879-905` | **PASS** | Contacts queried and mapped with high confidence (0.9). |
| **Identity: Correspondence** | Resolve identities from incoming/outgoing history. | `_search_mailbox` scans recent correspondence, extracts email, and scores name match. | `recipient_resolver.py:833-877` | **PASS** | Matches past correspondents when present in recent messages. |
| **Identity: No Guessing** | Never invent email address from name/domain. | When resolution fails, returns `status="clarification_required"` asking user for address. | `recipient_resolver.py:445-450` | **PASS** | Zero address fabrication observed in test or code. |
| **Identity: Ambiguity** | Ask user when identity is ambiguous. | Returns `status="multiple_candidates"` with focused selection prompt. | `recipient_resolver.py:385-389`, `test_task6_apple_mail.py:43-70` | **PASS** | Ambiguous contacts trigger explicit clarification turn. |
| **Draft Approval: Fields** | Display Recipient, CC, BCC, Account, Subject, Body, Attachments. | `ApprovalCard` and `MailDraftCard` render all listed fields. | `App.jsx:350-356, 2206-2223` | **PASS** | Complete draft details visible prior to approval. |
| **Draft Approval: Binding** | Explicit approval for exact final version. Content change invalidates token. | `current_hash` recomputed on approval; mismatch forces `WAITING_APPROVAL` with re-review error. | `orchestrator.py:3922-3936`, `test_mail_send_safety.py:192-221` | **PASS** | Tamper detection on body, subject, recipient, attachments. |
| **Send Safety: Persistent Idempotency** | Prevent duplicate sends across process restarts. | SQLite `mail_send_attempts` persists payload hash; rejects duplicates across restarts. | `task_store.py:653-740, 808-826`, `test_mail_send_safety.py:115-135` | **PASS** | Durable SQLite uniqueness prevents restart replays. |
| **Send Safety: Bounded Sent Verification** | Verify Sent mailbox without unbounded loops; handle ambiguous matches. | Bounded to 25–50 messages. Returns `SENT_VERIFIED` on 1 match, `DELIVERY_UNCONFIRMED` on >1 or 0. | `mail_actions.py:640-735`, `test_mail_send_safety.py:245-285` | **PASS** | Bounded scan in place. (*Note: timestamp gap detailed in Section E*). |
| **Natural Language Search** | Support natural language search queries across messages. | Regex extraction in `orchestrator.py:7433` parses query, but **no execution handler exists**. | `orchestrator.py:5482-5535` | **FAIL** | Search queries fall through unexecuted or trigger generic `read_mail`. |
| **Conversational Editing** | Edit specific parts of draft via natural language over multiple turns. | RegEx rules update time, date, CC, BCC, salutation, subject, tone. Freeform fallback overwrites body. | `email_engine.py:1318-1712`, `test_task6_apple_mail.py:72-105` | **PARTIAL** | Non-regex conversational instructions overwrite body instead of LLM targeted editing. |

---

## D. P7.1 FINDINGS — APPLE MAIL MCP INTEGRATION

### 1. Configuration & Connection Status
- **Server Registration:** Configured in `config/mcp_servers.json` and registered as a built-in server in `backend/mcp/config.py` under server ID `apple-mail`.
- **Command & Pinned Package:**
  ```json
  "command": "npx",
  "args": ["-y", "apple-mail-mcp@2.20.57"]
  ```
  Package version is strictly pinned to `2.20.57`. Environment sanitization runs via `get_sanitized_env()`.
- **Process Lifecycle:** `MCPProcess` manages process spawning via `asyncio.create_subprocess_exec`, monitors heartbeat and pipe health, and performs clean termination with SIGTERM and SIGKILL escalation.
- **Dynamic Tool Discovery:** `MCPClient.list_tools()` performs JSON-RPC `tools/list` handshake upon initialization. Discovered tools are dynamically mapped to `MCPToolDefinition`.

### 2. Tool Exposure & Boundary Verification
The live MCP server exposes the following tools:
- `health-check` (callable, verified)
- `list-mailboxes` (callable, verified)
- `search-messages` (callable, verified)
- `get-message` (callable, verified)
- `create-draft` (callable, verified)

**Prohibited Tools Blocked:**
- `send-email`, `send-serial-email`, `reply-to-message`, `forward-message`
- In `backend/mcp/config.py`, these tools are defined in `BLOCKED_APPLE_MAIL_TOOLS`.
- In `backend/mcp/client.py:164`, calling any blocked tool raises `MCPSecurityError`.
- In `backend/mcp/manager.py:224`, `call_tool_async` checks `server.config.is_tool_allowed(tool_name)` and rejects blocked tools prior to process dispatch.
- In `backend/mcp/registry.py`, blocked tools are excluded during registration and are never exposed in `ToolRegistry` or model planner prompts.

### 3. Native Automation Preservation
The native Apple Mail automation (`backend/capabilities/mail_actions.py` and `backend/integrations/email/apple_mail_provider.py`) remains intact alongside MCP. MCP is currently utilized for tool discovery, mailbox listing, and draft verification, while native AppleScript handles deep OS-level operations such as contact address book queries, signature retrieval, and draft window manipulation.

---

## E. P7.2 SECURITY & SEND-SAFETY FINDINGS

### 1. Synthetic-Send Removal Verification
- **Audit:** The hardcoded `is_safe_test` bypass previously present in `mail_actions.py` (which intercepted `@example.com`, `@test.com`, `@cortex.internal`, `@hospital.org`, deleted drafts, and logged fake sent records) has been **completely removed**.
- **Status:** Verified. In `test_mail_send_safety.py`, tests for all test domains and `PYTEST_CURRENT_TEST` confirm that send requests return truthful `ok=False, delivery_status="BLOCKED"`.
- **Draft Deletion:** Draft deletion is completely isolated and never claims email delivery.
- **Mock Separation:** Mocks now exist strictly within isolated test fixtures (`unittest.mock.patch`). Production code never queries `_sent_records` as proof of delivery.

---

### 2. Deep Investigation of Specific Risk Areas

#### Risk A: Persistent Idempotency & Task Deletion
- **Foreign Key Constraint Audit:**
  In `backend/persistence/task_store.py:151-165` and `331-345`, the `mail_send_attempts` table is defined as:
  ```sql
  CREATE TABLE IF NOT EXISTS mail_send_attempts (
      id TEXT PRIMARY KEY,
      task_id TEXT NOT NULL,
      approval_id TEXT,
      payload_hash TEXT NOT NULL,
      ...
  );
  ```
  **Finding:** Notice that `task_id` has **NO foreign key constraint** (unlike `task_steps` and `approvals` which have `REFERENCES tasks(id) ON DELETE CASCADE`).
  - **Result:** Deleting a task from `tasks` table **DOES NOT CASCADE** to `mail_send_attempts`. The record in `mail_send_attempts` remains intact, permanently preserving duplicate-send protection even if the parent task is purged.
- **Concurrency & Atomicity Audit:**
  In `orchestrator.py:3962-3967`, the send execution flow performs:
  ```python
  is_dup, reason, _ = self.task_store.check_mail_send_duplicate(current_hash)
  if is_dup:
      return ...
  self.task_store.record_mail_send_attempt(task.id, current_hash, ...)
  ```
  **Finding (Vulnerability):** `check_mail_send_duplicate()` and `record_mail_send_attempt()` are two independent SQLite transactions. Under concurrent asynchronous requests for the same payload hash, both requests could execute `check_mail_send_duplicate` before either executes `record_mail_send_attempt`. While `record_mail_send_attempt` uses `ON CONFLICT(payload_hash) DO UPDATE` to prevent database duplicate row crashes, both threads would pass the guard and proceed to dispatch sending!
  - **Severity:** P0 Concurrency Blocker.
  - **Required Remediation:** An atomic reservation mechanism (e.g. `INSERT ... ON CONFLICT DO NOTHING` returning affected row count, or an exclusive SQLite write lock) must be implemented.

#### Risk B: BLOCKED State Behavior & Reauthorization
- **Audit:** In `task_store.py:822-824`:
  ```python
  if status == MailDeliveryStatus.BLOCKED.value:
      return True, "Duplicate send prevented: send attempt was previously blocked by safety policy.", attempt
  ```
  **Finding:** When a send attempt is blocked by policy (as all sends currently are in P7.2), its status is recorded as `BLOCKED`. Subsequently, any future request to send that *exact same email* (with the same payload hash) is permanently rejected as a duplicate.
  - **Analysis:** This protection is vital to prevent unauthorized retry loops. However, **no administrative reauthorization method exists** in `TaskStore` or `PolicyEngine`. If the user intentionally wants to send that exact email after real sending is authorized in a later phase, they are blocked unless they modify the draft body (changing the hash) or the database row is manually cleared.
  - **Severity:** P1 Functional Blocker for production sending.
  - **Required Remediation:** Implement an explicit, auditable `reauthorize_send_attempt(payload_hash, admin_token)` method that transitions status from `BLOCKED` to `NOT_ATTEMPTED` with an audit event log.

#### Risk C: Sent-Message Verification & Timestamp Correlation
- **Audit:** In `backend/capabilities/mail_actions.py:640-690`, the verification AppleScript performs:
  ```applescript
  set candidateMessages to (messages 1 thru scanLimit of sent mailbox)
  repeat with m in candidateMessages
      set mSubj to (subject of m)
      -- checks if mSubj contains targetSubj and recipient matches targetRec
  ```
  **Finding (Critical Vulnerability):** While `verify_mail_sent` accepts an argument `since_timestamp: float | None = None` (line 610), **it is completely omitted from the AppleScript!**
  - **Result:** If a user previously sent an email to `alice@example.com` with subject `"Status Update"` three days ago, and today drafts a new email to `alice@example.com` with subject `"Status Update"`, the verifier will inspect `messages 1 thru 25 of sent mailbox`, match the *old* message, and return `SENT_VERIFIED`!
  - **Severity:** P0 Verification Integrity Blocker.
  - **Required Remediation:** The AppleScript must inspect `date sent of m` and strictly assert `(date sent of m) >= dispatch_date`. Furthermore, verification should correlate `Message-ID` or unique body fingerprint where possible. If timestamp evidence is missing or older than dispatch time, the status must remain `DELIVERY_UNCONFIRMED`.

#### Risk D: Approval Integrity & Retroactive Creation
- **Audit:** In `backend/agent/email_engine.py:80-107`, `EmailDraft.compute_hash()` binds:
  `sender_account`, `to`, `cc`, `bcc`, `subject`, `body`, and disk-level attachment file SHA-256 hashes.
- **Audit:** In `orchestrator.py:3920-3936`, `approve()` verifies `current_hash == expected_hash` and checks 15-minute expiration against `task.created_at`.
- **Finding (Architecture Gap):** In `orchestrator.py:3954-3957`:
  ```python
  ok, reason = self.task_store.consume_approval(task.id, current_hash)
  if not ok and "No approval record found" in reason:
      self.task_store.record_approval(task.id, current_hash)
      ok, reason = self.task_store.consume_approval(task.id, current_hash)
  ```
  The approval record in SQLite `approvals` table is **not created when the draft is presented to the user**. It is created *retroactively* at the moment of approval inside `approve()`.
  - **Analysis:** Because `record_approval` was omitted from initial draft preparation, the orchestrator works around it by creating the row immediately before consuming it. While `task.created_at` enforces the 15-minute window in Python, the database column `approvals.expires_at` does not reflect the original draft presentation time.
  - **Severity:** P2 Architecture Debt.

#### Risk E: Execution Boundaries & Send Leakage
Every execution boundary was traced to determine whether real email sending can be triggered:
1. `MCPClient`: **BLOCKED.** Rejects prohibited tools with `MCPSecurityError`.
2. `MCPServerManager`: **BLOCKED.** Rejects prohibited tools with `MCPSecurityError`.
3. `ToolRegistry`: **BLOCKED.** Blocked tools are filtered during discovery; never exposed.
4. `AutonomousPlanner`: **BLOCKED.** Has no tool definition for sending.
5. `Orchestrator`: **BLOCKED.** Direct send calls pass through `MailAutomation.send_mail`.
6. `MailAutomation.send_mail`: **BLOCKED.** Checks `allow_real_send = os.environ.get("CORTEX_ALLOW_REAL_EMAIL_SEND") == "1"`. Without this flag, strictly returns `status="BLOCKED"`.
7. `AppleMailProvider.send_message`: **BLOCKED.** Enforces the identical `CORTEX_ALLOW_REAL_EMAIL_SEND` guard.
8. `FastAPI REST API` / `Electron IPC`: **BLOCKED.** All approval routes call `orchestrator.approve()`, which is governed by the above guards.
- **Conclusion:** Real email sending cannot be reached through any path in Phase P7.2.

---

## F. MISSING PRODUCT CAPABILITIES

### 1. Intelligent Email Search
- **Execution Missing in Orchestrator:** `TaskCommand.SEARCH_MAIL` is defined in contracts and parsed in `_extract_params` (line 7433), but `_execute_task` has no handler for `TaskCommand.SEARCH_MAIL`.
- **Inbox-Only & 10-Message Cap:** `mail_actions.py:read_mail` hardcodes `eff_limit = min(limit, 10)` and only reads `messages of inbox`. Substrings are filtered in Python memory over those 10 items.
- **Natural Language Gaps:** No capability to search by date ranges (*"last week"*, *"yesterday"*), sender organizations (*"from Apple"*), attachment presence, or unread priority across mailboxes.
- **No MCP Search Routing:** `apple-mail-mcp` exposes `search-messages`, but Cortex never routes natural language queries to it.

### 2. Multiple-Account Intelligence
- **Hardcoded Mock Accounts:** In `email_engine.py:1425-1445`, account switching maps to hardcoded mock strings (`College Account (student@university.edu)`, `Primary Account (me@cortex.internal)`).
- **Default Account Disconnect:** Drafts default to `sender_account="Primary Account"`, which does not match real user accounts in macOS Mail (e.g. `Google <gsunilkumar1307@gmail.com>`).
- **No Cross-Account Ingestion:** Cortex cannot identify which account received an incoming email or search across multiple account inboxes.
- **No Ambiguity Handling for Accounts:** Cortex never asks the user: *"You have two accounts (Work and Personal). Which would you like to send this from?"*

### 3. Conversational Email Drafting & Editing
- **Regex Fallback Destroys Draft Content:** In `email_engine.py:1708`, if a user follow-up instruction does not match standard regex patterns (e.g., *"Mention that the lab opens at 9 AM and we need the keys"*), the engine executes:
  ```python
  draft.body = f"Hi {draft.recipient},\n\n{edit_instruction}\n\nBest regards,"
  ```
  This completely wipes out the previous draft body and replaces it with the raw user instruction.
- **Missing Gemini Interactive Revision:** While `_compose_with_gemini` exists for initial draft creation, `update_draft_with_edit` relies entirely on regex string manipulations rather than prompting Gemini to perform an in-place semantic revision.

---

## G. CRITICAL BLOCKERS RANKED BY PRIORITY

| Priority | ID | Blocker Description | Affected Files | Risk / Impact |
| :---: | :---: | :--- | :--- | :--- |
| **P0** | **B-01** | **Sent Verification Lacks Timestamp Correlation** | `backend/capabilities/mail_actions.py:640-690` | Older sent emails with identical recipient/subject can falsely satisfy delivery verification. |
| **P0** | **B-02** | **Concurrency Race in Idempotency Reservation** | `backend/persistence/task_store.py:663-700, 808-826`, `backend/agent/orchestrator.py:3962` | Concurrent requests for identical payload hash can pass duplicate check simultaneously before insertion. |
| **P1** | **B-03** | **Missing Orchestrator Execution Handler for `SEARCH_MAIL`** | `backend/agent/orchestrator.py:5480-5535` | User queries like *"Find emails from Apple"* fall through unexecuted or return generic 5-email inbox lists. |
| **P1** | **B-04** | **Hardcoded Accounts & Missing Multi-Account Routing** | `backend/agent/email_engine.py:1425-1453`, `backend/capabilities/mail_actions.py:826-847` | Drafts default to `"Primary Account"` (`me@cortex.internal`) instead of discovering and binding to real user accounts. |
| **P1** | **B-05** | **Conversational Edit Body-Replacement Fallback** | `backend/agent/email_engine.py:1708` | Unmatched conversational edit instructions wipe existing draft body and replace it with raw instruction text. |
| **P2** | **B-06** | **Search Capped at 10 Inbox Messages** | `backend/capabilities/mail_actions.py:97-121, 755-772` | `read_mail` and `search_mail` only inspect top 10 messages of default inbox; older or filed emails are invisible. |
| **P2** | **B-07** | **Retroactive Approval Row Creation in `TaskStore`** | `backend/agent/orchestrator.py:3954-3957` | Approval database row is created at approval time rather than draft presentation time. |
| **P2** | **B-08** | **Permanent Lockout on BLOCKED State without Reauthorization** | `backend/persistence/task_store.py:822-824` | Once an email draft hash is marked `BLOCKED`, it can never be sent even after real sending is authorized. |

---

## H. TEST AND RUNTIME EVIDENCE

All test suites were executed on the live Darwin host system (`macOS 27.0.1 arm64`). Zero failures occurred across 83 automated test cases.

### Test Execution Summary

```bash
# 1. Mail Send Safety Suite (Phase P7.2)
PYTHONPATH=. python3 -m pytest tests/test_mail_send_safety.py -v
Result: 16 passed in 13.28s

# 2. Mail Orchestrator Acceptance Suite
PYTHONPATH=. python3 -m pytest tests/test_task6_apple_mail.py -v
Result: 6 passed in 67.34s

# 3. Apple Mail MCP Server Integration Suite
PYTHONPATH=. python3 -m pytest tests/test_mcp_apple_mail.py -v
Result: 7 passed in 10.40s

# 4. MCP Core Foundation Suite
PYTHONPATH=. python3 -m pytest tests/test_mcp_foundation.py -v
Result: 18 passed in 1.38s

# 5. MCP Fetch Security & Source Isolation Suite
PYTHONPATH=. python3 -m pytest tests/test_mcp_fetch.py -v
Result: 20 passed in 17.07s

# 6. MCP Filesystem Security Suite
PYTHONPATH=. python3 -m pytest tests/test_mcp_filesystem.py -v
Result: 16 passed in 22.15s
```

**Total Tests:** **83 PASSED, 0 FAILED (100% Pass Rate).**

### Live Host System Runtime Checks
- **Apple Mail Host Accounts:**
  Command: `python3 -c "from backend.integrations.email.apple_mail_provider import AppleMailProvider; print(AppleMailProvider().get_accounts())"`
  Output: `[{'name': 'Google', 'email': 'gsunilkumar1307@gmail.com'}]`
  *Evidence:* Exactly 1 configured account exists in Apple Mail on this machine.
- **Live Mail Send Blocking Check:**
  Command: `python3 -c "from backend.capabilities.mail_actions import MailAutomation; print(MailAutomation().send_mail('test@example.com', 'Subject', 'Body'))"`
  Output: `{'ok': False, 'status': 'BLOCKED', 'delivery_status': 'BLOCKED', 'message': 'Email sending to test@example.com is blocked by safety policy. Real email transmission is disabled in Phase P7.2.', ...}`
  *Evidence:* Send blocking is active and reports truthful `BLOCKED` status.
- **Live Sent Verification Check:**
  Command: `python3 -c "from backend.capabilities.mail_actions import MailAutomation; print(MailAutomation().verify_mail_sent('test@example.com', 'Subject'))"`
  Output: `{'verified': False, 'status': 'DELIVERY_UNCONFIRMED', 'delivery_status': 'DELIVERY_UNCONFIRMED', 'evidence': 'No positive verification evidence found in Sent mailbox for test@example.com.'}`
  *Evidence:* Verifier correctly returns `DELIVERY_UNCONFIRMED` when no match exists.

---

## I. REAL-WORLD ACCEPTANCE SCENARIOS (1–24)

| # | Scenario Description | Evaluation Verdict | Empirical Evidence & Architectural Justification |
| :---: | :--- | :---: | :--- |
| **1** | Search for Apple mail across all accounts | **FAIL** | `SEARCH_MAIL` has no execution handler in `orchestrator.py:5482-5535`; `read_mail` only scans 10 items in default inbox. |
| **2** | Search by a person's name (*"from Rahul"*) | **PARTIAL** | Resolver can find Rahul from recent messages, but orchestrator direct search commands fall back to generic question answering. |
| **3** | Search by organization (*"emails from RVCE"*) | **PARTIAL** | Resolver maps RVCE in directory/contacts, but mailbox search across accounts is not executed. |
| **4** | Search using natural-language date ranges | **FAIL** | Neither AppleScript nor `mail_actions.py` contains date parsing or timestamp filtering for search. |
| **5** | Identify a known contact | **PASS** | `RecipientResolver` identifies authorized contacts with 0.9 confidence; verified in `test_task6_apple_mail.py:test_01`. |
| **6** | Identify person from previous correspondence | **PASS** | `_search_mailbox` parses sender addresses and matches keywords from correspondence. |
| **7** | Handle an ambiguous recipient | **PASS** | Resolver pauses and asks focused single-turn clarification; verified in `test_task6_apple_mail.py:test_02`. |
| **8** | Handle unknown recipient without guessing | **PASS** | Prompts user for email address when resolution fails; never invents address or domain. |
| **9** | Select correct sending account | **PARTIAL** | Defaults to `"Primary Account"` (`me@cortex.internal`); does not dynamically select real configured accounts. |
| **10** | Ask for missing leave-request information | **PARTIAL** | Prompts for recipient if missing, but does not perform multi-slot conversational elicitation for leave dates/reasons. |
| **11** | Compose a project update | **PASS** | Generates context-appropriate subject and body using role adaptation; verified in `test_task6_apple_mail.py:test_01`. |
| **12** | Compose professional application follow-up | **PASS** | Role adaptation detects recruiter/manager context and applies concise, professional tone without filler. |
| **13** | Reply using correct conversation context | **PARTIAL** | `EmailEngine` sets `Re: {subject}`, but thread history ingestion from `apple-mail-mcp` is not linked to prompt context. |
| **14** | Revise existing draft over multiple turns | **PARTIAL** | Regex updates succeed for time, date, tone, CC; but freeform instructions overwrite draft body with raw instruction. |
| **15** | Display complete draft before approval | **PASS** | Frontend `ApprovalCard` displays To, From, CC, BCC, Subject, Body, Attachments, and SHA-256 hash. |
| **16** | Invalidate approval after editing | **PASS** | Any change to draft parameters or attachment contents recomputes hash and triggers `approval_invalidated`. |
| **17** | Reject expired or replayed approval | **PASS** | Replay of consumed approvals rejected; expired tokens rejected; verified in `test_mail_send_safety.py:test_single_use`. |
| **18** | Prevent duplicate sending across restarts | **PASS** | SQLite `mail_send_attempts` UNIQUE `payload_hash` index blocks duplicates across restarts. |
| **19** | Prevent duplicate sending during concurrent requests | **PARTIAL** | `check_mail_send_duplicate` and `record_mail_send_attempt` are non-atomic; race condition exists prior to insert. |
| **20** | Prevent sending through unauthorized paths | **PASS** | Blocked across MCPClient, MCPServerManager, ToolRegistry, Planner, MailAutomation, and AppleMailProvider. |
| **21** | Verify real sent message using reliable evidence | **PARTIAL** | Bounded scan works, but omits timestamp correlation, risking false matches against historical emails. |
| **22** | Handle uncertain send outcomes without retrying | **PASS** | Ambiguous (>1), 0 matches, or timeouts return `DELIVERY_UNCONFIRMED`; `MailTool.recover` halts with `can_retry=False`. |
| **23** | Report actual failures honestly | **PASS** | Synthetic send bypass eliminated; truthful error reporting and `MailDeliveryStatus` contracts enforced. |
| **24** | Preserve task state when app restarts | **PASS** | SQLite `TaskStore` persists tasks, steps, checkpoints, approvals, and send attempts across restarts. |

---

## J. RECOMMENDED IMPLEMENTATION ROADMAP

To transition Cortex from `READY WITH BLOCKERS` to full product readiness, execute the following minimal, architectural roadmap:

```
+---------------------------------------------------------------------------------------------------------+
|                                  RECOMMENDED IMPLEMENTATION ROADMAP                                     |
+---------------------------------------------------------------------------------------------------------+
                                                     |
                                                     v
+---------------------------------------------------------------------------------------------------------+
| PHASE P7.3: EMAIL SEARCH & MULTI-ACCOUNT INTELLIGENCE                                                   |
| - Implement execution handler for TaskCommand.SEARCH_MAIL in backend/agent/orchestrator.py              |
| - Connect search requests to apple-mail-mcp search-messages tool across mailboxes                       |
| - Query real accounts dynamically from AppleMailProvider; replace hardcoded "Primary Account" defaults  |
| - Contextually match sending accounts based on recipient domain (e.g. university.edu -> College Account)|
+---------------------------------------------------------------------------------------------------------+
                                                     |
                                                     v
+---------------------------------------------------------------------------------------------------------+
| PHASE P7.4: VERIFICATION HARDENING & CONCURRENCY ATOMICITY                                              |
| - Inject dispatch_timestamp into MailAutomation.verify_mail_sent and enforce date check in AppleScript   |
| - Implement atomic check-and-insert reservation in TaskStore.record_mail_send_attempt                    |
| - Ensure approvals table row is created at draft presentation time, not retroactively                   |
| - Add auditable reauthorization mechanism for BLOCKED send attempts                                     |
+---------------------------------------------------------------------------------------------------------+
                                                     |
                                                     v
+---------------------------------------------------------------------------------------------------------+
| PHASE P7.5: CONVERSATIONAL DRAFTING VIA GEMINI & THREAD REPLIES                                         |
| - Update email_engine.py:edit_draft to use Gemini for semantic revisions when regex rules don't match   |
| - Prevent whole-body overwrite on conversational editing requests                                       |
| - Connect get-message from apple-mail-mcp into thread context for contextual reply composition           |
+---------------------------------------------------------------------------------------------------------+
                                                     |
                                                     v
+---------------------------------------------------------------------------------------------------------+
| PHASE P7.6: CONTROLLED REAL-SENDING PILOT                                                               |
| - Unlock sending behind CORTEX_ALLOW_REAL_EMAIL_SEND=1 under explicit user confirmation                 |
| - Verify end-to-end send dispatch and real Sent mailbox verification in Apple Mail                      |
+---------------------------------------------------------------------------------------------------------+
```

---

## K. FINAL SIGN-OFF

**Can Cortex proceed to the next implementation phase?**  
**YES**, Cortex is architecturally sound and safe to proceed to **Phase P7.3 (Search & Multi-Account Intelligence)**.

### Mandatory Preconditions Before Enabling Real Email Sending:
1. **Timestamp-Bound Verification (B-01):** Sent mailbox verification must enforce that matching messages were sent strictly after the task's dispatch timestamp.
2. **Atomic Idempotency Reservation (B-02):** Concurrency race in SQLite send attempt recording must be closed with an atomic reservation lock.
3. **Dynamic Account Binding (B-04):** Sending accounts must be dynamically resolved from actual macOS accounts rather than hardcoded mock strings.
4. **Explicit Human Confirmation:** Real sending must remain strictly gated behind explicit user approval cards and the `CORTEX_ALLOW_REAL_EMAIL_SEND` environment gate.
