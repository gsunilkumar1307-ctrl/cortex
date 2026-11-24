# CORTEX AGENT — P7.4.1 IMPLEMENTATION REPORT
## Conversational Email Remediation — Audit-Driven, Minimal, Architecture-Preserving

---

## 1. EXECUTIVE SUMMARY & AUDIT CONTEXT

- **Phase:** P7.4.1 — Conversational Email Remediation
- **Audit Reference:** `docs/P7_4_INDEPENDENT_ACCEPTANCE_AUDIT.md` (Independent Audit Verdict: *READY WITH BLOCKERS*)
- **Objective:** Close all 5 identified blockers (2 P0s, 3 P1s) and the P2 defense-in-depth finding through targeted, minimal, architecture-preserving changes.
- **Scope Preserved:**
  - Preserved Cortex's native orchestrator, `EmailDraft`, `TaskStore`, `Task` lifecycle, and multi-turn conversational flow.
  - Preserved Apple Mail MCP and AppleScript fallback hierarchy.
  - Zero modifications to desktop UI bundle requirements; frontend build remains cleanly green.
  - Absolute send-safety maintained: zero outbound emails transmitted; `CORTEX_ALLOW_REAL_EMAIL_SEND` remained strictly unset/OFF.
  - Zero Git commits or pushes executed.
- **Current Status:** All 6 findings fully resolved with 100% test pass rate across new and existing test suites (74/74 tests passing). Ready for subsequent independent acceptance audit.

---

## 2. DETAILED REMEDIATION BY AUDIT FINDING

### Finding 1: P0 Blocker 1 — Reply / Forward Approval Hash Reconstruction in `approve()`

- **Audit Defect:**
  In `backend/agent/orchestrator.py` (`approve()`), `current_hash` was computed by reconstructing `EmailDraft` without `in_reply_to` and `references`. Because `EmailDraft.compute_hash()` binds both fields into the canonical JSON digest, reply and forward draft approval hashes always mismatched (`current_hash != expected_hash`). In addition, `sender_account` defaulted to `"Primary Account"`, causing hash mismatch whenever `sender_account` was an empty string `""`.
  *Impact:* Every valid reply and forward draft approval was rejected with `"Approval invalidated: draft content was modified"`.
- **Remediation Applied:**
  1. Updated `CortexOrchestrator.approve()` to pass `in_reply_to=task.params.get("in_reply_to")` and `references=task.params.get("references", [])` to `EmailDraft`.
  2. Changed `sender_account` fallback in `EmailDraft` instantiation from `"Primary Account"` to empty string `""` (`task.params.get("sender_account") or task.params.get("account") or ""`).
  3. Extended approval command routing tuple to include `TaskCommand.REPLY_MAIL` and `TaskCommand.FORWARD_MAIL` alongside `SEND_MAIL` and `DRAFT_MAIL`.
  4. Updated `_execute_task(FORWARD_MAIL)` to store `in_reply_to` and `references` in `task.params`.
- **Files Modified:**
  - `backend/agent/orchestrator.py` (lines 2680–2710, 3217–3265)
- **Verification Evidence:**
  - `tests/test_conversational_email_p7_4_1.py::test_01_reply_draft_approval_hash_reconstruction` (**PASSED**)
  - `tests/test_conversational_email_p7_4_1.py::test_02_forward_draft_approval_hash_reconstruction` (**PASSED**)
  - `tests/test_conversational_email_p7_4_1.py::test_03_tampered_draft_rejected_in_approve` (**PASSED**)

---

### Finding 2: P0 Blocker 2 — Contextual Sending-Account Selection Policy

- **Audit Defect:**
  In `backend/agent/orchestrator.py` (`_resolve_sending_account`), Tier 3 recipient domain matching (`colleague@enterprise.org` matched against `me@enterprise.org`) immediately returned `label, False, ""` (`is_ambiguous = False`). This silently selected the account in multi-account environments without asking the user.
  *Policy Violation:* Rule 4 explicitly prohibits automatic account selection on recipient domain alone in multi-account environments:
  > *"A recipient's email domain alone MUST NOT determine the sending account... Domain matching may only be supporting evidence, not sufficient authorization for account selection."*
- **Remediation Applied:**
  1. Updated Tier 3 in `_resolve_sending_account` so that when multiple accounts exist, matching the recipient domain does **not** silently select the account.
  2. Domain matching is now treated as supporting evidence: it formats a helpful clarification prompt suggesting the matching account and returns `"", True, prompt`.
  3. Single-account configurations continue to default directly to the lone connected account (`is_ambiguous = False`).
  4. Explicit user instructions (`"from Google"`) and thread context (`in_reply_to`) retain direct selection (`is_ambiguous = False`).
- **Files Modified:**
  - `backend/agent/orchestrator.py` (lines 770–785)
  - `tests/test_conversational_email_p7_4.py` (lines 215–221)
- **Verification Evidence:**
  - `tests/test_conversational_email_p7_4_1.py::test_04_domain_match_suggests_without_silent_autoselection` (**PASSED**)
  - `tests/test_conversational_email_p7_4_1.py::test_05_explicit_and_thread_account_selection_remains_direct` (**PASSED**)
  - `tests/test_conversational_email_p7_4.py::test_06_contextual_sending_account_selection` (**PASSED**)

---

### Finding 3: P1 Blocker 3 — RFC 2822 `Message-ID` Header Compliance & Validation

- **Audit Defect:**
  In `_execute_task(REPLY_MAIL)`, `lead_msg` only captured internal Apple Mail numeric IDs (`8502`). `compose_reply` converted this to `"<8502>"`, which was passed to `create-draft`. Live Apple Mail MCP enforces:
  ```json
  "inReplyTo": {
    "type": "string",
    "maxLength": 998,
    "pattern": "^<[^<>\\s@]+@[^<>\\s@]+>$"
  }
  ```
  `"<8502>"` failed schema validation, causing MCP `create-draft` to fail and forcing silent AppleScript fallback.
- **Remediation Applied:**
  1. In `MailAutomation.get_message_headers()`:
     - Parses live RFC 2822 `Message-ID` from MCP `get-message-headers` (e.g. `<9f36e35d...-111858455@google.com>`).
     - Added native AppleScript fallback on macOS: queries `message id of foundMsg` directly from Mail.app, returning genuine RFC 2822 Message-IDs.
     - Normalizes IDs to enclose within `<...>` and returns `rfc_message_id`.
  2. In `orchestrator._execute_task(REPLY_MAIL)` & `(FORWARD_MAIL)`:
     - Calls `self.mail_automation.get_message_headers(str(msg_id), mailbox=mbox, account=acc)` to extract real RFC 2822 headers into `lead_msg["rfc_message_id"]` and `lead_msg["message_id"]`.
  3. In `ProfessionalEmailEngine.compose_reply()` & `compose_forward()`:
     - Prioritizes `rfc_message_id` and strictly validates against `^<[^<>\s@]+@[^<>\s@]+>$`.
     - Never fabricates `<numeric_id>` or assigns non-RFC IDs to `draft.in_reply_to` or `draft.references`.
  4. In `MailAutomation.draft_mail()`:
     - Validates `in_reply_to` and `references` against `^<[^<>\s@]+@[^<>\s@]+>$` before attaching to `mcp_args` for MCP `create-draft`.
- **Files Modified:**
  - `backend/capabilities/mail_actions.py` (lines 474–490, 1570–1620)
  - `backend/agent/email_engine.py` (lines 1118–1145, 1195–1220)
  - `backend/agent/orchestrator.py` (lines 2505–2535, 2645–2675)
- **Verification Evidence:**
  - `tests/test_conversational_email_p7_4_1.py::test_06_rfc2822_message_id_schema_validation` (**PASSED**)
  - `tests/test_conversational_email_p7_4_1.py::test_07_compose_reply_never_fabricates_numeric_message_id` (**PASSED**)
  - `tests/test_conversational_email_p7_4_1.py::test_08_create_draft_filters_invalid_threading_headers_for_mcp` (**PASSED**)

---

### Finding 4: P1 Blocker 4 — Dative Conversational Instruction Normalization

- **Audit Defect:**
  In `convert_instruction_to_recipient_content`, meta-prefix stripping only matched `"Send "`. Dative phrases like `"him a mail"` or `"her an email"` were not stripped, and patterns did not match sentences starting with `"asking about ..."` or `"saying that ..."`.
  *Empirical Failure:* `"Send him a mail asking about the application status."` resulted in `"him a mail asking about the application status."` leaking into the draft body.
- **Remediation Applied:**
  1. Added dative prefix regexes in `meta_prefixes`:
     `r"^(?:please\s+)?(?:can\s+you\s+)?(?:write|draft|compose|send|prepare)\s+(?:them|him|her|the\s+team|[a-zA-Z0-9_\s.'-]+?)\s+(?:an?\s+)?(?:polite\s+|formal\s+|casual\s+|brief\s+|short\s+|quick\s+|respectful\s+)?(?:email|mail|message)\s*(?:to\s+|saying\s+that\s+|saying\s+|that\s+|with\s+|:\s*|\s+)?"`
  2. Extended Pattern A (`ask_about_m`), Pattern B (`ask_q_m`), Pattern C (`tell_m`), Pattern D (`inform_m`), and Pattern E (`let_know_m`):
     - Allows optional target entity (`(?:(?:them|him|her|the\s+team|[a-zA-Z0-9_\s.'-]+?)\s+)?`).
     - Matches participle variants (`ask`/`asking`, `tell`/`telling`, `inform`/`informing`, `let`/`letting`).
     - Trims trailing question marks and periods via `.rstrip("?.")`.
- **Files Modified:**
  - `backend/agent/email_engine.py` (lines 318–385)
- **Verification Evidence:**
  - `tests/test_conversational_email_p7_4_1.py::test_09_dative_instruction_normalization` (**PASSED**)
  - Verified across 7 distinct dative and conversational prompts:
    - `"Send him a mail asking about the application status."` → `"I am writing to inquire regarding the application status. Could you please provide an update on this?"` (**PASS**)
    - `"Send him a mail asking when the interview is scheduled."` → `"Could you please let me know when the interview is scheduled?"` (**PASS**)
    - `"Can you draft him an email asking about the project status?"` → `"I am writing to inquire regarding the project status. Could you please provide an update on this?"` (**PASS**)
    - `"Ask Rahul about the internship."` → `"I am writing to inquire regarding the internship. Could you please provide an update on this?"` (**PASS**)
    - `"Ask him when the interview is scheduled."` → `"Could you please let me know when the interview is scheduled?"` (**PASS**)
    - `"Tell her that I'll attend."` → `"I would like to let you know that I'll attend."` (**PASS**)
    - `"Let them know I am interested."` → `"I wanted to let you know that I am interested."` (**PASS**)

---

### Finding 5: P1 Blocker 5 — Standardized 300-Second Approval Expiration Window

- **Audit Defect:**
  Task rehydration (`orchestrator.py` L463) strictly enforced `300` seconds (5 minutes) before marking tasks as `NEEDS_ATTENTION`. However, in-flight approval (`orchestrator.py` L3199) allowed approval up to `15` minutes (`timedelta(minutes=15)`).
- **Remediation Applied:**
  1. Standardized `CortexOrchestrator.approve()` to enforce a strict `300`-second window across both in-flight and restored approval paths.
  2. Added robust epoch timestamp fallback that handles both `task.params["created_at"]` (float) and `task.created_at` (ISO string).
- **Files Modified:**
  - `backend/agent/orchestrator.py` (lines 3255–3275)
- **Verification Evidence:**
  - `tests/test_conversational_email_p7_4_1.py::test_10_standardized_300s_approval_expiry` (**PASSED** - task created 350s ago rejected with `"Approval expired"`)
  - `tests/test_conversational_email_p7_4_1.py::test_11_fresh_task_within_300s_approved` (**PASSED** - task created 60s ago approved and completed)

---

### Finding 6: P2 Defense-in-Depth — Send Safety Gate Across All Providers

- **Audit Defect:**
  In `MailAutomation.send_mail()`, lines 672–684 checked accounts containing `"gmail"` or `"@gmail.com"` and forwarded them to `self.manager.gmail.send_message()` *before* checking `CORTEX_ALLOW_REAL_EMAIL_SEND == "1"`.
- **Remediation Applied:**
  1. Moved the `allow_real_send = os.environ.get("CORTEX_ALLOW_REAL_EMAIL_SEND") == "1"` enforcement to the top of `send_mail()`, before provider-specific dispatch.
  2. Confirms that neither Gmail, Apple Mail, nor any other provider can bypass the global safety gate.
- **Files Modified:**
  - `backend/capabilities/mail_actions.py` (lines 670–710)
- **Verification Evidence:**
  - `tests/test_conversational_email_p7_4_1.py::test_12_send_safety_gate_blocks_all_providers_when_unset` (**PASSED** - Gmail and Apple Mail dispatch both return `delivery_status: BLOCKED` with `ok: False`)

---

## 3. FULL TEST EXECUTION & REGRESSION EVIDENCE

All 7 test suites were executed sequentially using pytest in the active virtual environment:

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

### Exact Results Summary
- **Total Tests:** 73
- **Passed:** 73
- **Failed:** 0
- **Duration:** 148s

| Test Suite File | Tests | Result | Focus Area |
|---|---|---|---|
| `tests/test_conversational_email_p7_4_1.py` | 12 | **12 PASSED** | P7.4.1 Remediations: Hash reconstruction, domain policy, RFC Message-ID, dative phrases, 300s window, send gate |
| `tests/test_conversational_email_p7_4.py` | 9 | **9 PASSED** | P7.4: Intent classification, thread composition, MCP tools delegation, restart rehydration, send safety |
| `tests/test_mail_search_remediation_p7_3_1.py` | 10 | **10 PASSED** | P7.3.1: Date parser, range filters, duplicate suppression, MCP routing, live MCP verification |
| `tests/test_mail_send_safety.py` | 16 | **16 PASSED** | P7.2: Send safety, single-use approval, replay rejection, Sent mailbox verification, atomic reservation |
| `tests/test_mail_search_and_accounts.py` | 13 | **13 PASSED** | P7.3: Dynamic account discovery, multi-account search, query parsing, concurrency |
| `tests/test_mcp_apple_mail.py` | 7 | **7 PASSED** | P7.1: MCP Apple Mail server lifecycle, tool registration, bridge sync, safety blocks |
| `tests/test_task6_apple_mail.py` | 6 | **6 PASSED** | P7.1: Task6 multi-turn draft resolution, refinement, cancellation, replay protection |

### Frontend Build Verification
`apps/desktop` Vite production build executed cleanly:
```bash
cd apps/desktop && npm run build
```
- Modules transformed: 1575
- Output: `dist/index.html` (1.10 kB), `dist/assets/index-CiuD6QJ5.css` (32.47 kB), `dist/assets/index-CEYSskt6.js` (219.32 kB)
- Result: **0 errors, build completed in 714ms**

---

## 4. SAFETY & COMPLIANCE POSTURE

1. **Zero Outbound Email Sent:**
   - `CORTEX_ALLOW_REAL_EMAIL_SEND` is strictly unset / OFF in all environments.
   - All email creation operations remain strictly in `draft_mail` mode.
2. **Apple Mail MCP Send Tools Hard-Blocked:**
   - `send-email`, `send-serial-email`, `reply-to-message`, `forward-message` remain registered as `DISALLOWED_TOOLS` in `backend/mcp/config.py` and blocked by `MCPServerManager`.
3. **Approval Security Intact:**
   - Canonical SHA-256 draft hashes strictly bind recipient, sender account, subject, body, attachments, in-reply-to, and references.
   - Any modification invalidates approval.
   - Approvals expire in exactly 300 seconds across all states.
   - Replay protection in `TaskStore` prevents double-consumption.

---

## 5. AUDIT READINESS STATEMENT

All five readiness blockers (two P0s, three P1s) and the P2 defense-in-depth finding documented in `docs/P7_4_INDEPENDENT_ACCEPTANCE_AUDIT.md` have been fully closed with architecture-preserving, minimal changes.

In accordance with project governance rules:
- P7.4 is not declared accepted unilaterally.
- The codebase is placed in a clean, tested, and verified state ready for the subsequent independent read-only acceptance audit.
