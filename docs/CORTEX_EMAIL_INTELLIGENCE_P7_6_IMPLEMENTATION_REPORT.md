# CORTEX AGENT — P7.6 FOCUSED MAIL INTELLIGENCE REMEDIATION REPORT

**Date:** November 19, 2026  
**Scope:** P7 Mail Automation — Core Functional Defects Remediation  
**Status:** COMPLETED & LIVE-VERIFIED  
**Safety Gate:** Strict Read-Only (`CORTEX_ALLOW_REAL_EMAIL_SEND` unset; 0 real transmissions, 0 mailbox mutations)  

---

## EXECUTIVE SUMMARY

In accordance with the P7.6 specification, all three confirmed core defects in Cortex Mail have been remediated, verified via targeted automated regressions, and validated through live end-to-end testing against the active desktop daemon on port 8765:

1. **Defect A — Email Body Contamination:** Stripped hardcoded internal category labels (`Leave Request Draft:\n\n` and `Note to Self:\n\n`) from the canonical draft generation logic in `backend/agent/email_engine.py`. Draft bodies now start directly with the appropriate salutation or content.
2. **Defect B — Conversational Email-Investigation Context:** Implemented deterministic contextual email follow-up handling in `backend/core/contracts.py` and `backend/agent/orchestrator.py`. Follow-up queries referencing `self.last_mail_results` (e.g., *"What are they asking me to do?"*, *"When is the deadline?"*, *"Show me that email"*, *"Who sent it?"*, *"Explain the second email"*, and *"Reply asking for clarification"*) are now resolved using the active email investigation context rather than dropping into generic `ASK_QUESTION` or failing when cloud models are throttled.
3. **Defect C — Company / Domain / Subject Search Matching:** Enhanced `_term_matches()` in `backend/capabilities/mail_actions.py` with email domain token matching so company/organization searches match sender domains (e.g. `pentagon` and `pentagon space` matching `campusconnect@pentagonspace.in`). Added an MCP secondary query fallback when literal `from` searches return 0 results. Preserved strict intent boundaries:
   - *"Emails FROM Apple"* matches ONLY sender display name or email domain (returns 0 emails; does NOT falsely match unrelated newsletters like TAAFT).
   - *"Emails ABOUT Apple"* matches sender, subject, and topic (returns the TAAFT newsletter).

---

## SECTION A — ROOT CAUSE ANALYSIS

### 1. Defect A: Email Body Contamination
- **File:** `backend/agent/email_engine.py` (lines 1694 and 1704).
- **Cause:** When generating template-based drafts for leave requests and notes to self, internal category headers (`Leave Request Draft:\n\n` and `Note to Self:\n\n`) were prepended directly into the canonical draft body.
- **Impact:** The resulting email draft presented to the user and created in Apple Mail began with an internal header rather than a clean salutation.

### 2. Defect B: Missing Conversational Context on Follow-ups
- **Files:** `backend/core/contracts.py` and `backend/agent/orchestrator.py`.
- **Cause:** 
  1. `command_from_intent` in `contracts.py` classified conversational follow-ups like *"What are they asking me to do?"* and *"When is the deadline?"* as generic `ASK_QUESTION`, and *"Show me that email"* as `UNKNOWN`.
  2. `orchestrator._answer_general_question` had no reference to `self.last_mail_results`. When Gemini was on 429 quota cooldown, it produced generic canned responses with zero knowledge of the emails found in the previous search turn.
  3. In `orchestrator.py:2590`, for `TaskCommand.REPLY_MAIL`, when the user said *"Reply asking for clarification"*, `target_query` defaulted to the entire prompt string (`"Reply asking for clarification"`) because `params.get("target")` was empty, causing `search_mail` to fail to find an email matching that literal query string instead of referencing `self.last_mail_results[:1]`.

### 3. Defect C: Company / Domain / Subject Search False Negatives
- **File:** `backend/capabilities/mail_actions.py` (lines 227-275 and 1309-1360).
- **Cause:**
  1. `_term_matches(needle, haystack)` strictly required regex word boundaries `\b<term>\b`. When matching needle `"pentagon"` against sender email `"campusconnect@pentagonspace.in"`, the boundary failed because `pentagonspace` is a single alphanumeric token.
  2. In Apple Mail MCP `search-messages`, passing `from: "Pentagon Space"` instructed Mail.app AppleScript to search `sender contains "Pentagon Space"`. Because the sender string in Mail.app was `Campus Connect <campusconnect@pentagonspace.in>` (where "pentagon" and "space" are conjoined as `pentagonspace`), Apple Mail returned 0 messages.
  3. When general fallback logic was previously attempted, searching subject for "from" queries caused "Emails FROM Apple" to falsely match the TAAFT newsletter (`🏠 Apple Trains Robots in Fake Homes`), violating the semantic intent difference between "FROM" and "ABOUT".

---

## SECTION B — CODE MODIFICATIONS

### 1. `backend/agent/email_engine.py`
- Removed `f"Leave Request Draft:\n\n"` from line 1694 so the body starts directly with `f"{salutation}\n\n"`.
- Removed `f"Note to Self:\n\n"` from line 1704 so the body starts directly with `f"{polish_email_body_text(clean_content)}\n\n"`.

### 2. `backend/capabilities/mail_actions.py`
- Enhanced `_term_matches(needle: str, haystack: str) -> bool`:
  - Added email and domain segment matching. When `haystack` contains an email address (`@`) or domain (`.`), `needle` tokens (e.g. `pentagon`, `space`) are matched against the domain segments and full domain string.
- In `search_mail()`:
  - Added secondary query fallback: if an initial MCP search with `from: sender` yields 0 matching emails (e.g., multi-word organization names like "Pentagon Space"), a secondary search is executed using `query = query or sender` without `from`.
  - The returned messages are strictly filtered via `_matches_filters()`. For strict "from" searches, `snd_lower` must match the sender display name or sender email domain. Unrelated newsletters mentioning the entity only in the subject (e.g. TAAFT for Apple) are excluded.

### 3. `backend/core/contracts.py`
- Added `TaskCommand.EMAIL_INVESTIGATION = "email_investigation"` to the `TaskCommand` enum.
- In `command_from_intent()`:
  - Added deterministic recognition for conversational email follow-ups:
    - *"What are they asking me to do?"*, *"What do they want?"*, *"What does the email say?"*
    - *"When is the deadline?"*, *"What is the deadline?"*, *"Is there a deadline?"*
    - *"Show me that email"*, *"Show me the full mail"*, *"Read that email"*
    - *"Who sent it?"*, *"Who is the sender?"*
    - *"Explain the (first|second|...) email"*
  - Positioned this rule ahead of generic email search patterns to prevent interception.

### 4. `backend/agent/orchestrator.py`
- In `chat()`:
  - Added interceptor for `TaskCommand.EMAIL_INVESTIGATION` before general planning/Gemini analysis. If the user asks an email investigation follow-up, it routes directly to `_handle_email_investigation(message)`.
- In `_extract_params()`:
  - Added `TaskCommand.EMAIL_INVESTIGATION` parameter extraction (`{"query": text.strip()}`).
  - Fixed `TaskCommand.REPLY_MAIL` parameter extraction: prevented `target_query` from defaulting to the full command string when `params["body"]` is already populated.
- In `_execute()`:
  - Added execution handler for `TaskCommand.EMAIL_INVESTIGATION`.
- Added helper methods:
  - `_handle_email_investigation(message, lang_code)`: Inspects `self.last_mail_results`, resolves ordinals, retrieves full body if needed via `mail_automation.get_message()`, and answers the specific inquiry.
  - `_extract_deadline_from_text(body, subject)`: Extracts scheduled dates/times or states no deadline was mentioned.
  - `_extract_action_summary_from_email(sender, subject, body, date_str)`: Extracts Google Meet/Zoom links, times, batch numbers, and call-to-action sentences deterministically.
- In `_extract_mail_search_params()`:
  - Made `"me"` optional in `did_send_m` regex (`(?:me\s+)?`).
  - Added trailing email noise pattern to sanitize queries like `"Pentagon Space emails"`.

---

## SECTION C — AUTOMATED REGRESSION SUITE

Authored dedicated test suite `tests/test_email_intelligence_p7_6.py` with 13 unit tests:

| Test Case | Defect | Description | Result |
|:---|:---:|:---|:---:|
| `test_defect_a_professor_leave_draft_has_no_internal_labels` | A | Verifies draft body starts with salutation, no internal header | PASS |
| `test_defect_a_note_to_self_has_no_internal_labels` | A | Verifies note to self body starts directly with content | PASS |
| `test_defect_c_term_matches_domain_subtokens` | C | Verifies `pentagon` & `pentagon space` match `campusconnect@pentagonspace.in` | PASS |
| `test_defect_c_apple_sender_does_not_match_unrelated_newsletter_domain` | C | Verifies Apple does not match TAAFT newsletter domain | PASS |
| `test_defect_c_search_mail_filters_apple_sender_vs_about` | C | Verifies strict "from Apple" rejects TAAFT; "about Apple" accepts TAAFT | PASS |
| `test_defect_c_search_mail_matches_pentagon_space_sender_domain` | C | Verifies Pentagon Space email matches via sender domain | PASS |
| `test_defect_b_empty_last_mail_results_returns_helpful_guidance` | B | Verifies asking follow-up without search context prompts user | PASS |
| `test_defect_b_investigation_what_are_they_asking` | B | Verifies action/meet link extraction from search context | PASS |
| `test_defect_b_investigation_when_is_the_deadline` | B | Verifies scheduled date/time extraction from search context | PASS |
| `test_defect_b_investigation_show_me_that_email` | B | Verifies clean display of full email (headers + body) | PASS |
| `test_defect_b_investigation_who_sent_it` | B | Verifies sender identity extraction from context | PASS |
| `test_defect_b_investigation_ordinal_resolution` | B | Verifies "second email" picks index 1 from search results | PASS |
| `test_defect_b_reply_asking_for_clarification_wires_to_last_mail` | B | Verifies reply drafting targets `self.last_mail_results[:1]` | PASS |

### Regression Suite Status:
- `tests/test_email_intelligence_p7_6.py`: 13/13 PASSED
- `tests/test_email_intelligence_batch1*.py` & `batch2*.py`: 64/64 PASSED
- `apps/desktop` Vite build: PASSED (740ms, 0 errors)

---

## SECTION D — LIVE END-TO-END VERIFICATION ON PORT 8765

Live verification was executed directly against the active FastAPI daemon over HTTP (`POST /chat`) with authentication header `X-Cortex-Session`:

### Turn 1 — Pentagon Space Email Search
- **User Input:** `"Find emails from Pentagon"`
- **Response:**
  ```text
  Found 1 matching email(s):
  • [Google: [Gmail]/Important] From Campus Connect <campusconnect@pentagonspace.in>: Google Meet Link for Group Discussion - Pentagon Space (11/12/2026)
  ```
- **Task Status:** `completed`
- **Result:** Successfully matched sender domain `pentagonspace.in`.

### Turn 2 — Conversational Follow-up: Action Inquiry
- **User Input:** `"What are they asking me to do?"`
- **Response:**
  ```text
  In this email ('Google Meet Link for Group Discussion - Pentagon Space'), Campus Connect is asking you to:
  - Join the group discussion on 12-11-2026 at 04:30 PM (Batch 05) using the link: https://meet.google.com/zwz-oxsx-uaf
  - Hello everyone, please find the Google Meet link below. Kindly join on time.
  ```
- **Task Status:** `completed`
- **Result:** Context retained. Extracted exact meeting link, batch number, scheduled date/time, and instructions.

### Turn 3 — Conversational Follow-up: Deadline Inquiry
- **User Input:** `"When is the deadline?"`
- **Response:**
  ```text
  The scheduled date and time is 12-11-2026 at 04:30 PM (Batch: 05). There is no separate submission deadline mentioned; it is a live session scheduled for that time.
  ```
- **Task Status:** `completed`
- **Result:** Context retained. Identified scheduled session time and explicitly noted that no submission deadline was present.

### Turn 4 — Conversational Follow-up: Show Full Email
- **User Input:** `"Show me that email"`
- **Response:**
  ```text
  From: Campus Connect <campusconnect@pentagonspace.in>
  Subject: Google Meet Link for Group Discussion - Pentagon Space
  Date: 11/12/2026

  Hello everyone, please find the Google Meet link below. Kindly join on time.

  Date: 12-11-2026
  Time: 04:30 PM
  Batch No: 05
  Meet Link : https://meet.google.com/zwz-oxsx-uaf

  -- 
  Regards, 
  Team Campus Connect
  Sushma M
  8951953812
  www.pentagonspace.in
  Bangalore I Hyderabad
  ```
- **Task Status:** `completed`
- **Result:** Rendered full original message with clean metadata headers.

### Turn 5 — Strict Sender Search (Negative Control)
- **User Input:** `"Find emails from Apple"`
- **Response:**
  ```text
  No emails found matching 'Apple' across connected accounts.
  ```
- **Task Status:** `completed`
- **Result:** Correctly returned 0 results. Did NOT match the unrelated TAAFT newsletter.

### Turn 6 — Topic / Query Search (Positive Control)
- **User Input:** `"Find emails about Apple"`
- **Response:**
  ```text
  Found 1 matching email(s):
  • [Google: [Gmail]/All Mail] From TAAFT - There's An AI For That <hi@mail.theresanaiforthat.com>: 🏠 Apple Trains Robots in Fake Homes (11/9/2026)
  ```
- **Task Status:** `completed`
- **Result:** Correctly matched the newsletter because user asked for emails *about* Apple.

---

## SECTION E — SAFETY AUDIT & CHANGE CONTROL COMPLIANCE

1. **Safety Controls:**
   - Outbound transmission safety gate `CORTEX_ALLOW_REAL_EMAIL_SEND` was verified UNSET throughout.
   - Zero outbound emails were transmitted.
   - Zero mailboxes or drafts were mutated in Mail.app.
2. **Change Control:**
   - No git staging (`git add`), commits (`git commit`), or pushes (`git push`) were performed.
   - All unrelated repository changes across WhatsApp, notes, and browser automation were preserved untouched.
   - Changes were restricted strictly to the minimal lines necessary in `email_engine.py`, `mail_actions.py`, `contracts.py`, and `orchestrator.py`.
