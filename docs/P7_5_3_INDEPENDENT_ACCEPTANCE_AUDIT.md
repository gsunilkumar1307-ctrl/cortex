# CORTEX AGENT — P7.5.3 INDEPENDENT ACCEPTANCE AUDIT

**Audit Date:** 2026-11-19  
**Audit Scope:** P7.5.3 Email Send Safety Gate Correction  
**Audit Mode:** Strict Read-Only Verification  
**Audited Artifacts:**
- Implementation Report: `docs/P7_5_3_IMPLEMENTATION_REPORT.md`
- Core Capabilities: `backend/capabilities/safety.py`, `backend/capabilities/mail_actions.py`, `backend/capabilities/device_actions.py`
- Providers & Integrations: `backend/integrations/email/apple_mail_provider.py`, `backend/integrations/email/gmail_provider.py`, `backend/integrations/email/manager.py`
- MCP Boundaries: `backend/mcp/config.py`, `backend/mcp/client.py`, `backend/mcp/models.py`, `backend/mcp/manager.py`
- Agent Orchestration: `backend/agent/orchestrator.py`
- Test Suites: `tests/test_conversational_email_p7_5_3.py` (12 tests) and the full 10-suite regression matrix (109 tests total)
- Desktop App: `apps/desktop` (Vite build)

---

## 1. EXECUTIVE VERDICT

### **VERDICT: ACCEPTED**

The critical P0 email send-gate vulnerability identified in the P7.5.2 audit—where Python environment variable truthiness allowed non-empty strings like `"0"` and `"false"` to potentially satisfy generic truthiness checks—is **completely and authoritatively resolved**.

### Verification Highlights
1. **Centralized Enforcement:** Defined in `backend/capabilities/safety.py` as:
   ```python
   def is_real_email_send_allowed() -> bool:
       return os.getenv("CORTEX_ALLOW_REAL_EMAIL_SEND", "").strip() == "1"
   ```
2. **Strict Value Matrix:** Validated across 17 test cases. Only the exact value `"1"` (and intentionally whitespace-normalized equivalents `" 1 "`, `"1\n"`) returns `True`. All other values (`None`/unset, `""`, `"0"`, `"false"`, `"False"`, `"no"`, `"off"`, `"true"`, `"yes"`, `"None"`, `"2"`, `"-1"`) strictly evaluate to `False` (`BLOCK`).
3. **Defense-in-Depth Layering:** Every outbound transmission route enforces `is_real_email_send_allowed()` at its entry point before any AppleScript construction, REST call, or subprocess invocation. Direct invocations of lower-level providers (`AppleMailProvider`, `GmailProvider`, `MailProviderManager`, `DeviceAutomation`) cannot bypass the gate.
4. **MCP Boundary Integrity:** Apple Mail MCP outbound sending tools (`send-email`, `send-serial-email`, `reply-to-message`, `forward-message`) remain strictly blocked in `backend/mcp/config.py` and raise `MCPSecurityError` if invoked directly.
5. **Supervised Workflow Preservation:** Cryptographic approval tokens (SHA-256 draft integrity, single-use consumption, 300-second expiration, replay protection) remain fully functional and **cannot bypass** the safety gate.
6. **Regression Suite Compliance:** 10 out of 10 test suites (109 total tests) passed with 100% compliance in a single pytest run (100.50s).
7. **Zero Outbound Transmission:** The active runtime environment maintained `CORTEX_ALLOW_REAL_EMAIL_SEND` unset (`None`). Zero real emails were sent, forwarded, or replied to, and zero mailbox records were modified.

---

## 2. COMPLETE OUTBOUND-PATH INVENTORY

An exhaustive audit of the codebase identified 10 potential outbound transmission routes. Each route was inspected and tested:

| # | Outbound Route / Component | Entry Point | Dispatch Mechanism | Safety Gate Placement | Bypass Possible? | Reachability & Status |
|---|---|---|---|---|:---:|---|
| **1** | `MailAutomation.send_mail()` | `backend/capabilities/mail_actions.py:642` | AppleScript / Gmail Provider | Lines 703–714: Evaluates `is_real_email_send_allowed()` immediately after dry-run check, prior to provider routing or AppleScript. | **NO** | Active primary route. Returns `MailDeliveryStatus.BLOCKED` with `SEND_BLOCKED_BY_POLICY`. |
| **2** | `MailProviderManager.send_message()` | `backend/integrations/email/manager.py:137` | Provider Delegation | Lines 148–159: Evaluates `is_real_email_send_allowed()` before `get_provider_for_account()`. | **NO** | Direct provider manager entry. Returns `BLOCKED`. |
| **3** | `AppleMailProvider.send_message()` | `backend/integrations/email/apple_mail_provider.py:354` | AppleScript `osascript` (`make new outgoing message`, `visible:false`) | Lines 393–415: Evaluates `is_real_email_send_allowed()` before assembling AppleScript. | **NO** | Direct Apple Mail provider entry. Subprocess is never called. |
| **4** | `GmailProvider.send_message()` | `backend/integrations/email/gmail_provider.py:336` | Google REST API (`urllib.request.urlopen`) | Lines 347–362: Evaluates `is_real_email_send_allowed()` at top of method before authentication or network I/O. | **NO** | Direct Gmail provider entry. `urlopen` is never called. |
| **5** | `DeviceAutomation._send_mail()` | `backend/capabilities/device_actions.py:803` | `self._get_mail().send_mail()` | Lines 814–820: Evaluates `is_real_email_send_allowed()` before accessing `mail_inst`. | **NO** | Fallback capability handler. Returns `DeviceActionResult(False, ...)`. |
| **6** | Apple Mail MCP `send-email` | `backend/mcp/client.py:164` | External MCP Server Process | `backend/mcp/config.py:309` (`BLOCKED_APPLE_MAIL_TOOLS`); checked in `client.py:164` and `manager.py:224`. | **NO** | Strictly blocked at MCP client layer; raises `MCPSecurityError`. |
| **7** | Apple Mail MCP `send-serial-email`, `reply-to-message`, `forward-message` | `backend/mcp/client.py:164` | External MCP Server Process | `BLOCKED_APPLE_MAIL_TOOLS` list. | **NO** | Strictly blocked at client layer; filtered from tool discovery. |
| **8** | Conversational New Email Send | `backend/agent/orchestrator.py:1213-1221` | `approve()` $\rightarrow$ `_execute()` $\rightarrow$ `MailAutomation.send_mail()` | Dual-gated: requires valid approval token, then hits `send_mail()` gate. | **NO** | Verified blocked when `CORTEX_ALLOW_REAL_EMAIL_SEND != "1"`. |
| **9** | Conversational Reply Send | `backend/agent/orchestrator.py:1213-1221` | Transitions `REPLY_MAIL` to `SEND_MAIL` $\rightarrow$ `send_mail()` | RFC threading preserved; send execution hits `send_mail()` gate. | **NO** | Verified blocked without subprocess dispatch. |
| **10** | Conversational Forward Send | `backend/agent/orchestrator.py:1213-1221` | Transitions `FORWARD_MAIL` to `SEND_MAIL` $\rightarrow$ `send_mail()` | Forward content preserved; send execution hits `send_mail()` gate. | **NO** | Verified blocked without subprocess dispatch. |

---

## 3. CENTRALIZED GATE SOURCE INSPECTION

### Implementation Location
`backend/capabilities/safety.py:129-138`:
```python
def is_real_email_send_allowed() -> bool:
    """
    Mandatory safety gate: Outbound real email transmission is permitted ONLY when
    os.getenv("CORTEX_ALLOW_REAL_EMAIL_SEND", "").strip() == "1".

    All other values (unset, empty string, '0', 'false', 'False', 'no', 'off',
    'true', 'yes', etc.) evaluate to False (BLOCK).
    """
    import os
    return os.getenv("CORTEX_ALLOW_REAL_EMAIL_SEND", "").strip() == "1"
```

### Import Fallback Architecture
Across all callers (`mail_actions.py`, `apple_mail_provider.py`, `gmail_provider.py`, `manager.py`, `device_actions.py`), imports follow a resilient pattern:
```python
try:
    from backend.capabilities.safety import is_real_email_send_allowed
except ImportError:
    try:
        from capabilities.safety import is_real_email_send_allowed
    except ImportError:
        def is_real_email_send_allowed() -> bool:
            return os.getenv("CORTEX_ALLOW_REAL_EMAIL_SEND", "").strip() == "1"
```
**Audit Finding:** Even under standalone execution or altered `sys.path` where imports might fail, the fallback function implements the **identical strict check**. There are no stale, legacy, or weaker checks remaining in the codebase.

---

## 4. ENVIRONMENT-VALUE SECURITY MATRIX

The environment variable evaluation was independently tested using an isolated Python test harness:

| Value Evaluated | Expected Authorization | Actual Evaluated Result | Outbound Dispatch Permitted? | Status |
|---|:---:|:---:|:---:|:---:|
| `None` (unset) | **BLOCK** (`False`) | `False` | **NO** | **PASS** |
| `""` (empty string) | **BLOCK** (`False`) | `False` | **NO** | **PASS** |
| `" "` (single space) | **BLOCK** (`False`) | `False` | **NO** | **PASS** |
| `"   \t\n  "` (whitespace) | **BLOCK** (`False`) | `False` | **NO** | **PASS** |
| `"0"` | **BLOCK** (`False`) | `False` | **NO** | **PASS** |
| `"false"` | **BLOCK** (`False`) | `False` | **NO** | **PASS** |
| `"False"` | **BLOCK** (`False`) | `False` | **NO** | **PASS** |
| `"no"` | **BLOCK** (`False`) | `False` | **NO** | **PASS** |
| `"off"` | **BLOCK** (`False`) | `False` | **NO** | **PASS** |
| `"true"` | **BLOCK** (`False`) | `False` | **NO** | **PASS** |
| `"yes"` | **BLOCK** (`False`) | `False` | **NO** | **PASS** |
| `"None"` | **BLOCK** (`False`) | `False` | **NO** | **PASS** |
| `"2"` | **BLOCK** (`False`) | `False` | **NO** | **PASS** |
| `"-1"` | **BLOCK** (`False`) | `False` | **NO** | **PASS** |
| `"1"` | **ALLOW** (`True`) | `True` | Yes (Mocked only) | **PASS** |
| `" 1 "` | **ALLOW** (`True`) | `True` | Yes (Mocked only) | **PASS** |
| `"1\n"` | **ALLOW** (`True`) | `True` | Yes (Mocked only) | **PASS** |

**Confirmation:** In the developer environment runtime, `CORTEX_ALLOW_REAL_EMAIL_SEND` evaluated to `None`. No test or process inherits an enabled state.

---

## 5. DIRECT PROVIDER DISPATCH & BYPASS TESTING

Each provider and dispatch handler was directly invoked with `CORTEX_ALLOW_REAL_EMAIL_SEND=0` while monitoring low-level dispatch functions (`subprocess.run` and `urllib.request.urlopen`):

1. **`MailAutomation.send_mail()` Direct Call:**
   - Result: `ok=False`, `delivery_status="blocked"`, `error="SEND_BLOCKED_BY_POLICY"`.
   - `subprocess.run` call count: **0**.
   - `urllib.request.urlopen` call count: **0**.
2. **`AppleMailProvider.send_message()` Direct Call:**
   - Result: `ok=False`, `delivery_status="blocked"`, `error="SEND_BLOCKED_BY_POLICY"`.
   - `subprocess.run` call count: **0**.
3. **`GmailProvider.send_message()` Direct Call:**
   - Result: `ok=False`, `delivery_status="blocked"`, `error="SEND_BLOCKED_BY_POLICY"`.
   - `urllib.request.urlopen` call count: **0**.
4. **`MailProviderManager.send_message()` Direct Call:**
   - Result: `ok=False`, `delivery_status="blocked"`, `error="SEND_BLOCKED_BY_POLICY"`.
   - Provider delegation was halted before `provider.send_message()` was invoked.
5. **`DeviceAutomation._send_mail()` Direct Call:**
   - Result: `ok=False`, `data={"error": "SEND_BLOCKED_BY_POLICY"}`.
   - Mail automation instance was never dispatched.
6. **Positive Authorization with Mocked Dispatch (`"1"` Case):**
   - In an isolated test where `CORTEX_ALLOW_REAL_EMAIL_SEND="1"` was patched, `AppleMailProvider` reached `subprocess.run` (mocked) and `GmailProvider` reached `urllib.request.urlopen` (mocked).
   - Zero real network sockets or OS scripts were executed.

---

## 6. MCP CLIENT-VERSUS-SERVER ENFORCEMENT DISTINCTION

An independent architectural review was conducted regarding MCP tool blocking:

1. **Server-Side Capability:** The external Apple Mail MCP package (`apple-mail-mcp`) provides implementations for `send-email`, `send-serial-email`, `reply-to-message`, and `forward-message`. The external MCP server process does *not* natively block these tools if called by an arbitrary MCP client.
2. **Cortex Client Enforcement:** Cortex enforces tool safety strictly inside its MCP client architecture:
   - **Configuration:** `backend/mcp/config.py:309-314` specifies `BLOCKED_APPLE_MAIL_TOOLS`.
   - **Catalog Filtering:** During server initialization (`MCPClient.list_tools()`), blocked tools are stripped from the advertised tool catalog so the LLM planner never sees or selects them.
   - **Call-Level Interception:** If an instruction attempts to execute a blocked tool by name, `MCPClient.call_tool()` (`backend/mcp/client.py:164`) and `MCPManager.call_tool()` (`backend/mcp/manager.py:224`) check `server.config.is_tool_allowed(name)`. If blocked, execution immediately aborts by raising `MCPSecurityError` before sending any JSON-RPC request across the stdio pipe.
3. **Conclusion:** The MCP sending block is **enforced by Cortex's MCP client layer**, not by the external server. This containment is complete and verified.

---

## 7. SIMULATION AND DRY-RUN SEMANTICS

`MailAutomation.send_mail()` evaluates `self.dry_run` before `is_real_email_send_allowed()`:

```python
# In dry-run mode, simulate send without real external transmission
if self.dry_run:
    self._sent_records.append(record)
    return {
        "ok": True,
        "status": "sent",
        "delivery_status": "sent",
        "message": f"Dry-run simulated send to {recipient} with subject '{subject}'.",
        "data": record,
    }

# Mandatory P7.5.3 Safety Gate
if not is_real_email_send_allowed():
    ...
```

### Safety Assessment of Dry-Run Positioning
1. **Zero Outbound Risk:** In dry-run mode (`self.dry_run == True`), the method appends to an internal in-memory list (`_sent_records`) and returns immediately. No AppleScript, subprocess, REST API, or network socket is reachable.
2. **Clear Distinction:** The return payload explicitly states `"Dry-run simulated send..."` and marks `record["dry_run"] = True`.
3. **Production Safety:** In production (`dry_run=False`), execution proceeds directly to the safety gate check `if not is_real_email_send_allowed():`, which blocks transmission.
4. **Verdict on Dry-Run:** Safe. Evaluating dry-run before the environment gate is standard for test harness simulation and cannot lead to unintended real transmission.

---

## 8. APPROVAL LIFECYCLE AND POLICY INTEGRITY

The cryptographic approval workflow was audited to confirm that approval tokens cannot bypass the safety policy:

1. **Hash Integrity:** `EmailDraft.compute_hash()` covers `recipient`, `subject`, `body`, `sender_account`, `cc`, `bcc`, `in_reply_to`, and `references`. Any edit or tampering produces a hash mismatch and rejects approval.
2. **Single-Use Consumption:** Approval sets `task.params["approval_consumed"] = True`. Any replay attempt immediately raises a replay error.
3. **TTL Expiration:** Approval attempts on tasks older than 300 seconds are rejected with `"Approval expired"`.
4. **Gate Independence:** In `test_10_approval_lifecycle_hash_expiry_and_replay`, a valid, non-expired, single-use approval token was submitted while `CORTEX_ALLOW_REAL_EMAIL_SEND=0`. The approval was validated, but outbound execution was strictly halted by the safety gate with `SEND_BLOCKED_BY_POLICY`.
5. **Verdict:** Approval and authorization are cleanly decoupled. Approval confirms user intent; the safety gate enforces system-level transmission policy.

---

## 9. REGRESSION TEST RECONCILIATION

### Reconciliation Analysis
In the P7.5.2 audit, 9 test suites were reported with 97 total passing tests. In the P7.5.3 implementation report, 10 suites were reported with 109 total passing tests.

An inspection of the test suite files was performed to reconcile individual test counts:
- The 9 historical test suites were **not altered or depleted**. Their actual pytest collection counts are:
  - `test_conversational_email_p7_5_2.py`: 11
  - `test_conversational_email_p7_5_1.py`: 13
  - `test_conversational_email_p7_4_1.py`: 12
  - `test_conversational_email_p7_4.py`: 9
  - `test_mail_search_remediation_p7_3_1.py`: 10
  - `test_mail_send_safety.py`: 16
  - `test_mail_search_and_accounts.py`: 13
  - `test_mcp_apple_mail.py`: 7
  - `test_task6_apple_mail.py`: 6
  - *Subtotal:* **97 tests** (exact match to P7.5.2 accepted baseline).
- The new suite `tests/test_conversational_email_p7_5_3.py` adds **12 tests**.
- *Total Genuine Count:* **109 tests**.
- The row counts reported in the P7.5.3 implementation table contained typographical transcription errors across several rows, but the total test count (109) and the underlying test implementations are 100% genuine and verified.

### Execution Record
All 10 suites were executed simultaneously in one single pytest command:

```bash
/Users/gsunilkumar/.gemini/antigravity/scratch/cortex/venv/bin/python3 -m pytest \
  tests/test_conversational_email_p7_5_3.py \
  tests/test_conversational_email_p7_5_2.py \
  tests/test_conversational_email_p7_5_1.py \
  tests/test_conversational_email_p7_4_1.py \
  tests/test_conversational_email_p7_4.py \
  tests/test_mail_search_remediation_p7_3_1.py \
  tests/test_mail_send_safety.py \
  tests/test_mail_search_and_accounts.py \
  tests/test_mcp_apple_mail.py \
  tests/test_task6_apple_mail.py
```

**Results:**
- **Collected:** 109 items
- **Passed:** 109 items
- **Failed:** 0
- **Skipped:** 0
- **Duration:** 100.50s (0:01:40)

---

## 10. FRONTEND AND INTEGRATION REGRESSION

The Electron desktop application (`apps/desktop`) was compiled for production:

```bash
cd apps/desktop && npm run build
```

- **Vite Build Outcome:** Succeeded in 739ms.
- **Transformed Modules:** 1575 modules.
- **Assets Emitted:**
  - `dist/index.html` (1.10 kB)
  - `dist/assets/index-CiuD6QJ5.css` (32.47 kB)
  - `dist/assets/index-CEYSskt6.js` (219.32 kB)
- **Error Count:** 0 errors, 0 warnings.
- **UI Safety Feedback:** Inspecting `apps/desktop/src/App.jsx` confirms that `failed` and `execution_blocked` task events are rendered with distinct warning/error badges (`status-bad`, `status-warn`). A blocked email send is never reported as sent in the UI.

---

## 11. REMAINING GAPS AND LIMITATIONS

No P0 or P1 blockers remain.

### P2 (Defense-in-Depth Note)
- **External MCP Server Direct Invocation:** If an external process communicates directly with the Apple Mail MCP server outside of Cortex (bypassing Cortex's `MCPClient` and `MCPServerConfig`), the external tool could theoretically execute `send-email`. Within Cortex, this is fully mitigated by client-level tool filtering and security checks.

---

## 12. GIT AND MAILBOX SAFETY CONFIRMATION

- **Git Working Tree:** No Git commits, stages, or pushes were performed during this audit.
- **Mailbox Contents:** No emails were sent, forwarded, replied to, or deleted in real Apple Mail or Gmail accounts.
- **Active Environment:** `CORTEX_ALLOW_REAL_EMAIL_SEND` remained unset (`None`).

---

## 13. CONCLUSION & FINAL SIGN-OFF

Phase **P7.5.3 — Email Send Safety Gate Correction** successfully resolves the environment-variable truthiness vulnerability. Outbound email transmission across all routes is strictly guarded by the centralized `is_real_email_send_allowed()` check. All acceptance criteria have been satisfied.

**Verdict: ACCEPTED**
