# CORTEX AGENT — P7.4.1 INDEPENDENT ACCEPTANCE AUDIT
## Strict Read-Only Verification — Conversational Email Remediation

**Audit scope:** P7.4.1 Remediation & Final Acceptance  
**Previous audit reference:** `docs/P7_4_INDEPENDENT_ACCEPTANCE_AUDIT.md` (*READY WITH BLOCKERS*)  
**Implementation report reference:** `docs/P7_4_1_IMPLEMENTATION_REPORT.md`  
**Audit mode:** Strict read-only  
**Target Environment:** macOS 15.0+ (Darwin 24.6.0), Python 3.9.6, Node.js v20+, Apple Mail MCP Server v2.20.57  
**Host Connected Accounts:** 1 real account (`Google <gsunilkumar1307@gmail.com>`)  
**Safety Gate:** `CORTEX_ALLOW_REAL_EMAIL_SEND` unset/OFF (Zero real outbound emails transmitted)  

---

## 1. FINAL ACCEPTANCE VERDICT

### **VERDICT: ACCEPTED**

All five readiness blockers (two P0s, three P1s) and the P2 defense-in-depth finding documented in `docs/P7_4_INDEPENDENT_ACCEPTANCE_AUDIT.md` have been independently verified as completely and correctly resolved. The codebase is fully compliant with all architectural, security, and conversational requirements. Zero regressions were detected across the entire test matrix (73/73 tests passing).

---

## 2. BLOCKER RESOLUTION SUMMARY TABLE

| Finding ID | Severity | Original Blocker Description | Remediation Verified | Status |
|---|---|---|---|---|
| **B1** | **P0** | `approve()` hash reconstruction omitted `in_reply_to` & `references` and defaulted `sender_account` to `"Primary Account"`, causing 100% false-positive rejection of reply/forward draft approvals. | `approve()` passes `in_reply_to` and `references` to `EmailDraft`, removes `"Primary Account"` fallback, and routes `REPLY_MAIL` & `FORWARD_MAIL`. | **RESOLVED** |
| **B2** | **P0** | `_resolve_sending_account()` silently auto-selected sending account based on recipient domain match alone without user confirmation in multi-account setups. | Domain matching now acts strictly as supporting evidence, suggesting the account with `is_ambiguous=True` and requiring explicit user confirmation. | **RESOLVED** |
| **B3** | **P1** | `REPLY_MAIL` used internal Apple Mail numeric IDs (`<8502>`) instead of RFC 2822 `Message-ID`, violating live MCP `create-draft` regex schema `^<[^<>\s@]+@[^<>\s@]+>$`. | Real RFC 2822 `Message-ID` headers are retrieved from MCP `get-message-headers` with native AppleScript fallback; IDs are strictly validated. | **RESOLVED** |
| **B4** | **P1** | Dative natural-language phrasing (`"Send him a mail asking about the application status."`) leaked instruction text and third-person pronouns into draft body. | Added dative prefix stripping and extended inquiry/participle patterns, cleanly normalizing dative phrasing into professional first-person correspondence. | **RESOLVED** |
| **B5** | **P1** | Expiration policy mismatch: restart rehydration strictly enforced 300 seconds (5 min), while in-flight `approve()` permitted 15 minutes (900s). | Standardized approval expiration across the entire application lifecycle to exactly 300 seconds. | **RESOLVED** |
| **B6** | **P2** | `MailAutomation.send_mail()` routed accounts containing `"gmail"` to `self.manager.gmail.send_message()` prior to checking `CORTEX_ALLOW_REAL_EMAIL_SEND`. | Global `CORTEX_ALLOW_REAL_EMAIL_SEND == "1"` check moved to the top of `send_mail()`, protecting all providers before dispatch. | **RESOLVED** |

---

## 3. DETAILED SOURCE-LEVEL EVIDENCE BY AUDIT AREA

### Area 1: P0 — Reply/Forward Approval Hash Reconstruction
- **Inspection Targets:** `backend/agent/orchestrator.py` (L3217–L3275), `backend/agent/email_engine.py` (L90–L120)
- **Verified Code:**
  ```python
  # backend/agent/orchestrator.py
  if task.command in (TaskCommand.SEND_MAIL, TaskCommand.DRAFT_MAIL, TaskCommand.REPLY_MAIL, TaskCommand.FORWARD_MAIL):
      ...
      expected_hash = task.params.get("approval_hash")
      if expected_hash:
          current_hash = EmailDraft(
              recipient=task.params.get("recipient_email") or task.params.get("recipient", ""),
              subject=task.params.get("subject", ""),
              body=task.params.get("formatted_body") or task.params.get("body", ""),
              sender_account=task.params.get("sender_account") or task.params.get("account") or "",
              attachments=task.params.get("attachments", []),
              cc=task.params.get("cc", []),
              bcc=task.params.get("bcc", []),
              in_reply_to=task.params.get("in_reply_to"),
              references=task.params.get("references", []),
          ).compute_hash()
  ```
- **Audit Findings:**
  1. Full field parity exists between `EmailDraft.canonicalize()` and `EmailDraft` reconstruction in `approve()`.
  2. `in_reply_to` and `references` are now faithfully bound to the approval payload.
  3. `sender_account` no longer defaults to `"Primary Account"`, eliminating hash mismatches when the account is an empty string.
  4. Both `TaskCommand.REPLY_MAIL` and `TaskCommand.FORWARD_MAIL` are routed through the cryptographic verification logic.
  5. Empirical testing confirms:
     - Legitimate reply approval (`in_reply_to='<thesis-123@univ.edu>'`, `references=['<thesis-123@univ.edu>']`): `status: completed`, `error: None`.
     - Tampered threading metadata (`in_reply_to='<tampered@evil.com>'`): `status: waiting_approval`, `error: "Approval invalidated: draft content was modified"`.

---

### Area 2: P0 — Sending-Account Confirmation Policy
- **Inspection Targets:** `backend/agent/orchestrator.py` (L770–L795, L2505–L2525, L2620–L2645, L2775–L2795)
- **Verified Code:**
  ```python
  # backend/agent/orchestrator.py
  # 3. Recipient domain / affiliation match (Supporting evidence only — MUST NOT silently auto-select in multi-account setups)
  if recipient and "@" in recipient and len(available_accounts) > 1:
      rec_domain = recipient.split("@", 1)[1].lower().strip()
      suggested_acc = None
      for acc in available_accounts:
          acc_email = acc.get("email", "").lower()
          if "@" in acc_email:
              acc_domain = acc_email.split("@", 1)[1].strip()
              if rec_domain == acc_domain or (rec_domain.endswith(".edu.in") and "college" in acc.get("name", "").lower()):
                  suggested_acc = acc
                  break
      if suggested_acc:
          sug_label = f"{suggested_acc.get('name')} <{suggested_acc.get('email')}>" if suggested_acc.get("email") else suggested_acc.get("name")
          acc_names = [f"{a.get('name')} ({a.get('email')})" if a.get("email") else a.get("name") for a in available_accounts]
          prompt = (
              f"You have multiple email accounts connected ({', '.join(acc_names)}). "
              f"Based on the recipient's domain (@{rec_domain}), would you like to send this from {sug_label}, or another account?"
          )
          return "", True, prompt
  ```
- **Audit Findings:**
  1. Recipient domain matching never automatically selects an account when multiple accounts are connected (`acc = ""`, `is_ambiguous = True`).
  2. The prompt specifically surfaces the matching account as a suggestion and asks the user to choose or confirm.
  3. Single-account configurations continue to default directly without prompt (`is_ambiguous = False`).
  4. Explicit user instructions (`"from Work"`) and thread context (`lead_msg["account"]`) take precedence and select the account directly.
  5. The selected account is persisted in `task.params["sender_account"]` and cryptographically bound to the approval hash. Attempting to switch accounts after approval request invalidates the approval.

---

### Area 3: P1 — RFC 2822 Threading Verification
- **Inspection Targets:** `backend/capabilities/mail_actions.py` (L474–L490, L1570–L1625), `backend/agent/email_engine.py` (L1115–L1135, L1190–L1215), `backend/agent/orchestrator.py` (L2505–L2530)
- **Live Tool Schema Inspection:**
  Live inspection of Apple Mail MCP server `create-draft` tool schema confirms:
  ```json
  "inReplyTo": {
    "type": "string",
    "maxLength": 998,
    "pattern": "^<[^<>\\s@]+@[^<>\\s@]+>$"
  },
  "references": {
    "type": "array",
    "items": {
      "type": "string",
      "maxLength": 998,
      "pattern": "^<[^<>\\s@]+@[^<>\\s@]+>$"
    }
  }
  ```
- **Audit Findings:**
  1. `MailAutomation.get_message_headers()` extracts genuine RFC 2822 Message-IDs via MCP tool `get-message-headers`.
  2. On macOS fallback, `osascript` directly queries `message id of foundMsg` from Mail.app, obtaining real RFC Message-IDs (e.g. `<9f36e35d...-111858455@google.com>`).
  3. Live extraction against real mailbox message `8502` retrieved:
     `<MA5P287MB48353ED2E634B6DC4B5BA566AB7A2@MA5P287MB4835.INDP287.PROD.OUTLOOK.COM>`.
  4. `ProfessionalEmailEngine.compose_reply()` and `compose_forward()` validate all IDs against `^<[^<>\s@]+@[^<>\s@]+>$`. Non-RFC local IDs (such as `<8502>`) are never assigned to threading headers.
  5. `MailAutomation.draft_mail()` sanitizes `inReplyTo` and `references` against the RFC pattern before calling MCP `create-draft`.

---

### Area 4: P1 — Dative Instruction Normalization
- **Inspection Targets:** `backend/agent/email_engine.py` (L318–L385)
- **Audit Findings:**
  Empirical testing across required conversational test cases:
  1. `"Send him a mail asking about the application status."`
     → `"I am writing to inquire regarding the application status. Could you please provide an update on this?"` (**PASS**)
  2. `"Send Rahul a mail asking when the internship starts."`
     → `"Could you please let me know when the internship starts?"` (**PASS**)
  3. `"Write her a mail saying that I'll attend."`
     → `"I'll attend."` (**PASS**)
  4. `"Draft them a mail asking for an update."`
     → `"I would like to respectfully request an update."` (**PASS**)
  5. `"Ask him when the interview is scheduled."`
     → `"Could you please let me know when the interview is scheduled?"` (**PASS**)
  6. `"Tell her that I'll attend."`
     → `"I would like to let you know that I'll attend."` (**PASS**)
  7. No instruction fragments (e.g., `"him a mail"`, `"her an email"`) leak into the generated output.
  8. Factual meaning and tone are preserved without fabricated details.

---

### Area 5: P1 — Consistent Approval Expiry
- **Inspection Targets:** `backend/agent/orchestrator.py` (L450–L465, L3255–L3275)
- **Audit Findings:**
  1. Exact boundary enforcement:
     - Task requested 295 seconds ago: approved cleanly (`status: completed`).
     - Task requested 305 seconds ago: rejected with `"Approval expired: action was requested more than 5 minutes ago. Please re-approve."` (`status: waiting_approval`).
  2. Restart rehydration parity:
     - Task restored after shutdown requested 350 seconds ago: transitions immediately to `NEEDS_ATTENTION` with audit event `"Approval window expired during shutdown. Fresh approval required."`.
  3. Single-use and replay protection:
     - `TaskStore.consume_approval()` prevents double-spending of approval hashes. Replaying an approval returns `"Approval replay detected: this cryptographic approval was already consumed."`.

---

### Area 6: P2 — Provider-Agnostic Send Safety
- **Inspection Targets:** `backend/capabilities/mail_actions.py` (L685–L715)
- **Audit Findings:**
  1. `allow_real_send = os.environ.get("CORTEX_ALLOW_REAL_EMAIL_SEND") == "1"` check is positioned on lines 693–713, preceding all provider routing (lines 715+).
  2. Both Gmail and Apple Mail account dispatches return `ok: False`, `delivery_status: BLOCKED` with error `"SEND_BLOCKED_BY_POLICY"` when `CORTEX_ALLOW_REAL_EMAIL_SEND` is unset.
  3. Disallowed MCP transmission tools (`send-email`, `send-serial-email`, `reply-to-message`, `forward-message`) remain hard-blocked in `backend/mcp/config.py` and `backend/mcp/client.py`.
  4. Zero real outbound emails were transmitted during any stage of this audit.

---

## 4. TEST MATRIX & REGRESSION VERIFICATION

All 7 test suites were executed sequentially via pytest in the clean virtual environment:

```bash
/Users/gsunilkumar/.gemini/antigravity/scratch/cortex/venv/bin/python3 -m pytest \
    tests/test_conversational_email_p7_4_1.py \
    tests/test_conversational_email_p7_4.py \
    tests/test_mail_search_remediation_p7_3_1.py \
    tests/test_mail_send_safety.py \
    tests/test_mail_search_and_accounts.py \
    tests/test_mcp_apple_mail.py \
    tests/test_task6_apple_mail.py -v
```

### Complete Test Results

| Test Suite | Tests | Passed | Failed | Duration | Scope Verified |
|---|---|---|---|---|---|
| `tests/test_conversational_email_p7_4_1.py` | 12 | **12** | 0 | 5.60s | P7.4.1 Remediations (Approval hash, domain policy, RFC Message-ID, dative phrases, 300s window, send gate) |
| `tests/test_conversational_email_p7_4.py` | 9 | **9** | 0 | 5.12s | P7.4: Intent classification, thread composition, MCP tools delegation, restart rehydration, send safety |
| `tests/test_mail_search_remediation_p7_3_1.py` | 10 | **10** | 0 | 15.87s | P7.3.1: Date parser, range filters, deduplication, MCP search routing, live MCP verification |
| `tests/test_mail_send_safety.py` | 16 | **16** | 0 | 11.85s | P7.2: Send safety, single-use approval, replay rejection, Sent mailbox verification, atomic reservation |
| `tests/test_mail_search_and_accounts.py` | 13 | **13** | 0 | 14.92s | P7.3: Dynamic account discovery, multi-account search, query parsing, concurrency |
| `tests/test_mcp_apple_mail.py` | 7 | **7** | 0 | 25.10s | P7.1: MCP Apple Mail server lifecycle, tool registration, bridge sync, safety blocks |
| `tests/test_task6_apple_mail.py` | 6 | **6** | 0 | 17.61s | P7.1: Multi-turn draft resolution, refinement, cancellation, replay protection |
| **TOTAL** | **73** | **73** | **0** | **96.07s** | **100% PASS RATE** |

### Desktop Frontend Build Verification
`apps/desktop` Vite build was executed in read-only verification mode:
```bash
cd apps/desktop && npm run build
```
- Modules transformed: 1575
- Output artifacts:
  - `dist/index.html` (1.10 kB)
  - `dist/assets/index-CiuD6QJ5.css` (32.47 kB)
  - `dist/assets/index-CEYSskt6.js` (219.32 kB)
- Result: **0 errors, build completed in 1.20s**

---

## 5. LIVE MCP & APPLE MAIL ENVIRONMENT VERIFICATION

Independent live queries were executed against the host's active Apple Mail and MCP processes:

- **Apple Mail MCP Server Version:** v2.20.57 (`@modelcontextprotocol/server-apple-mail` via `npx -y`)
- **Total Tools Discovered:** 15 canonical tools registered and accessible.
- **Disallowed Tools Verification:** `send-email`, `send-serial-email`, `reply-to-message`, and `forward-message` are confirmed blocked by client and bridge enforcement.
- **Account Discovery:** Discovered 1 real connected account:
  `Google <gsunilkumar1307@gmail.com>`.
- **Live Message Retrieval:** Message ID `8502` retrieved with subject `Registration Successful – VTU Industry Awareness Quiz 2026`.
- **Live Header Extraction:**
  - `rfc_message_id`: `<MA5P287MB48353ED2E634B6DC4B5BA566AB7A2@MA5P287MB4835.INDP287.PROD.OUTLOOK.COM>`
  - Format matches `^<[^<>\s@]+@[^<>\s@]+>$` exactly.
  - No synthetic `<8502>` tokens were generated or passed to MCP.
- **Integrity Guarantee:** Zero messages were modified, zero drafts were left lingering in the user's Sent/Trash folders, and zero emails were transmitted.

---

## 6. AUDIT CONCLUSION & NEXT STEPS

Phase P7.4.1 has closed all identified architectural, policy, schema, and normalization blockers. Cortex now reliably performs conversational reply and forward preparation, enforces strict confirmation on ambiguous sending accounts, preserves threading headers across MCP and AppleScript boundaries, cleans dative user inputs, standardizes cryptographic approval lifetimes, and hardens the global send safety gate across all providers.

### Recommendation
1. **Transition P7.4 to ACCEPTED.**
2. The email foundation (P7.1), send safety hardening (P7.2), intelligent search (P7.3 / P7.3.1), and conversational email intelligence (P7.4 / P7.4.1) are complete, safe, and robust.
3. The project is ready to proceed to Phase P8 or the next scheduled milestone in accordance with Cortex product roadmap.
