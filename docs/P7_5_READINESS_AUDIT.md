# CORTEX AGENT — P7.5 END-TO-END EMAIL WORKFLOW ACCEPTANCE
## Comprehensive Readiness Audit — Strict Read-Only Audit
### Architecture-Preserving · Zero Outbound Sends · Systematic Verification

**Date:** November 18, 2026  
**Audit Phase:** P7.5 End-to-End Email Workflow Acceptance  
**Audit Mode:** Strict Read-Only Verification  
**Host Environment:** macOS Darwin 27.0.1 (arm64 Apple Silicon)  
**Python Runtime:** Python 3.9.6 (`/Users/gsunilkumar/.gemini/antigravity/scratch/cortex/venv/bin/python3`)  
**Frontend Stack:** React 19 / TypeScript 5.6.3 / Vite 6.0.5 (`apps/desktop`)  
**Active Account:** `Google <gsunilkumar1307@gmail.com>` (Apple Mail connected)  
**Safety Gate:** `CORTEX_ALLOW_REAL_EMAIL_SEND` **UNSET / OFF (0)** — Outbound transmission strictly blocked  
**Regression Test Status:** **73 / 73 PASSED (100%)** across 7 test suites  
**Frontend Build Status:** **0 ERRORS** (1,575 modules built in 1.33s)  
**Final Verdict:** **ACCEPTED WITH MINOR GAPS (READY FOR P7.5)**

---

## 1. EXECUTIVE SUMMARY

This comprehensive audit independently evaluates the end-to-end readiness of Cortex Agent's email automation subsystem for Phase P7.5 acceptance. The audit was conducted under strict read-only constraints: zero source-code modifications were made, no live emails were transmitted, no Git changes were staged, and all state databases and mailbox contents remained unmodified.

The primary objective was to determine whether Cortex can reliably execute complete, natural-language email workflows across real Apple Mail data, using its MCP-first architecture and supervised human-in-the-loop approval system.

### Summary of Acceptance Status:

| Scenario / Subsystem | Status | Key Findings |
|---|---|---|
| **Scenario A: Natural-Language Search** | **PASS** | High-precision intent classification across 8 complex search queries; multi-mailbox traversal (`INBOX`, `[Gmail]/Important`, `[Gmail]/All Mail`); robust date filtering across RFC 2822/ISO/relative dates; transparent partial-coverage reporting. |
| **Scenario B: Recipient Resolution & New Email** | **PASS (Minor Gaps)** | Directory search, authorized contacts, and direct emails resolved cleanly; missing information (`need_info`) prompts conversationally without hallucinating email addresses; deterministic fallback handles canonical send phrasing. |
| **Scenario C: Multi-Turn Draft Refinement** | **PASS (Minor Gaps)** | Conversational state maintained across turns; tone, meeting times, and subject refinements update non-destructively; dative conversions (`"Ask him about..."`) normalize cleanly; approval hash recomputed on each edit. |
| **Scenario D: Replying to Existing Emails** | **PASS** | `REPLY_MAIL` intent classification; threading headers (`inReplyTo`, `references`) populated; live host RFC 2822 Message-ID validation strictly conforms to MCP regex (`^<[^<>\s@]+@[^<>\s@]+>$`). |
| **Scenario E: Forwarding Emails** | **PASS** | `FORWARD_MAIL` preserves source headers, original body, and user notes; draft-only mode enforced; approval hash covers threading context. |
| **Scenario F: Multi-Account Contextual Routing** | **PASS** | Single account defaults directly without prompting; multi-account domain match generates clarification with recommendation (`is_ambiguous=True`); thread context and explicit account requests resolve directly. |
| **Scenario G: Draft Persistence & Recovery** | **PASS** | SQLite `tasks` table stores draft payload; 300-second TTL expiration enforced across in-flight approval and restart rehydration (`NEEDS_ATTENTION`); hash tampering detected. |
| **Scenario H: Approval Flow & Safety Gates** | **PASS** | Structured preview card presents recipient, account, subject, body, and threading headers; SHA-256 payload integrity check prevents tampering; `CORTEX_ALLOW_REAL_EMAIL_SEND=0` blocks all outbound transmissions. |
| **Scenario I: Frontend & Conversational Experience** | **PASS** | Vite production build compiles with 0 errors; no internal tool names or raw exceptions leaked to user; clean assistant UI responses. |

**Overall Verdict:** Cortex's email subsystem is **ACCEPTED WITH MINOR GAPS**. All foundational architecture, MCP integrations, safety gates, and multi-turn workflows are fully operational and verified against real Apple Mail data and live MCP schemas.

---

## 2. SYSTEM ARCHITECTURE & END-TO-END EXECUTION TRACE

The email subsystem operates via an architecture-preserving, multi-stage pipeline:

```
[ User Natural-Language Prompt ]
               │
               ▼
   [ CortexOrchestrator.chat() ]
               │
     ┌─────────┴─────────┐
     ▼                   ▼
[ LLM Gemini 1.5 ]  [ Fallback Regex Engine ]
 (Circuit Breaker)   (Offline / Quota Fallback)
     │                   │
     └─────────┬─────────┘
               ▼
[ Intent & Command Resolution ]
 (SEARCH_MAIL, DRAFT_MAIL, REPLY_MAIL, FORWARD_MAIL)
               │
               ├─────────────────────────────────────────────┐
               ▼                                             ▼
       [ Search Pipeline ]                           [ Draft Pipeline ]
               │                                             │
      [ MailAutomation ]                             [ RecipientResolver ]
    (Apple Mail MCP First)                                   │
               │                                             ▼
  ┌────────────┴────────────┐                     [ EmailEngine / Compose ]
  ▼                         ▼                                │
[ MCP Search ]   [ AppleScript Fallback ]                    ▼
  │                         │                     [ Contextual Account Resolver ]
  └────────────┬────────────┘                                │
               ▼                                             ▼
   [ Multi-Mailbox Dedupe ]                         [ Apple Mail MCP Draft ]
   [ Coverage & Date Filter]                      (create-draft / inReplyTo)
               │                                             │
               ▼                                             ▼
      [ Results to UI ]                             [ SQLite TaskStore ]
                                                  (SHA-256 Hash & 300s TTL)
                                                             │
                                                             ▼
                                                    [ Frontend Approval Card ]
                                                             │
                                                             ▼
                                                   [ User Approve / Reject ]
                                                             │
                                                             ▼
                                                    [ Send Safety Gate ]
                                              (CORTEX_ALLOW_REAL_EMAIL_SEND)
```

### Trace Step Details:
1. **Natural-Language Understanding:** `CortexOrchestrator.chat()` receives the prompt. Primary classification uses Gemini (`gemini-1.5-flash`), with an automatic 3-minute circuit breaker fallback to `_analyze_intent_fallback()` if quota limits (429) or network interruptions occur.
2. **Recipient & Context Resolution:** `RecipientResolver` identifies target recipients via regex, encrypted contacts, `KNOWN_DIRECTORY` (e.g., academic institutions), or prior correspondence. Missing parameters trigger a `need_info` conversational prompt.
3. **Draft Composition & Threading:** `ProfessionalEmailEngine` prepares structured content, converting third-person dative instructions (`"Ask him about..."`) to polite first-person phrasing. For replies/forwards, `in_reply_to` and `references` headers are populated with RFC 2822 Message-IDs.
4. **Account Selection:** `MailAutomation.get_accounts()` and `_resolve_sending_account()` choose the appropriate sender based on explicit request, thread context, or domain suggestion.
5. **Draft Persistence & Security:** `EmailDraft.compute_hash()` computes a SHA-256 checksum over all draft fields. The task is persisted to SQLite with `status=WAITING_APPROVAL` and a standardized 300s TTL.
6. **Supervised Approval:** The desktop frontend displays a rich approval card. Approving triggers `CortexOrchestrator.approve()`, which validates the token, recomputes the SHA-256 hash, checks the 300s expiration, and inspects the hard safety gate.
7. **Transmission Gate:** In accordance with P7.5 safety requirements, `CORTEX_ALLOW_REAL_EMAIL_SEND` is unset/OFF. Any delivery attempt returns an audit-logged simulated response; transmission tools (`send-draft`, `send-email`) are blocked in `AppleMailMCPClient`.

---

## 3. SCENARIO-BY-SCENARIO DETAILED ACCEPTANCE MATRIX

### Scenario A: Natural-Language Email Search
- **Status:** **PASS**
- **Requirements Tested:** Sender filtering, keyword search, unread filter, limit parsing, multi-mailbox traversal, date filtering, duplicate suppression, honest partial-coverage reporting.
- **Empirical Test Results:**
  - `"Do I have any mail from Apple?"` → `command=SEARCH_MAIL`, `sender='Apple'` (**PASS**)
  - `"Show me the latest email from Google"` → `command=SEARCH_MAIL`, `sender='Google'`, `limit=1` (**PASS**)
  - `"Did Instagram send me anything?"` → `command=SEARCH_MAIL`, `sender='Instagram'` (**PASS**)
  - `"Find the email Rahul sent me"` → `command=SEARCH_MAIL`, `sender='Rahul'` (**PASS**)
  - `"Show me unread emails from my college"` → `command=SEARCH_MAIL`, `unread_only=True` (**PASS**)
  - `"Search for emails about taxes from this month"` → `command=SEARCH_MAIL`, `subject='taxes'` (**PASS**)
  - `"Search for invoice from last week"` → `command=SEARCH_MAIL`, `subject='invoice'` (**PASS**)
  - `"Find messages from John about project schedule"` → `command=SEARCH_MAIL`, `sender='John'`, `subject='project schedule'` (**PASS**)
- **Live MCP Search Verification:** Live execution against Apple Mail MCP discovered 15 canonical tools. `search-mail` executes across `INBOX`, `[Gmail]/Important`, and `[Gmail]/All Mail`.
- **Date & Deduplication Verification:** `parse_email_date()` and `normalize_date_bound()` parse RFC 2822, ISO, `"today"`, `"yesterday"`, and named month ranges. Multi-mailbox searches deduplicate on `(message_id, subject, date)`. Partial account failures report coverage rather than silent omission.

---

### Scenario B: Recipient Resolution & New Email Draft
- **Status:** **PASS (with minor fallback phrasing gaps)**
- **Requirements Tested:** Resolving recipients from conversational inputs, directory lookups, prompting when recipient or body is missing, preventing hallucinated email addresses.
- **Empirical Test Results:**
  - `"Send a mail to Rahul"` → Cortex identifies missing body, returns `need_info`: `"What would you like me to send to Rahul?"` (**PASS**)
  - `"Write an email to my project guide"` → Cortex identifies missing recipient details and body, prompts user conversationally (**PASS**)
  - Direct email input (`"Send an email to alex@company.com saying hello"`) → Resolves recipient `alex@company.com`, creates draft with subject `"Greeting / Hello"` (**PASS**)
- **Gaps Identified in Fallback Mode:**
  - When Gemini Free Tier quota is reached (429 circuit breaker active), queries without explicit keywords `"email"` or `"mail"` (e.g. `"Send my professor an update"`) or phrased as `"Email the person..."` return `UNKNOWN` because `command_from_intent()` in `contracts.py` lines 1410–1425 expects `"send email"`, `"send a mail"`, or `"email to "`. This is a non-blocking deterministic regex coverage gap (P1).

---

### Scenario C: Multi-Turn Conversational Draft Refinement
- **Status:** **PASS (with minor fallback editing gaps)**
- **Requirements Tested:** Multi-turn drafting state machine (`waiting_for_body` -> `confirm_send`), contextual conversational edits, tone adjustments, subject modifications, non-destructive updating.
- **Empirical Test Sequence:**
  1. User: `"Send a mail to Rahul"` → Response: `"What would you like me to send to Rahul?"` (State: `waiting_for_body`).
  2. User: `"Ask him about the internship opportunity"` → Cortex normalizes dative phrasing to `"I am writing to inquire about the internship opportunity."`, creates draft, computes hash, displays approval preview (State: `confirm_send`).
  3. User: `"Keep it professional"` → Cortex updates salutation to `"Dear Rahul Verma,"`, maintains content, updates approval hash.
  4. User: `"Change the subject to Internship Application Query"` → Subject updated, body preserved, approval hash updated.
- **Dative Normalization Verification:** Verified via `test_conversational_email_p7_4_1.py` test 09. Dative third-person constructions (`"Ask him about..."`, `"Tell her that..."`) are converted into professional first-person sentences without third-person leakage.
- **Gaps Identified in Fallback Mode:**
  - In deterministic fallback mode, `update_draft_with_edit()` handles `"change subject"`, `"add that"`, `"include that"`, and meeting times, but lacks exact prefix matching for `"Mention that ..."` and `"Make it sound more natural"`.

---

### Scenario D: Replying to Existing Emails
- **Status:** **PASS**
- **Requirements Tested:** `REPLY_MAIL` classification, extracting `inReplyTo` and `references`, RFC 2822 Message-ID validation, draft creation with MCP threading headers.
- **Empirical Test Results:**
  - `"Reply to that email"` → Classified as `REPLY_MAIL` (**PASS**)
  - `"Reply saying I'll attend"` → Classified as `REPLY_MAIL`, body initialized (**PASS**)
  - RFC 2822 Schema Compliance: MCP `create-draft` tool enforces regex `^<[^<>\s@]+@[^<>\s@]+>$`. Live mailbox inspection confirmed extraction of real RFC 2822 Message-ID (e.g. `<MA5P287MB48353ED2E634B6DC4B5BA566AB7A2@MA5P287MB4835.INDP287.PROD.OUTLOOK.COM>`). Numeric IDs (e.g. `8502`) are filtered out to prevent MCP schema rejection.
  - Approval Hash Integrity: Reply drafts incorporate `in_reply_to` and `references` into `EmailDraft.compute_hash()` and `approve()` recomputation, eliminating false hash mismatches.

---

### Scenario E: Forwarding Emails
- **Status:** **PASS**
- **Requirements Tested:** `FORWARD_MAIL` classification, preserving source body, prepending user notes, setting `Fwd:` subject prefix, approval hash integrity.
- **Empirical Test Results:**
  - `"Forward this email to Rahul"` → Classified as `FORWARD_MAIL` (**PASS**)
  - Source body formatting: Header block (`---------- Forwarded message ---------`, `From:`, `Subject:`, `Date:`) correctly prepended to original message body (**PASS**).
  - Draft safety: Forward tasks are strictly held in `WAITING_APPROVAL` with `requires_approval=True` (**PASS**).
  - Hash reconstruction: `test_02_forward_draft_approval_hash_reconstruction` verified passing in regression test suite (**PASS**).

---

### Scenario F: Multi-Account Contextual Routing
- **Status:** **PASS**
- **Requirements Tested:** Dynamic account discovery, single-account default, multi-account clarification, recipient domain matching without silent auto-selection.
- **Empirical Test Matrix:**
  1. *Single Connected Account:* When only one account exists (`Google <gsunilkumar1307@gmail.com>`), it is automatically selected with `is_ambiguous=False` (**PASS**).
  2. *Multi-Account Domain Match:* When recipient is `colleague@work.com` and both Personal and Work accounts exist, Cortex marks `is_ambiguous=True` and generates a suggestion prompt: `"You have multiple email accounts. Would you like to send this from your Work account (me@work.com)?"` (**PASS**).
  3. *Thread Context:* In reply/forward workflows, `thread_account` is directly inherited with `is_ambiguous=False` (**PASS**).
  4. *Explicit User Choice:* Specifying `"from my Work account"` directly selects the requested account (**PASS**).

---

### Scenario G: Draft Persistence & Recovery
- **Status:** **PASS**
- **Requirements Tested:** SQLite task persistence, 300-second TTL expiration, process restart rehydration.
- **Empirical Test Results:**
  - Standardized 300s TTL: `EmailDraft.is_expired(300)` accurately evaluates draft age. Fresh drafts (<300s) approve cleanly; drafts older than 300s are rejected with `APPROVAL_EXPIRED` (**PASS**).
  - Restart Rehydration: Upon restart, `_rehydrate_tasks()` scans SQLite for pending tasks. Stale drafts (>300s) transition to `NEEDS_ATTENTION` with clear explanatory messages. Active drafts within TTL transition to `WAITING_APPROVAL` (**PASS**).
  - Non-Destructive Edits: Any edit to an active draft recalculates `draft.compute_hash()` and updates the task parameters, invalidating prior approval tokens (**PASS**).

---

### Scenario H: User Approval Flow & Safety Gates
- **Status:** **PASS**
- **Requirements Tested:** Structured approval card payload, SHA-256 payload tampering detection, single-use approval token consumption, send safety gate enforcement.
- **Empirical Test Results:**
  - Preview Payload: Task parameters expose complete structured fields (`recipient`, `sender_account`, `subject`, `body`, `formatted_body`, `approval_hash`, `in_reply_to`, `references`) for frontend card rendering (**PASS**).
  - Tamper Detection: Changing any parameter (e.g., recipient, body, account) before calling `approve()` causes immediate rejection with `APPROVAL_HASH_MISMATCH` (**PASS**).
  - Single-Use Consumption: After an approval attempt, the token is consumed. Replay attempts are rejected with `APPROVAL_TOKEN_ALREADY_USED` (**PASS**).
  - Send Safety Gate: In accordance with P7 safety rules, `CORTEX_ALLOW_REAL_EMAIL_SEND` remains unset. `test_12_send_safety_gate_blocks_all_providers_when_unset` confirms that neither Apple Mail nor Gmail can send real outbound emails when this flag is OFF (**PASS**).

---

### Scenario I: Frontend & Conversational Experience
- **Status:** **PASS**
- **Requirements Tested:** Production build integrity, absence of leaked internal tool names or raw error traces, conversational clarity.
- **Build Verification:**
  ```bash
  cd apps/desktop && npm run build
  # Output:
  # vite v6.0.5 building for production...
  # transforming...
  # ✓ 1575 modules transformed.
  # rendering chunks...
  # computing gzip size...
  # dist/index.html                   0.85 kB │ gzip:  0.43 kB
  # dist/assets/index-B_VlW25w.css   33.24 kB │ gzip:  6.91 kB
  # dist/assets/index-C72z1Pqg.js   563.02 kB │ gzip: 169.57 kB
  # ✓ built in 1.33s
  ```
- **Conversational Verification:** Error messages, empty search results, and clarification prompts present natural language (e.g. `"I couldn't find any emails from Google matching that criteria in your Inbox or Archive."`) without exposing raw MCP JSON-RPC schemas or tool names.

---

## 4. LIVE APPLE MAIL / MCP ENVIRONMENT VS MOCK TEST EVIDENCE

A critical mandate of this audit is to clearly distinguish live host execution from mocked test suites.

| Capability | Verification Mode | Evidence & Environment |
|---|---|---|
| **Apple Mail MCP Server Connection** | **LIVE EXECUTION** | Connected to live `apple-mail` MCP server v2.20.57 via stdio. 15 canonical tools enumerated (`search-mail`, `get-mailboxes`, `create-draft`, `get-thread`, etc.). |
| **Account Discovery** | **LIVE EXECUTION** | Queried live host Mail.app; dynamically discovered active account `Google <gsunilkumar1307@gmail.com>`. Zero mock accounts used. |
| **RFC 2822 Message-ID Extraction** | **LIVE EXECUTION** | Extracted real RFC 2822 Message-ID from host mailbox message ID 8502 (`<MA5P287MB48353ED2E634B6DC4B5BA566AB7A2@MA5P287MB4835.INDP287.PROD.OUTLOOK.COM>`). |
| **Mailbox Traversal** | **LIVE EXECUTION** | Queried live mailboxes: `INBOX`, `[Gmail]/Important`, `[Gmail]/All Mail`. Verified search execution across real mailbox hierarchies. |
| **Multi-Account Clarification Logic** | **MOCKED INTEGRATION** | Multi-account environment mocked with Personal + Work accounts in `tests/test_conversational_email_p7_4_1.py` because host machine only has one configured email account. |
| **Send Safety Gate** | **LIVE & MOCKED** | Verified that `CORTEX_ALLOW_REAL_EMAIL_SEND` is unset on host machine, and mocked tests confirm both Gmail and Apple Mail drivers block transmission when flag is 0. |
| **Idempotency & Concurrency** | **INTEGRATION TEST** | Verified via 20-thread concurrent reservation test against SQLite `mail_send_attempts` table. |

---

## 5. REGRESSION & TEST SUITE VERIFICATION

All 7 test suites comprising 73 tests were executed against the active virtual environment:

```bash
pytest \
  tests/test_conversational_email_p7_4_1.py \
  tests/test_conversational_email_p7_4.py \
  tests/test_mail_search_remediation_p7_3_1.py \
  tests/test_mail_send_safety.py \
  tests/test_mail_search_and_accounts.py \
  tests/test_mcp_apple_mail.py \
  tests/test_task6_apple_mail.py
```

### Results Summary:
- `tests/test_conversational_email_p7_4_1.py`: **12 / 12 PASSED**
- `tests/test_conversational_email_p7_4.py`: **9 / 9 PASSED**
- `tests/test_mail_search_remediation_p7_3_1.py`: **10 / 10 PASSED**
- `tests/test_mail_send_safety.py`: **16 / 16 PASSED**
- `tests/test_mail_search_and_accounts.py`: **13 / 13 PASSED**
- `tests/test_mcp_apple_mail.py`: **7 / 7 PASSED**
- `tests/test_task6_apple_mail.py`: **6 / 6 PASSED**

**Total: 73 / 73 PASSED (100%) in 115.49s**

---

## 6. PRIORITIZED GAPS & RECOMMENDATIONS (FOR P7.5.1)

No P0 blockers were identified that compromise safety, data integrity, or core conversational workflows. The following minor non-blocking gaps are documented for future refinement:

### 1. P1: Deterministic Fallback Regex Phrasing Coverage
- **Location:** `backend/core/contracts.py:command_from_intent()` (lines 1410–1430)
- **Finding:** When Gemini quota is exhausted (429 circuit breaker active), queries without explicit keywords `"mail"` or `"email"` (e.g., `"Send my professor an update"`) or phrasing like `"Email the person..."` return `UNKNOWN`.
- **Recommendation:** Expand regex patterns in `command_from_intent()` to recognize `r"^(?:send|write|shoot)\s+(?:to\s+)?([a-z\s]+?)\s+(?:an?\s+)?update"` and `r"^email\s+(?:the\s+)?person"`.

### 2. P1: Conversational Draft Edit Trigger Phrasing
- **Location:** `backend/agent/email_engine.py:update_draft_with_edit()` (lines 920–960)
- **Finding:** While `"add that ..."`, `"include ..."`, and time updates work properly, prefixes like `"Mention that ..."` and tone directives like `"Make it sound more natural"` are not fully parsed in offline fallback mode.
- **Recommendation:** Add prefix stripper for `r"^(?:please\s+)?mention\s+that\s+"` and expand tone adjectives to include `"natural"`, `"warm"`, and `"casual"`.

### 3. P2: Reply Intent Priority over Search for Contextual Threads
- **Location:** `backend/core/contracts.py` (lines 1420–1435)
- **Finding:** Phrases like `"Reply to the latest email from Google"` route to `SEARCH_MAIL` first rather than `REPLY_MAIL`.
- **Assessment:** This is functionally acceptable because Cortex must find the target message before constructing the reply; however, linking the search result directly into an automatic reply prompt would streamline the user experience.

---

## 7. FINAL ACCEPTANCE VERDICT

| Category | Assessment | Verdict |
|---|---|---|
| **P7.1 – P7.3.1 Capabilities** | Preserved & operational | **PASS** |
| **P7.4 & P7.4.1 Remediations** | Verified in source & tests | **PASS** |
| **End-to-End Scenarios (A – I)** | All 9 scenarios validated | **PASS** |
| **Apple Mail MCP Connectivity** | Verified on live macOS environment | **PASS** |
| **Send Safety Gate** | `CORTEX_ALLOW_REAL_EMAIL_SEND=0` verified | **PASS** |
| **Regression Test Suite** | 73 / 73 passed (100%) | **PASS** |
| **Frontend Production Build** | 0 errors (1.33s build) | **PASS** |

### **Final Verdict: ACCEPTED WITH MINOR GAPS (READY FOR P7.5)**

Cortex Agent successfully demonstrates end-to-end conversational email capabilities across real Apple Mail data while strictly enforcing supervised approval and outbound transmission safety gates.
