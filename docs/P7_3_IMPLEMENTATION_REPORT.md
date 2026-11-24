# CORTEX AGENT — PHASE P7.3 IMPLEMENTATION REPORT
## INTELLIGENT EMAIL SEARCH & MULTI-ACCOUNT INTELLIGENCE
### P0 SAFETY CORRECTIONS & APPLE MAIL AUTOMATION HARDENING

**Date:** November 18, 2026  
**Status:** COMPLETE & EMPIRICALLY VERIFIED (42/42 PASSING)  
**Host Environment:** macOS Darwin 27.0.1 (arm64 Apple Silicon)  
**Safety Gate:** REAL SENDING STRICTLY DISABLED (`CORTEX_ALLOW_REAL_EMAIL_SEND` OFF)

---

## 1. EXECUTIVE SUMMARY

Phase P7.3 transforms Cortex from an application with raw Apple Mail MCP connectivity into a unified, intelligent email assistant. Users can express natural-language email requests without knowing email addresses, mailbox identifiers, account names, or MCP tool names.

Simultaneously, Phase P7.3 resolves the four **P0 Critical Safety Deficiencies** identified during the P7 Comprehensive Audit:
1. **P0-A (Sent Verification Timestamp Correlation):** Prevents false-positive delivery confirmations when historical sent emails match the search criteria.
2. **P0-B (Atomic Persistent Idempotency Reservation):** Eliminates check-then-act concurrency race conditions under simultaneous execution requests.
3. **P0-C (BLOCKED State Auditable Reauthorization):** Provides an auditable, intentional mechanism to release blocked send attempts without bypassing safety invariants.
4. **P0-D (Approval Lifecycle & Expiration Binding):** Enforces a durable 15-minute approval window registered immediately upon draft presentation or revision.

All capabilities were implemented strictly within Cortex's existing architecture (`CortexOrchestrator`, `AutonomousPlanner`, `ExecutionEngine`, `PolicyEngine`, `TaskStore`, `DeviceAutomation`, and `ToolRegistry`) without introducing secondary engines or breaking backward compatibility.

---

## 2. P0 CRITICAL SAFETY DEFICIENCIES RESOLVED

### 2.1 P0-A: Sent Verification Timestamp Correlation
- **Defect:** `verify_mail_sent` previously searched Apple Mail's Sent mailbox for matching recipient and subject without bounding the search window by when the send operation was actually initiated. A historical message sent days or weeks earlier would trigger a false-positive delivery confirmation.
- **Resolution (`backend/capabilities/mail_actions.py:verify_mail_sent`):**
  - Added an optional `since_timestamp: float` parameter (epoch seconds).
  - Calculated `max_age = max(15.0, (now - since_timestamp) + 10.0)` to allow for minor system clock drift and Apple Mail message indexing latency.
  - Injected an age check directly into the AppleScript verification routine:
    ```applescript
    set sentDate to date sent of m
    set ageSec to ((current date) - sentDate)
    if ageSec <= maxAge then
        -- Valid recently sent message
    ```
  - If a message matches recipient and subject but is older than `maxAge`, it is explicitly rejected with `DELIVERY_UNCONFIRMED` and `error: "Only historical messages found in Sent mailbox"`.

### 2.2 P0-B: Atomic Persistent Idempotency Reservation
- **Defect:** Duplicate send prevention relied on reading the `mail_send_attempts` table, verifying status in Python application code, and subsequently inserting or updating the row. Under concurrent requests or multi-threaded dispatch, two concurrent tasks could both evaluate the status as `NOT_ATTEMPTED` and proceed to dispatch duplicate emails.
- **Resolution (`backend/persistence/task_store.py:reserve_mail_send_attempt`):**
  - Implemented an atomic SQLite reservation method executed within a single immediate transaction:
    ```python
    def reserve_mail_send_attempt(self, payload_hash: str, task_id: str, metadata: dict | None = None) -> tuple[bool, str]:
    ```
  - Inspects existing records under row/table lock:
    - If no record exists, inserts status `RESERVED` and grants reservation (`True, "RESERVED"`).
    - If status is `RESERVED`, `DISPATCHED`, `COMPLETED`, or `BLOCKED`, the reservation is denied (`False, status`).
    - If status is `FAILED` or `NOT_ATTEMPTED`, atomically transitions to `RESERVED` and grants reservation.
  - Concurrency testing confirmed zero duplicate executions across simultaneous worker threads.

### 2.3 P0-C: BLOCKED State Auditable Operator Reauthorization
- **Defect:** Once a send attempt entered the `BLOCKED` state (due to policy violations, payload tampering, or security triggers), there was no auditable, safe procedure to release the block if the operator deliberately confirmed the action was legitimate.
- **Resolution (`backend/persistence/task_store.py:reauthorize_mail_send_attempt`):**
  - Added `reauthorize_mail_send_attempt(payload_hash, reason, authorized_by)`:
    - Verifies the attempt is currently in `BLOCKED` status.
    - Atomically updates status to `NOT_ATTEMPTED`.
    - Appends structured audit metadata recording timestamp, reason, and authorizing principal.
    - Emits a durable `mail_send_reauthorized` audit event to `audit_events`.
  - Reauthorization occurs outside open database locks to prevent SQLite lock contention.

### 2.4 P0-D: Approval Lifecycle & Expiration Binding
- **Defect:** Approval tokens were only persisted when explicitly confirmed by the user, leaving a gap where presented drafts in the UI could be approved arbitrarily far in the future without adhering to the 15-minute expiration policy.
- **Resolution (`backend/agent/orchestrator.py:_format_approval_card`):**
  - In `_format_approval_card()`, whenever a draft is initially formatted and presented to the user, its cryptographic payload hash is immediately registered in `TaskStore.record_approval()` with a sliding 15-minute (`expires_in_seconds=900`) TTL.
  - Any subsequent edit or account switch immediately invalidates the prior hash and registers the updated draft payload.
  - Expired approvals (> 15 minutes) or approvals already consumed are deterministically rejected with `APPROVAL_EXPIRED` or `APPROVAL_ALREADY_USED`.

---

## 3. INTELLIGENT EMAIL SEARCH IMPLEMENTATION

### 3.1 Intent Classification & Query Extraction
- **Command Routing (`backend/core/contracts.py`):**
  - Expanded `command_from_intent()` to recognize complex conversational search patterns:
    - By sender: `"Do I have any mail from Apple?"`, `"Find emails from RVCE"`
    - By person: `"Show me the latest email from Rahul Hulikatti"`
    - By unread/importance: `"Show unread emails from Instagram"`, `"Important emails"`
    - By subject / keyword: `"Find emails about my project"`, `"Search all accounts for emails containing the word internship"`
    - By event / announcement: `"Find the interview invitation I received last week"`
    - By date expressions: `"Show me emails received between Monday and Friday"`, `"Emails from October"`
    - By reply / thread: `"Find the latest reply from my project guide"`
- **Structured Parameter Parsing (`backend/agent/orchestrator.py:_extract_mail_search_params`):**
  - Extracts structured filters into a query dictionary:
    - `query`: Free-text keywords or extracted entities.
    - `sender`: Discovered sender name or email.
    - `subject`: Targeted topic or keywords.
    - `unread_only`: Boolean flag for unread filter.
    - `mailbox`: Target mailbox (defaults to all mailboxes or `INBOX`).
    - `account`: Target account if specified.
    - `date_from` / `date_to` / `date_expression`: Normalized ISO timestamps or expressions (`today`, `yesterday`, `this week`, `last week`, `between Monday and Friday`, etc.).
    - `limit`: Default 20, capped at 50.

### 3.2 Backend Multi-Criteria Search Execution
- **Provider Multi-Account Search (`backend/capabilities/mail_actions.py:read_mail` & `search_mail`):**
  - Updated Apple Mail AppleScript query generator to extract 6-part metadata per message using `<|COL|>` delimiters:
    `id`, `sender_name`, `sender_email`, `subject`, `date_received`, `is_read`, `mailbox_name`, `account_name`.
  - Dynamically searches across all mailboxes and connected accounts when not constrained to a specific account.
  - Implements multi-criteria filtering matching sender, recipient, subject, read status, and date boundaries.
  - Caps output results safely to prevent memory pressure while providing actionable summaries.

---

## 4. MULTI-ACCOUNT INTELLIGENCE & CONTEXTUAL BINDING

### 4.1 Eradication of Hardcoded Mock Accounts
- Audited and purged all artificial accounts across production paths:
  - Removed `student@university.edu`, `Primary Account`, `me@cortex.internal`, `user@mac.local`.
- Implemented live dynamic account discovery in `backend/capabilities/mail_actions.py:get_accounts()` and `backend/integrations/email/apple_mail_provider.py`:
  - Directly queries Mail.app via AppleScript:
    ```applescript
    tell application "Mail"
        set accList to {}
        repeat with acc in accounts
            set end of accList to (name of acc) & "<|>" & (email addresses of acc as string)
        end repeat
    end tell
    ```
  - Discovered real connected account on host system: `Google` (`gsunilkumar1307@gmail.com`).

### 4.2 Conversational Account Switching & Non-Destructive Refinement
- **Contextual Account Switching (`backend/agent/email_engine.py:update_draft_with_edit`):**
  - Detects user requests like `"Send this from my college email"` or `"Use my work account"`.
  - Matches the requested account against connected accounts.
  - Updates the draft's `sender_account` and immediately re-computes `draft.approval_hash`.
- **Non-Destructive Body Refinement:**
  - Instructions to modify tone, length, or content (e.g. `"Make it shorter and more formal"`) preserve greetings, recipient context, and sign-offs while updating the core body.
  - Recalculates the SHA-256 approval hash so that modified drafts cannot be sent with outdated approval tokens.

---

## 5. FRONTEND SEARCH & RESULT PRESENTATION

- **Desktop UI Search Card (`apps/desktop/src/App.jsx`):**
  - Added dedicated result rendering for `cmd === "search_mail" && task.status === "completed"`.
  - Displays:
    - Account and mailbox badge (e.g. `[Google: INBOX]`).
    - Unread status indicator badge (`UNREAD`).
    - Sender name and email address with an `@` icon.
    - Subject line and relative/formatted date.
    - Message body snippet.
- **Frontend Build Verification:**
  - Ran `npm run build --prefix apps/desktop`.
  - Build completed successfully in 561ms (`dist/index.html`, `dist/assets/index-*.js`, `dist/assets/index-*.css`).

---

## 6. EMPIRICAL VERIFICATION & TEST RESULTS

Full regression verification was executed using the project Python virtual environment:
```bash
PYTHONPATH=. /Users/gsunilkumar/.gemini/antigravity/scratch/cortex/venv/bin/pytest \
  tests/test_mail_search_and_accounts.py \
  tests/test_mail_send_safety.py \
  tests/test_mcp_apple_mail.py \
  tests/test_task6_apple_mail.py -v
```

### 6.1 Test Suite Breakdown

| Test Suite | Purpose | Tests | Result | Duration |
| :--- | :--- | :---: | :---: | :---: |
| `tests/test_mail_search_and_accounts.py` | P7.3 Natural-language search, multi-account discovery, P0 safety fixes | 13 | **13 / 13 PASSED** | 7.54s |
| `tests/test_mail_send_safety.py` | P7.2 Delivery verification, duplicate send prevention, approval binding | 16 | **16 / 16 PASSED** | 15.14s |
| `tests/test_mcp_apple_mail.py` | P7.1 Apple Mail MCP server lifecycle, security allowlists, tool namespacing | 7 | **7 / 7 PASSED** | 7.77s |
| `tests/test_task6_apple_mail.py` | End-to-end conversational draft creation, modification, approval consumption | 6 | **6 / 6 PASSED** | 78.40s |
| **TOTAL** | **Full Apple Mail Communication Automation Suite** | **42** | **42 / 42 PASSED** | **108.85s** |

### 6.2 Key Scenarios Verified
- `test_01_search_query_parsing_sender`: Parsed `"Do I have any mail from Apple?"` -> `sender: "Apple"`.
- `test_02_search_query_parsing_unread`: Parsed `"Show unread emails from Instagram"` -> `unread_only: True, sender: "Instagram"`.
- `test_03_search_query_parsing_keywords_and_topics`: Parsed `"Search all accounts for emails containing the word internship"` -> `query: "internship"`.
- `test_04_search_query_parsing_date_expressions`: Parsed `"Show me emails received between Monday and Friday"` -> `date_expression: "Monday to Friday"`.
- `test_07_dynamic_account_discovery_no_mock_accounts`: Verified real accounts queried without mock fallbacks.
- `test_08_contextual_account_switching_in_draft_edit`: Switched account from Work to Personal with automatic approval hash recalculation.
- `test_10_sent_verification_timestamp_correlation`: Historical emails rejected with `DELIVERY_UNCONFIRMED`.
- `test_11_atomic_idempotency_reservation_concurrency`: Concurrency test proved zero duplicate executions under parallel reservation attempts.
- `test_12_blocked_state_auditable_reauthorization`: Blocked attempts reauthorized only via auditable `reauthorize_mail_send_attempt()`.
- `test_13_approval_lifecycle_expiration_and_replay_prevention`: Approval expiration at 15 minutes and single-use consumption confirmed.

---

## 7. SAFETY BOUNDARY ENFORCEMENT CONFIRMATION

- **Real Email Sending:**
  - `CORTEX_ALLOW_REAL_EMAIL_SEND` remained strictly unset throughout all development, debugging, and verification steps.
  - Sending MCP tools (`send-email`, `send-serial-email`, `reply-to-message`, `forward-message`) remain hard-blocked in `backend/mcp/config.py`, `backend/mcp/client.py`, and `backend/mcp/manager.py`.
  - Zero real emails were transmitted to external mail servers.
- **Git Hygiene:**
  - No commits or pushes to GitHub were made during this phase.

---

## 8. CONCLUSION & PRODUCTION READINESS

Phase P7.3 is **100% complete, fully implemented, and empirically validated**. Cortex now features:
1. Natural language email search across all mailboxes, senders, dates, and topics.
2. Dynamic discovery and contextual switching of connected Apple Mail accounts.
3. Complete elimination of false-positive delivery confirmations via timestamp-correlated Sent mailbox verification.
4. Thread-safe atomic idempotency reservations protecting against duplicate sends.
5. Auditable reauthorization for blocked send operations.
6. Cryptographically bound 15-minute sliding approval tokens with single-use replay rejection.
