# Phase P7.1: Apple Mail MCP Connection & Existing Architecture Preservation Report

**Execution Date:** November 18, 2026  
**Platform:** macOS 27.0.1 (Darwin arm64)  
**Host Application:** Mail.app (`com.apple.mail`), Node.js v24.13.1, npm / npx 11.8.0  
**Target Logical Server ID:** `apple-mail`  
**Target Package:** `apple-mail-mcp` @ `2.20.57` (Pinned)  
**Integration Status:** Complete & Verified on Live macOS Environment  

---

## Executive Summary

Phase P7.1 successfully integrated the dedicated Apple Mail Model Context Protocol (MCP) server (`apple-mail-mcp` pinned at version `2.20.57`) into the Cortex agent using its existing, production-grade MCP infrastructure (`MCPProcess`, `MCPClient`, `MCPServerManager`, `MCPRegistryBridge`, and `ToolRegistry`).

All pre-integration inspections, package verification, process lifecycles, JSON-RPC 2.0 handshakes, tool filtering policies, and live macOS Mail operations were empirically validated. Real read, search, health check, mailbox listing, and draft creation were executed live in Apple Mail (`Mail.app`), confirmed via AppleScript mailbox inspection, and safely cleaned up.

Crucially, **sending tools (`send-email`, `send-serial-email`, `reply-to-message`, `forward-message`) were strictly blocked at the backend engine level** (`MCPClient.call_tool` and `MCPServerManager.call_tool_async` enforce `is_tool_allowed` and raise `MCPSecurityError`), guaranteeing that prompt instructions alone are never relied upon to prevent consequential email dispatch. Existing native implementations (`MailAutomation` and `AppleMailProvider`) were preserved completely intact without breaking changes.

---

## 1. Selected Package and Source Verification

### Package Identification & Pinned Version
- **Repository:** `https://github.com/sweetrb/apple-mail-mcp`
- **Package Name:** `apple-mail-mcp`
- **Pinned Version:** `2.20.57`
- **Author:** Rob Sweet (`rob@superiortech.io`)
- **License:** MIT License
- **OS Requirement:** `darwin` (macOS required)
- **Engine Requirement:** `node >= 20.0.0` (Environment has Node v24.13.1)
- **Executable Binaries:** `apple-mail-mcp` (`build/index.js`), `apple-mail-send` (`build/cli.js`)

### Verification Audit
A comprehensive pre-installation audit of the package metadata and code on the npm registry confirmed:
1. **License & Compliance:** Standard permissive MIT license. Contains no tracking telemetry or unauthorized network egress.
2. **AppleScript & Security Boundaries:** Interacts with `com.apple.mail` exclusively via macOS Apple Events (`osascript` and JXA).
3. **Execution Safety:** Requires no elevated root/sudo privileges; runs within standard user session permissions (`System Settings > Privacy & Security > Automation > Mail.app`).

---

## 2. MCP Integration & Architectural Alignment

The connection strictly reused Cortex's existing MCP infrastructure without introducing redundant abstraction layers:

1. **Subprocess Management (`MCPProcess`):**
   - Spawns `npx -y apple-mail-mcp@2.20.57` via non-shell `create_subprocess_exec`.
   - Sanitizes environment variables using `sanitize_environment()`, stripping all API keys and session secrets.
   - Robust `PATH` resolution via `essential_dirs` (`/opt/homebrew/bin`, `/usr/local/bin`, `~/.local/bin`, etc.) ensuring reliable startup in Electron packaged environments.
2. **JSON-RPC stdio Client (`MCPClient`):**
   - Protocol version: `2024-11-05`.
   - Line-delimited JSON-RPC framing with request/response correlation and cancellation handling.
3. **Server Manager (`MCPServerManager`):**
   - Registered under logical ID `apple-mail` with `timeout_seconds: 30.0` and `default_risk_level: RiskLevel.MEDIUM`.
   - Managed lifecycle: `start_server`, `stop_server`, `call_tool_async`, and `run_sync`.
4. **Registry Bridge (`MCPRegistryBridge`):**
   - Synchronizes discovered and permitted tools into `ToolRegistry`.
   - Exposes tools under canonical names (`mcp__apple-mail__<tool_name>`).
   - Assigns `RiskLevel.LOW` to read/search/status tools and `RiskLevel.MEDIUM` to draft manipulation tools.

---

## 3. Safe Initial Tool Exposure & Backend Security Restrictions

The `apple-mail-mcp` package exposes 53 tools in total. In accordance with Step 3, **only safe read, search, status, and draft operations are exposed to the model**. Sending tools are explicitly prohibited.

### Tool Allowlist (`SAFE_APPLE_MAIL_TOOLS`)
The following 16 tools are permitted and exposed through `ToolRegistry`:
1. `health-check` (Diagnose connection and macOS permissions)
2. `doctor` (Validate Mail accounts and system readiness)
3. `get-sync-status` (Check background synchronization status)
4. `get-mail-stats` (Retrieve total counts and statistics)
5. `list-mailboxes` (List all mailboxes across active accounts)
6. `list-accounts` (List configured mail accounts)
7. `get-unread-count` (Get unread message counts)
8. `search-messages` (Search emails by query, sender, subject, date)
9. `list-messages` (List messages in a specific mailbox)
10. `get-message` (Read email content and headers by ID)
11. `get-message-headers` (Inspect specific MIME headers)
12. `get-thread` (Read full email conversation thread)
13. `list-attachments` (List attachment metadata for an email)
14. `get-attachment-metadata` (Retrieve attachment filenames and MIME types)
15. `create-draft` (Create a real draft in Mail.app)
16. `update-saved-draft` (Update an existing draft's subject or body)

### Blocked Consequential Tools (`BLOCKED_APPLE_MAIL_TOOLS`)
The following tools are strictly blocked from exposure and execution:
- `send-email`
- `send-serial-email`
- `reply-to-message`
- `forward-message`

### Backend Security Enforcement
Security restrictions are enforced deterministically in Python backend code:
- `MCPServerConfig.is_tool_allowed(name)` checks `blocked_tools` first and then validates against `allowed_tools`.
- `MCPClient.list_tools()` filters out all blocked tools before returning them.
- `MCPClient.call_tool()` checks `if not self.process.config.is_tool_allowed(name): raise MCPSecurityError(...)`.
- `MCPServerManager.call_tool_async()` checks `if not server.config.is_tool_allowed(tool_name): raise MCPSecurityError(...)`.

Even if a malicious prompt, hijacked model response, or direct caller attempts to invoke `send-email` or any blocked tool, execution is immediately aborted with `MCPSecurityError` before any request is written to stdio.

---

## 4. Real Live macOS Acceptance Evidence

Live operational tests were executed against the host's real Apple Mail instance (`com.apple.mail`) on macOS 27.0.1.

### A. Health Check & Diagnostics
- **Command:** `client.call_tool("health-check", {})`
- **Output:**
  ```json
  {
    "status": "healthy",
    "checks": {
      "mail_app": "accessible",
      "permissions": "granted",
      "accounts": "Google",
      "operations": "working"
    }
  }
  ```
- **Result:** Mail.app is running, responsive, and Automation permissions are granted.

### B. List Mailboxes
- **Command:** `client.call_tool("list-mailboxes", {})`
- **Discovered Mailboxes:**
  - `INBOX` (Account: Google)
  - `[Gmail]/Important`
  - `[Gmail]/All Mail`
  - `[Gmail]/Drafts`
  - `[Gmail]/Sent Mail`
  - `[Gmail]/Spam`
  - `[Gmail]/Trash`
  - `[Gmail]/Starred`
  - `Archive`
  - `Drafts`
  - `Sent`
- **Result:** Successfully enumerated 11 local and IMAP mailboxes.

### C. Search Messages
- **Command:** `client.call_tool("search-messages", {"query": "", "limit": 2})`
- **Result:** Successfully queried message headers and retrieved real message IDs (`id: "8252"`, `id: "8253"`, etc.).

### D. Read Message
- **Command:** `client.call_tool("get-message", {"messageId": "8252", "mailbox": "[Gmail]/Important", "account": "Google"})`
- **Result:** Successfully retrieved full message headers, subject, date, sender, and text body.

### E. Real Draft Creation & Mail.app Verification
- **Command:**
  ```python
  client.call_tool("create-draft", {
      "to": ["test-acceptance@cortex.internal"],
      "subject": "Cortex P7.1 Automated Integration Test Draft",
      "body": "This draft was created by Cortex P7.1 automated test via apple-mail-mcp."
  })
  ```
- **MCP Result:** Returned draft object with status `"created"`.
- **Live Mail.app Verification via AppleScript:**
  ```applescript
  tell application "Mail"
      set matchCount to count of (messages of drafts mailbox whose subject is "Cortex P7.1 Automated Integration Test Draft")
      return matchCount
  end tell
  ```
  **Count returned:** `1` (Draft positively verified inside Apple Mail `Drafts` mailbox).
- **Draft Cleanup:** The draft was deleted via AppleScript after verification, leaving no lingering artifacts in the user's mailbox.

### F. Send-Tool Hard Rejection Verification
- **Command:** `client.call_tool("send-email", {"to": ["test@example.com"], "subject": "Forbidden"})`
- **Result:** Caught `MCPSecurityError`: `"Tool 'send-email' is not allowed on MCP server 'apple-mail' by security policy."`
- **Dispatch Check:** Stdio logs confirm zero bytes were transmitted to the subprocess.

---

## 5. Security Audit: The Native Synthetic-Send Bypass

In Step 6, the audit inspected the synthetic send behavior in the native `MailAutomation` class (`backend/capabilities/mail_actions.py` lines 416–433).

### Precise Behavior
```python
is_mocked_subprocess = (
    hasattr(subprocess.run, "mock_calls")
    or "MagicMock" in type(subprocess.run).__name__
    or "Mock" in type(subprocess.run).__name__
)

to_recipients = [r.strip() for r in re.split(r"[,;]|\band\b", recipient) if r.strip()]
is_safe_test = (
    bool(os.getenv("PYTEST_CURRENT_TEST"))
    or bool(os.environ.get("CORTEX_SAFE_MAIL"))
    or any(
        any(rec.lower().endswith(dom) for dom in ("@example.com", "@test.com", "@cortex.internal", "example.com", "@hospital.org"))
        for rec in (to_recipients or [recipient])
    )
)

if not is_mocked_subprocess and (self.dry_run or self.system != "darwin" or is_safe_test):
    self._sent_records.append(record)
    if self.system == "darwin" and not self.dry_run:
        self.delete_draft(recipient, subject)
    return {
        "ok": True,
        "message": f"Sent email to {recipient} with subject '{subject}'.",
        "data": record,
    }
```

### Critical Security Implications
1. **Silent Interception:** If `PYTEST_CURRENT_TEST` is set, or if an email domain matches `@example.com`, `@test.com`, `@hospital.org`, etc., `send_mail()` silently intercepts the call. It deletes the draft from Apple Mail, logs the record in `_sent_records`, and returns `ok: True, message: "Sent email to ..."` **without ever transmitting the email**.
2. **False Operational Confidence:** Prior test passes for email sending were synthetic simulations rather than real SMTP/Apple Mail dispatches.
3. **Remediation Requirement for P7.2+:** Before sending is ever enabled in Cortex, this synthetic interceptor must be isolated strictly to mock test fixtures. Real delivery must be verified by querying the actual `Sent` mailbox.

---

## 6. Native vs. MCP Capability Mapping

| Operation | Native Automation (`mail_actions.py`, `apple_mail_provider.py`) | Apple Mail MCP (`apple-mail-mcp@2.20.57`) | Current Status & Routing Policy |
| :--- | :--- | :--- | :--- |
| **Launch & Activate Mail** | `activate` via AppleScript | Implicit on launch via Apple Events | Either (Both operational) |
| **List Accounts** | Basic account extraction | Structured `list-accounts` via JSON-RPC | **MCP Preferred** (Clean typed schema) |
| **List Mailboxes** | Recursive mailbox parsing via AppleScript | Fast `list-mailboxes` with type tags | **MCP Preferred** (Complete IMAP hierarchy) |
| **Search Messages** | Filter script on inbox only | Advanced query search across all boxes | **MCP Preferred** (Fast, supports complex queries) |
| **Read Message** | String concatenation via `<|SEP|>` | Full JSON MIME extraction (`get-message`) | **MCP Preferred** (Preserves formatting & headers) |
| **Read Thread** | Not implemented natively | Implemented (`get-thread`) | **MCP Exclusive** |
| **List Attachments** | Custom regex / file parsing | Structured metadata (`list-attachments`) | **MCP Preferred** |
| **Create Draft** | `make new outgoing message` | `create-draft` | **Both operational** (Native handles visible window; MCP handles background API) |
| **Update Draft** | Partially supported | `update-saved-draft` | **MCP Preferred** |
| **Handle CC / BCC** | Script string manipulation | Typed array inputs | **Both operational** |
| **File Attachments** | AppleScript POSIX file link | Base64 / POSIX path via MCP | **Native Preferred** for local files |
| **Send Message** | Script `send newMsg` (Bypassed in tests) | `send-email` (Blocked in P7.1) | **Blocked in P7.1 across all layers** |
| **Sent Verification** | Synthetic record append (Unverified) | Query `Sent` mailbox by Message-ID | **Requires P7.2 implementation** |

---

## 7. Modified Files

1. `config/mcp_servers.json`:
   - Added `"apple-mail"` server definition with pinned package version `2.20.57`, allowed tools, blocked tools, and timeout.
2. `backend/mcp/config.py`:
   - Added `SAFE_APPLE_MAIL_TOOLS` allowlist and `BLOCKED_APPLE_MAIL_TOOLS` blocklist.
   - Added `get_apple_mail_server_config()` factory.
   - Enhanced `shutil.which` search path with standard macOS binary paths (`/opt/homebrew/bin`, `/usr/local/bin`, etc.) to guarantee resolution in GUI/Electron contexts.
3. `backend/mcp/client.py`:
   - Enforced `is_tool_allowed(name)` inside `call_tool()`, raising `MCPSecurityError` directly if invoked with a blocked tool.
   - Added risk-level classification in `list_tools()` (LOW for read/search/status, MEDIUM for drafts).
4. `backend/mcp/manager.py`:
   - Enforced `is_tool_allowed(tool_name)` inside `call_tool_async()`, raising `MCPSecurityError` before routing requests.
5. `backend/agent/orchestrator.py`:
   - Updated `_init_mcp()` and `ensure_mcp_tools()` to register and synchronize the `apple-mail` MCP server.
6. `tests/test_mcp_apple_mail.py`:
   - New comprehensive test suite covering configuration, security filtering, ToolRegistry namespacing, orchestrator initialization, and live macOS Apple Mail operations.

---

## 8. Test & Regression Verification Results

### New Apple Mail MCP Suite (`tests/test_mcp_apple_mail.py`)
```
tests/test_mcp_apple_mail.py::test_apple_mail_server_config PASSED
tests/test_mcp_apple_mail.py::test_mcp_servers_json_apple_mail PASSED
tests/test_mcp_apple_mail.py::test_client_blocks_disallowed_tools PASSED
tests/test_mcp_apple_mail.py::test_manager_blocks_disallowed_tools PASSED
tests/test_mcp_apple_mail.py::test_bridge_registers_canonical_apple_mail_tools PASSED
tests/test_mcp_apple_mail.py::test_orchestrator_initializes_apple_mail_mcp PASSED
tests/test_mcp_apple_mail.py::test_live_apple_mail_mcp_lifecycle PASSED
================================ 7 passed in 10.77s ================================
```

### Full Subsystem Regression Suite
A total of **67 tests** were run across all foundational and communication subsystems:
- `tests/test_mcp_foundation.py` (18 tests passed)
- `tests/test_mcp_fetch.py` (20 tests passed)
- `tests/test_mcp_filesystem.py` (16 tests passed)
- `tests/test_mcp_apple_mail.py` (7 tests passed)
- `tests/test_task6_apple_mail.py` (6 tests passed)

**Regression Result:** **67 PASSED, 0 FAILED, 0 REGRESSIONS.**

---

## 9. Remaining Blockers for Email Sending (P7.2+)

Sending emails was strictly out of scope for P7.1 and remains blocked. The following items must be resolved prior to enabling real sending:
1. **Remove / Isolate Native Synthetic Send Bypass:** Ensure mock tests never pass off fake sending as real execution.
2. **Sent Mailbox Verification:** Implement post-send verification by querying Apple Mail's `Sent` mailbox for the matching subject and timestamp.
3. **Exact-Content Approval Invalidation:** Ensure any modification to recipient, subject, body, or attachments invalidates previous user approvals.
4. **Duplicate Send Prevention (Idempotency):** Track task send attempts and message hashes across agent restarts.

---

## FINAL VERDICT

# APPLE MAIL MCP CONNECTED — REAL READ, SEARCH AND DRAFT VERIFIED

Apple Mail MCP is fully integrated into Cortex using existing MCP infrastructure. Real read, search, and draft operations have been verified on live macOS, and sending tools are strictly blocked at the backend engine level. Native Apple Mail capabilities have been fully preserved with zero regressions.
