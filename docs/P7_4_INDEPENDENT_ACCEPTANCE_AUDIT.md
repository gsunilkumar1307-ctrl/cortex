# CORTEX AGENT — P7.4 INDEPENDENT ACCEPTANCE AUDIT
## CONVERSATIONAL EMAIL INTELLIGENCE
### Strict Read-Only Acceptance Audit Report

---

## 1. AUDIT METADATA & EXECUTIVE SUMMARY

| Audit Parameter | Evidence & Details |
|---|---|
| **Audit Mode** | **Strict Read-Only Inspection** (No modifications, no Git commits, zero emails sent) |
| **Phase Audited** | **P7.4 — Conversational Email Intelligence** |
| **Audit Date** | November 18, 2026 |
| **Test Execution Summary** | **61/61 PASSED** across 6 test suites in 85.62s |
| **Frontend Build** | **SUCCESS** (`npm run build` in 742ms with 0 errors) |
| **Live MCP Integration** | **CONFIRMED** (`apple-mail-mcp` v2.20.57 starts, health-check passes, 15 tools discovered) |
| **Send Safety Status** | **HARD BLOCKED** (`CORTEX_ALLOW_REAL_EMAIL_SEND` unset; MCP sending tools disallowed) |
| **FINAL AUDIT VERDICT** | **READY WITH BLOCKERS** |

### Executive Summary
Cortex Agent Phase P7.4 demonstrates substantial architectural progress toward conversational email intelligence on macOS. The foundation established in P7.1 through P7.3.1 has been preserved, with 61/61 regression tests passing and the Vite desktop frontend building cleanly.

However, a strict source-code and execution trace against the original product requirements, MCP tool schemas, and safety rules revealed **two P0 blockers and three P1 blockers** that prevent clean sign-off:
1. **[P0 Blocker] Silent Account Selection via Recipient Domain:** In `_resolve_sending_account`, recipient domain matching (Tier 3) automatically and silently selects a sending account without user confirmation, violating Rule 4 (*"A recipient's email domain alone MUST NOT determine the sending account"*).
2. **[P0 Blocker] Cryptographic Approval Rejection on Replies/Forwards:** In `approve()`, reconstructed draft hash computation omits `in_reply_to` and `references`, causing all approved reply and forward drafts to fail cryptographic hash verification (`current_hash != expected_hash`) and be rejected with `"Draft changed after approval requested"`.
3. **[P1 Blocker] Numeric ID vs. RFC 2822 Message-ID Mismatch in Threading Headers:** Reply draft preparation injects internal Mail.app numeric IDs (`<8502>`) instead of RFC 2822 `Message-ID` tokens (`<id@domain>`) because `get_message_headers` is not invoked. This violates the Apple Mail MCP `create-draft` regex schema (`pattern: ^<[^<>\s@]+@[^<>\s@]+>$`), causing MCP draft creation to fail and drop into AppleScript fallback.
4. **[P1 Blocker] Instruction Text & Dative Pronoun Leakage:** Instruction normalization fails on dative phrasing (`"Send him a mail asking about the application status"`), emitting `"him a mail asking about the application status."` directly into the email body.
5. **[P1 Blocker] Inconsistent Approval Expiration Policy:** Task rehydration enforces a 300-second approval window, but `approve()` enforces a 15-minute (`timedelta(minutes=15)`) window.

---

## 2. ORIGINAL P7.4 BLOCKERS & INDEPENDENT VERIFICATION STATUS

| Audit Baseline Blocker | Initial Verdict | P7.4 Audit Finding | Current Status |
|---|---|---|---|
| **Blocker 1: Email Thread Intelligence & Reply/Forward Draft Preparation** | READY WITH BLOCKERS | Commands `REPLY_MAIL` and `FORWARD_MAIL` added; `compose_reply` and `compose_forward` format quotations and headers. However, `approve()` hash mismatch blocks reply confirmation, and numeric IDs fail MCP `create-draft` regex. | **PARTIALLY RESOLVED (P0/P1 Blockers Remain)** |
| **Blocker 2: Contextual Sending-Account Selection** | READY WITH BLOCKERS | Removed hardcoded `"Primary Account"`. Dynamic discovery works. However, Tier 3 silently selects sending accounts based on recipient domain alone, violating Rule 4. | **BLOCKED (P0 Safety Blocker)** |
| **Blocker 3: Indirect Instruction Normalization** | READY WITH BLOCKERS | Conversational normalization works for `"Ask him about..."`, `"Tell her that..."`, and pronoun mapping. However, dative commands (`"Send him a mail asking..."`) leak into draft bodies. | **PARTIALLY RESOLVED (P1 Blocker Remains)** |
| **Blocker 4: Draft & Task Rehydration After Process Restarts** | READY WITH BLOCKERS | Rehydration restores `type: "email_draft"`, `step: "confirm_send"`, and `EmailDraft`. Expiration and tampering checks work on restart, but expiration threshold is inconsistent with `approve()` (300s vs 15m). | **PARTIALLY RESOLVED (P1 Blocker Remains)** |

---

## 3. DETAILED SOURCE-LEVEL EVIDENCE BY AUDIT AREA

### Area 1: Reply & Forward Intelligence
- **Routing & Execution:**
  - `backend/core/contracts.py` (L1392-L1408): Correctly routes `"reply to ..."`, `"write a reply ..."`, and `"forward ..."` to `TaskCommand.REPLY_MAIL` and `FORWARD_MAIL`. Informational queries route to `SEARCH_MAIL`.
  - `backend/agent/orchestrator.py` (L2462-L2670): Implements `REPLY_MAIL` and `FORWARD_MAIL` execution handlers.
- **MCP Tool Invocation & Schema Failure:**
  - In `mail_actions.py` (L1400-L1590): `get_message`, `get_thread`, and `get_message_headers` properly call `apple-mail` MCP tools `get-message`, `get-thread`, and `get-message-headers` with parameter `{"id": str(message_id)}`.
  - **Schema Defect:** In `orchestrator.py` (L2498), `_execute_task` calls `get_message(str(msg_id))` which retrieves the internal Apple Mail message ID (e.g., `8502`). It does **not** call `get_message_headers` to obtain the RFC 2822 `Message-ID` header (e.g., `<CAGx...-abc@mail.gmail.com>`).
  - In `compose_reply` (L1118), `clean_msg_id = f"<{msg_id}>"` creates `"<8502>"`.
  - In `mail_actions.py` (L480), `create-draft` passes `inReplyTo: "<8502>"`.
  - **Live MCP Tool Schema Evidence:**
    ```json
    "inReplyTo": {
      "type": "string",
      "maxLength": 998,
      "pattern": "^<[^<>\\s@]+@[^<>\\s@]+>$"
    }
    ```
  - Empirical verification: `re.match(r"^<[^<>\s@]+@[^<>\s@]+>$", "<8502>")` is `False`.
  - Result: MCP `create-draft` rejects the call with schema validation failure, forcing silent fallback to AppleScript.

### Area 2: Sending-Account Resolution (Critical Check)
- **Code Location:** `backend/agent/orchestrator.py`, lines 770-780:
  ```python
  # 3. Recipient domain / affiliation match
  if recipient and "@" in recipient and available_accounts:
      rec_domain = recipient.split("@", 1)[1].lower().strip()
      for acc in available_accounts:
          acc_email = acc.get("email", "").lower()
          if "@" in acc_email:
              acc_domain = acc_email.split("@", 1)[1].strip()
              if rec_domain == acc_domain or (rec_domain.endswith(".edu.in") and "college" in acc.get("name", "").lower()):
                  label = f"{acc.get('name')} <{acc.get('email')}>" if acc.get("email") else acc.get("name")
                  return label, False, ""
  ```
- **Policy Assessment:**
  - The audit instructions explicitly specify:
    > *"A recipient's email domain alone MUST NOT determine the sending account. Determine whether this can silently select an account. If it can, classify this as a blocker. Domain matching may only be supporting evidence, not sufficient authorization for account selection."*
  - **Finding:** If a user has both a Personal account (`me@personal.com`) and an Enterprise account (`me@enterprise.org`), and drafts an email to `colleague@enterprise.org`, line 777 matches `enterprise.org == enterprise.org` and immediately returns `Work <me@enterprise.org>, False, ""`. Because `is_ambiguous` is `False`, Cortex **silently selects** the account without asking the user.
  - This is classified as a **P0 Blocker**.

### Area 3: Natural-Language Instruction Normalization
- **Code Location:** `backend/agent/email_engine.py`, lines 319-370.
- **Empirical Execution Results:**
  - `"Ask Rahul about the internship."` → `"I am writing to inquire regarding the internship. Could you please provide an update on this?"` (**PASS**)
  - `"Ask him when the interview is scheduled."` → `"Could you please let me know when the interview is scheduled?"` (**PASS**)
  - `"Tell her that I'll attend."` → `"I would like to let you know that I'll attend."` (**PASS**)
  - `"Let them know I am interested."` → `"I wanted to let you know that I am interested."` (**PASS**)
  - `"Send him a mail asking about the application status."` → `"him a mail asking about the application status."` (**FAIL**)
- **Finding:**
  - In `convert_instruction_to_recipient_content`, the regex for stripping meta-prefixes only strips `"Send "`. The dative phrase `"him a mail"` is not stripped. None of the conversion patterns match, and raw instruction text with third-person pronoun `"him"` is directly emitted into the body.
  - Classified as a **P1 Blocker**.

### Area 4: Draft & Task Rehydration & Approval Integrity
- **Rehydration State Restoration:**
  - `backend/agent/orchestrator.py` (L505-L560): Active tasks awaiting approval are properly restored with `type: "email_draft"`, `step: "confirm_send"`, and reconstructed `EmailDraft`.
  - Multi-turn refinement on rehydrated drafts (`"Make it shorter and more formal"`) works seamlessly.
- **Approval Window Discrepancy:**
  - Rehydration (`orchestrator.py` L463): Enforces strict `300` seconds (5 minutes). Tasks older than 300s transition to `NEEDS_ATTENTION`.
  - Real-time approval (`orchestrator.py` L3199): Enforces `timedelta(minutes=15)` (900 seconds).
  - Finding: An active session allows approval up to 15 minutes, but a restart invalidates approval after 5 minutes.
- **Cryptographic Hash Failure on Reply/Forward Drafts:**
  - In `EmailDraft.compute_hash()` (`email_engine.py` L112-L135), `in_reply_to` and `references` are cryptographically bound to the draft hash.
  - In `CortexOrchestrator.approve()` (`orchestrator.py` L3179-L3187):
    ```python
    current_hash = EmailDraft(
        recipient=task.params.get("recipient_email") or task.params.get("recipient", ""),
        subject=task.params.get("subject", ""),
        body=task.params.get("formatted_body") or task.params.get("body", ""),
        sender_account=task.params.get("sender_account") or task.params.get("account") or "Primary Account",
        attachments=task.params.get("attachments", []),
        cc=task.params.get("cc", []),
        bcc=task.params.get("bcc", []),
    ).compute_hash()
    ```
  - **Empirical Evidence:** When verifying a reply draft with `in_reply_to='<msg-123@example.com>'`:
    - `expected_hash`: `6986dece348b87d5231dd104eb880ab04d6fc9e5a858624a8ebe63e801a85171`
    - `current_hash`: `3206386164ff0e192bc734bbe4c2768e3fb6887762afcf555f272323a328c20c`
    - `expected_hash == current_hash`: `False`.
  - Result: Every valid reply and forward draft approval is rejected by Cortex with `"Approval invalidated: draft content was modified"`.
  - Classified as a **P0 Blocker**.

### Area 5: Safety Verification & Send Hard-Block
- **Inspection of All Sending Paths:**
  - `send-email`, `send-serial-email`, `reply-to-message`, `forward-message`: Hard-blocked in `backend/mcp/config.py` and `backend/mcp/client.py`.
  - `MailAutomation.send_mail()`: Guarded by `CORTEX_ALLOW_REAL_EMAIL_SEND == "1"` for AppleScript outgoing messages.
  - **Observation (P2):** Lines 672-684 of `backend/capabilities/mail_actions.py` forward accounts containing `"gmail"` or `"@gmail.com"` to `self.manager.gmail.send_message()` *before* checking `CORTEX_ALLOW_REAL_EMAIL_SEND`. In default configuration, `gmail_prov.sandbox` is True (dry-run), but the environment variable check should sit at the top of the function.

---

## 4. TEST EXECUTION & REGRESSION RESULTS

All 6 test suites were executed sequentially via pytest in the clean virtual environment:

```bash
/Users/gsunilkumar/.gemini/antigravity/scratch/cortex/venv/bin/python3 -m pytest \
    tests/test_conversational_email_p7_4.py \
    tests/test_mail_search_remediation_p7_3_1.py \
    tests/test_mail_send_safety.py \
    tests/test_mail_search_and_accounts.py \
    tests/test_mcp_apple_mail.py \
    tests/test_task6_apple_mail.py -v
```

### Exact Results Summary
- **Total Tests:** 61
- **Passed:** 61
- **Failed:** 0
- **Duration:** 85.62s
- **Warnings:** 4 (deprecation warnings for Python 3.9 and google-generativeai)

| Suite File | Tests | Result | Duration | Scope Verified |
|---|---|---|---|---|
| `tests/test_conversational_email_p7_4.py` | 9 | 9 PASSED | 5.2s | P7.4: Reply/forward intents, indirect instructions, composition, MCP delegation, account selection, restart rehydration, dry-run safety |
| `tests/test_mail_search_remediation_p7_3_1.py` | 10 | 10 PASSED | 25.1s | P7.3.1: Date parser, range filters, error on invalid date, deduplication, MCP search routing, partial coverage |
| `tests/test_mail_send_safety.py` | 16 | 16 PASSED | 12.3s | P7.2: Send safety, single-use approval, replay rejection, bounded Sent mailbox verification, atomic reservation |
| `tests/test_mail_search_and_accounts.py` | 13 | 13 PASSED | 15.4s | P7.3: Dynamic account discovery, multi-account search, query parsing, sent verification correlation, concurrency |
| `tests/test_mcp_apple_mail.py` | 7 | 7 PASSED | 8.2s | P7.1: MCP config, server registration, client/manager tool blocking, canonical tool bridge, live lifecycle |
| `tests/test_task6_apple_mail.py` | 6 | 6 PASSED | 19.4s | Task 6 End-to-End: Draft resolution, clarification, follow-up editing, draft cancellation, send approval consumption |

---

## 5. LIVE INTEGRATION EVIDENCE

Live inspection was performed against the running macOS host environment:
1. **MCP Server Startup & Discovery:**
   - Started `apple-mail-mcp` v2.20.57 via `MCPProcess` and `MCPClient`.
   - Successfully discovered 15 canonical tools: `search-messages`, `get-message`, `get-message-headers`, `get-thread`, `list-messages`, `update-saved-draft`, `create-draft`, `list-attachments`, `list-mailboxes`, `get-unread-count`, `list-accounts`, `health-check`, `doctor`, `get-mail-stats`, `get-sync-status`.
2. **Live Health Check Tool:**
   - Returned: `✓ All checks passed (Mail.app accessible, permissions granted, Found 1 account(s): Google, 8 mailbox(es) in Google)`.
3. **Live Mailbox Listing Tool:**
   - Successfully retrieved 12 live mailboxes from Mail.app (`[Gmail]/Important`, `[Gmail]/Starred`, `[Gmail]/All Mail`, `[Gmail]/Drafts`, `[Gmail]/Sent Mail`, `INBOX`, etc.).
4. **Live Message Retrieval Tool:**
   - Called `get-message` on real message ID `8502`. Returned real message content.
   - Called `get-message-headers` on message ID `8502`. Returned real RFC 2822 header stream.
5. **Multiple Connected Accounts:**
   - Live Apple Mail host currently has 1 connected account (`Google <gsunilkumar1307@gmail.com>`).
   - Multiple connected account logic was verified via mock fixtures and unit tests; multi-account switching cannot be fully tested against real Mail.app data on this host without a second configured account.

---

## 6. FRONTEND BUILD VERIFICATION

- Executed `npm run build` in `apps/desktop`:
  ```text
  > cortex-desktop-app@0.1.0 build
  > vite build

  ✓ 1575 modules transformed.
  dist/index.html                   1.10 kB │ gzip:  0.55 kB
  dist/assets/index-CiuD6QJ5.css   32.47 kB │ gzip:  6.60 kB
  dist/assets/index-CEYSskt6.js   219.32 kB │ gzip: 66.05 kB
  ✓ built in 742ms
  ```
- Result: **CLEAN BUILD (0 errors, 0 warnings)**.

---

## 7. REMAINING BLOCKERS RANKED BY SEVERITY

### P0 Blockers (Must Fix Prior to Sign-Off)
1. **P0-1: Silent Recipient-Domain Account Selection**
   - **File:** `backend/agent/orchestrator.py`, lines 770-780.
   - **Impact:** Automatically selects sending account based on recipient domain alone, violating explicit safety rule.
   - **Remediation:** Remove automatic selection in Tier 3; recipient domain should only be presented as a suggestion in the clarification prompt when multiple accounts exist.
2. **P0-2: Approval Hash Mismatch on Reply and Forward Drafts**
   - **File:** `backend/agent/orchestrator.py`, lines 3179-3187.
   - **Impact:** `approve()` fails to pass `in_reply_to` and `references` when reconstructing `EmailDraft` to verify `approval_hash`, causing all reply and forward approvals to be rejected as tampered.
   - **Remediation:** Pass `in_reply_to=task.params.get("in_reply_to")` and `references=task.params.get("references")` into `EmailDraft` in `approve()`. Also remove `"Primary Account"` fallback in line 3183.

### P1 Blockers (High Priority Functional Remediation)
3. **P1-1: Numeric ID vs. RFC 2822 Message-ID Mismatch in Threading Headers**
   - **Files:** `backend/agent/orchestrator.py` (L2498) and `backend/capabilities/mail_actions.py` (L476-L483).
   - **Impact:** Numeric ID `<8502>` violates Apple Mail MCP `create-draft` regex schema (`pattern: ^<[^<>\s@]+@[^<>\s@]+>$`), causing MCP tool execution failure and AppleScript fallback.
   - **Remediation:** Call `get_message_headers` in `_execute_task(REPLY_MAIL)` to extract the real RFC 2822 `Message-ID` header. Validate that `inReplyTo` matches RFC 2822 token format before passing to MCP.
4. **P1-2: Dative Phrasing Instruction Leakage in Body Normalization**
   - **File:** `backend/agent/email_engine.py`, lines 319-325.
   - **Impact:** Phrases like `"Send him a mail asking about the application status"` leak `"him a mail asking about..."` into the draft body.
   - **Remediation:** Add dative meta-prefixes (e.g. `send\s+(?:him|her|them|[a-zA-Z0-9_\-]+)\s+(?:an?\s+)?(?:email|mail|message)\s+(?:asking|inquiring|saying)?`) to `meta_prefixes`.
5. **P1-3: Approval Window Expiration Inconsistency Across Execution Paths**
   - **File:** `backend/agent/orchestrator.py`, line 3199 vs line 463.
   - **Impact:** Inconsistent window (300s in rehydration vs 900s in `approve()`).
   - **Remediation:** Standardize the approval expiration window to 300 seconds across all code paths.

### P2 Observations (Defense-in-Depth)
6. **P2-1: Gmail Provider Branch Precedes Environment Variable Check**
   - **File:** `backend/capabilities/mail_actions.py`, lines 672-684.
   - **Impact:** Moves Gmail provider invocation ahead of `CORTEX_ALLOW_REAL_EMAIL_SEND` check.
   - **Remediation:** Move the `allow_real_send` check to the top of `send_mail` before any provider branching.

---

## 8. FINAL AUDIT VERDICT & RECOMMENDED NEXT PHASE

### Final Verdict: READY WITH BLOCKERS

While Cortex's conversational email infrastructure is functional and passes regression testing, the system cannot be awarded an unconditional ACCEPTED verdict due to:
1. Silent account selection violating Rule 4.
2. Inability to approve reply/forward drafts due to hash reconstruction omission in `approve()`.
3. Schema rejection in live MCP `create-draft` due to numeric ID usage in threading headers.

### Recommended Next Phase: P7.4.1 — Conversational Email Remediation
A focused, architecture-preserving remediation phase (P7.4.1) should be scheduled to close these 5 blockers:
1. Fix `approve()` hash reconstruction to include `in_reply_to` and `references`.
2. Update `_resolve_sending_account` so recipient domain match suggests rather than silently selects.
3. Call `get_message_headers` during reply resolution to supply valid RFC 2822 `Message-ID` tokens to `create-draft`.
4. Fix dative prefix stripping in `convert_instruction_to_recipient_content`.
5. Standardize 300-second approval window in `approve()`.
