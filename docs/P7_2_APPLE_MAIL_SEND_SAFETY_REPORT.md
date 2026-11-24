# CORTEX AGENT — PHASE P7.2 IMPLEMENTATION REPORT
## APPLE MAIL SEND-SAFETY HARDENING & DELIVERY VERIFICATION

**Phase Status:** `P7.2 COMPLETE — SEND SAFETY HARDENED, REAL SENDING STILL BLOCKED`  
**Date:** June 17, 2026 / November 18, 2026  
**Host Environment:** macOS Darwin 27.0.1 (arm64 Apple Silicon)  
**Safety Status:** Real email transmission strictly disabled; synthetic-send bypass completely eliminated; persistent idempotency active.

---

### 1. EXECUTIVE SUMMARY

In Phase P7.1, Apple Mail MCP integration was established and safe read, search, listing, and draft-creation capabilities were verified against macOS Mail.app while sending tools were blocked. However, an architectural audit revealed a critical synthetic-send bypass in `MailAutomation.send_mail` and `verify_mail_sent` that fabricated delivery success when test domains or pytest environment variables were encountered, deleting drafts and treating in-memory mock logs as proof of delivery.

Phase P7.2 eliminates all false-positive email delivery paths, establishes durable SQLite idempotency across process restarts, strengthens cryptographic approval integrity (including disk-level attachment content hashing), implements bounded Sent mailbox verification, and enforces explicit truthful delivery states.

**Core Safety Guarantee:** Production execution can never report successful delivery without actual observable evidence in the Sent mailbox. Real email transmission remains strictly disabled in P7.2 until real send authorization is scheduled in subsequent phases.

---

### 2. AUDIT FINDINGS & DEFECT RESOLUTION

Prior to modification, a comprehensive audit identified five critical safety risks across the mail subsystem:

| Defect / Risk | Previous Implementation | Phase P7.2 Hardening |
| :--- | :--- | :--- |
| **Synthetic Send Bypass** | `mail_actions.py` checked `is_safe_test` (`PYTEST_CURRENT_TEST` or domains `@example.com`, `@test.com`, `@cortex.internal`, `@hospital.org`), deleted the draft, and returned fake `sent` success. | **Completely Removed.** `is_safe_test`, domain filtering, and draft-deletion fake sends were excised. In P7.2, send requests return truthful `BLOCKED` status. |
| **Fabricated Sent Verification** | `verify_mail_sent` checked in-memory `self._sent_records` and returned `verified=True` without checking Mail.app. | **Excised.** In-memory records are never treated as delivery evidence. Verification queries Mail.app Sent mailbox via bounded AppleScript. |
| **Unbounded Sent Mailbox Scan** | AppleScript loop `repeat with m in (messages of sent mailbox)` scanned all historical sent messages without limit. | **Bounded Window Scan.** Limited to `messages 1 thru scanLimit` (capped at 25-50 messages). |
| **Ephemeral Idempotency** | Duplicate checks were in-memory and lost across server or process restarts. | **Durable SQLite Table.** Migration 3 in `TaskStore` persists `mail_send_attempts` with a UNIQUE index on `payload_hash`. |
| **Attachment Tampering Vulnerability** | Approval hashes only checked attachment file names/paths, ignoring modified bytes on disk. | **Content-Level Hashing.** `EmailDraft.canonicalize()` computes SHA-256 digests of attachment file contents on disk. |

---

### 3. TECHNICAL IMPLEMENTATION DETAILS

#### 3.1 Removal of Synthetic Send Success
- **Files Modified:**
  - `backend/capabilities/mail_actions.py`:
    - Removed `is_safe_test` block and recipient-domain interception (`@example.com`, `@test.com`, `@cortex.internal`, `@hospital.org`).
    - Removed `PYTEST_CURRENT_TEST` environment checks in production execution.
    - Removed draft deletion masquerading as successful send.
    - Updated `send_mail` to return `ok=False`, `status="BLOCKED"`, `delivery_status="BLOCKED"` when real sending is disabled by policy.
  - `backend/integrations/email/apple_mail_provider.py`:
    - Removed synthetic send branches. Returns truthful `BLOCKED` status.

#### 3.2 Durable SQLite Idempotency (`TaskStore`)
- **File Modified:** `backend/persistence/task_store.py`
- **Schema Migration 3:**
  ```sql
  CREATE TABLE IF NOT EXISTS mail_send_attempts (
      id TEXT PRIMARY KEY,
      task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
      approval_id TEXT,
      payload_hash TEXT NOT NULL,
      recipient_hash TEXT NOT NULL,
      subject_hash TEXT NOT NULL,
      status TEXT NOT NULL,
      attempt_count INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      verified_at TEXT,
      provider_message_id TEXT,
      verification_details TEXT
  );
  CREATE UNIQUE INDEX IF NOT EXISTS idx_mail_attempts_payload ON mail_send_attempts(payload_hash);
  CREATE INDEX IF NOT EXISTS idx_mail_attempts_task_id ON mail_send_attempts(task_id);
  CREATE INDEX IF NOT EXISTS idx_mail_attempts_status ON mail_send_attempts(status);
  ```
- **Duplicate Prevention Policy:**
  - `check_mail_send_duplicate(payload_hash)` inspects the persistent table before any send invocation.
  - Rejects attempts if the payload was already `SENT_VERIFIED`, `SEND_ATTEMPTED` (in-flight), `DELIVERY_UNCONFIRMED`, or `BLOCKED`.
  - Persists across application restarts, ensuring duplicate emails are never dispatched even after sudden crashes.

#### 3.3 Cryptographic Approval Integrity
- **Files Modified:** `backend/agent/email_engine.py`, `backend/agent/orchestrator.py`, `backend/agent/policy.py`
- **Canonical Payload Digest:**
  Computes a 64-character SHA-256 digest covering:
  - `sender_account`
  - Normalized recipient (`to`, `cc`, `bcc`)
  - Normalized `subject` and `body`
  - **Attachment Content Fingerprints:** Reads file bytes from disk and computes SHA-256 checksums (`filename:sha256_content_hash`).
- **Immediate Invalidation:** Any change to recipient, subject, body, CC, BCC, or attachment file content on disk immediately causes a hash mismatch, invalidating approval and forcing re-review.
- **Single-Use Consumption & Expiration:**
  Approvals expire after 15 minutes and can only be consumed once. Attempting to approve an already-consumed task is blocked as a replay attempt.

#### 3.4 Bounded Sent Mailbox Verification
- **Files Modified:** `backend/capabilities/mail_actions.py`, `backend/integrations/email/apple_mail_provider.py`, `backend/tools/mail_tool.py`
- **Bounded AppleScript Query:**
  ```applescript
  tell application "Mail"
      set totalSent to count of messages of sent mailbox
      if totalSent is 0 then return "NOT_FOUND"
      set scanLimit to 25
      if totalSent < scanLimit then set scanLimit to totalSent
      set candidateMessages to (messages 1 thru scanLimit of sent mailbox)
      -- Bounded match iteration over candidates only
  ```
- **Definitive Delivery States (`MailDeliveryStatus` in `backend/core/contracts.py`):**
  1. `BLOCKED`: Prevented by safety policy; no transmission attempted.
  2. `NOT_ATTEMPTED`: Draft created or action queued, no send triggered.
  3. `SEND_ATTEMPTED`: Send dispatch initiated, awaiting verification.
  4. `DELIVERY_UNCONFIRMED`: Sent mailbox check returned 0 matches, multiple matches (ambiguous), timeout, or AppleScript error. Prohibits automatic retries.
  5. `SENT_VERIFIED`: Confirmed exactly 1 matching message in Apple Mail Sent mailbox.
  6. `SEND_FAILED`: Explicit transport error or failure reported by adapter.

#### 3.5 Backend MCP Send Restrictions
- P7.1 send restrictions remain strictly preserved on the `apple-mail` MCP server:
  - Blocked tools: `send-email`, `send-serial-email`, `reply-to-message`, `forward-message`.
  - Invocation of any blocked tool directly via `MCPClient.call_tool` or `MCPServerManager.call_tool` immediately raises `MCPSecurityError`.
  - `ToolRegistry` does not register blocked sending tools into the model's executable tool definitions.

---

### 4. VERIFICATION RESULTS & TEST SUITE

A dedicated test suite `tests/test_mail_send_safety.py` was authored covering 16 comprehensive safety test cases. In addition, full regression suites across all system components were executed.

#### 4.1 Test Execution Summary

| Test Suite | Total Tests | Passed | Failed | Status |
| :--- | :---: | :---: | :---: | :---: |
| `tests/test_mail_send_safety.py` (P7.2 Safety Suite) | 16 | 16 | 0 | **PASSED** |
| `tests/test_task6_apple_mail.py` (Mail Orchestrator) | 6 | 6 | 0 | **PASSED** |
| `tests/test_mcp_apple_mail.py` (Apple Mail MCP Server) | 7 | 7 | 0 | **PASSED** |
| `tests/test_mcp_foundation.py` (MCP Core Lifecycle) | 18 | 18 | 0 | **PASSED** |
| `tests/test_mcp_fetch.py` (Fetch MCP Security & SSRF) | 20 | 20 | 0 | **PASSED** |
| `tests/test_mcp_filesystem.py` (Filesystem MCP Security) | 16 | 16 | 0 | **PASSED** |
| **Total Test Suite** | **83** | **83** | **0** | **100% PASSED** |

#### 4.2 Detailed P7.2 Test Breakdown (`test_mail_send_safety.py`)

1. `test_synthetic_send_domains_never_report_success`: Tests `@example.com`, `@test.com`, `@cortex.internal`, `@hospital.org` — all return truthful `BLOCKED` status.
2. `test_pytest_env_never_triggers_synthetic_send`: `PYTEST_CURRENT_TEST` presence in environment does not bypass safety policy.
3. `test_draft_deletion_never_reports_delivery`: Deleting drafts never reports `SENT_VERIFIED`.
4. `test_verify_mail_sent_does_not_rely_on_in_memory_records`: Verifier ignores in-memory logs and queries real mailbox state.
5. `test_task_store_mail_send_attempts_schema_and_persistence`: Migration 3 persists send attempt metadata and unique payload hashes.
6. `test_duplicate_send_prevention_across_restarts`: Re-instantiated `TaskStore` detects previous sends and blocks duplicates.
7. `test_duplicate_send_blocked_for_all_non_repeatable_states`: Blocks retries for `BLOCKED`, `SEND_ATTEMPTED`, and `DELIVERY_UNCONFIRMED`.
8. `test_approval_hash_covers_all_fields_and_attachments`: Deterministic SHA-256 across all recipient, body, and attachment fields.
9. `test_approval_invalidated_when_content_or_recipient_modified`: Tampering with body or attachment bytes invalidates approval.
10. `test_single_use_approval_consumption_and_replay_rejection`: Replay attempts on consumed approvals are rejected.
11. `test_bounded_sent_verification_single_match`: Exactly 1 match yields `SENT_VERIFIED`.
12. `test_bounded_sent_verification_ambiguous_matches`: Multiple matches yield `DELIVERY_UNCONFIRMED` (ambiguous).
13. `test_bounded_sent_verification_not_found`: Zero matches yield `DELIVERY_UNCONFIRMED`.
14. `test_bounded_sent_verification_applescript_timeout_or_error`: Timeouts or AppleScript errors yield `DELIVERY_UNCONFIRMED`.
15. `test_mcp_client_blocks_apple_mail_send_tools`: `MCPClient` raises `MCPSecurityError` on prohibited tools.
16. `test_mcp_server_manager_blocks_apple_mail_send_tools`: `MCPServerManager` blocks dispatch of prohibited tools.

---

### 5. SYSTEM CAPABILITY MATRIX

| Capability | Previous State (P7.1) | Current State (P7.2) | Target State (Production Release) |
| :--- | :---: | :---: | :---: |
| Apple Mail MCP Connection | Connected | Connected | Connected |
| Safe Tool Discovery | Verified | Verified | Verified |
| Read / Search / List Mail | Verified | Verified | Verified |
| Draft Creation & Modification | Verified | Verified | Verified |
| Synthetic Send Interception | Active Defect | **Eliminated** | Eliminated |
| Durable Send Idempotency | Missing | **Active (SQLite)** | Active (SQLite) |
| Attachment Content Hashing | Missing (path only) | **Active (SHA-256)** | Active (SHA-256) |
| Bounded Sent Verification | Missing (unbounded) | **Active (Bounded 25-50)** | Active (Bounded 25-50) |
| Real Email Transmission | Blocked | **Blocked** | Enabled with User Approval |

---

### 6. FINAL VERDICT & RECOMMENDATIONS

```
================================================================================
FINAL VERDICT:
P7.2 COMPLETE — SEND SAFETY HARDENED, REAL SENDING STILL BLOCKED
================================================================================
```

1. **Safety Objective Met:** False-positive email delivery has been completely eliminated from the codebase. No domain, environment flag, or mock record can cause Cortex to report an unverified or unsent email as sent.
2. **Duplicate Prevention Established:** SQLite `TaskStore` maintains persistent record of send attempts by payload hash, preventing duplicate transmissions even across process restarts.
3. **Approval Integrity Hardened:** Approvals are strictly bound to exact recipient addresses, message content, and attachment byte fingerprints.
4. **Real Sending Remains Blocked:** As required by P7.2 scope, real sending remains strictly blocked across all layers (MCP client, server manager, tool registry, and native capabilities). Real email dispatch should only be unlocked in a future phase with explicit human-in-the-loop signoff.
