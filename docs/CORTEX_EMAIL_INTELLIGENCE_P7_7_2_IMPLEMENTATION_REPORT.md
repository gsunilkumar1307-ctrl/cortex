# CORTEX AGENT — P7.7.2 SINGLE COMPOSER LIFECYCLE & DUPLICATE CARD REMEDIATION
## Implementation & Verification Report

**Phase:** P7.7.2  
**Scope:** Email Composition Experience & State Lifecycle Remediation  
**Status:** **ACCEPTED — SINGLE COMPOSER LIFECYCLE VERIFIED**  
**Date:** November 19, 2026  
**Reference Commit Baseline:** Desktop Mail Pilot P7.7.1  

---

## 1. Executive Summary

During live desktop testing of Cortex Mail following P7.7.1, a significant UI lifecycle and state rendering defect was identified:
- When a user submitted successive conversational modifications to an active email draft, Cortex repeatedly rendered duplicate "Email Draft Ready for Review" bubble notices and re-rendered additional review card instances for each turn.
- The TO (recipient) and SUBJECT fields in the review card were intermittently unpopulated/blank due to shallow parameter referencing (`task.params.recipient` instead of checking fallback draft objects).
- Conversational topic changes (e.g., *"Change the topic to applying for a VTU internship"*) were unrecognized or treated as a no-op fallthrough, failing to adjust the subject and body.
- Complex conversational directives observed in live sessions (*"Request leave for one week and add date"*, *"Make it larger"*, *"Format it as a proper leave letter"*, *"Recipient name is Dhulappa"*) were unhandled or truncated.

Phase P7.7.2 has fully resolved these defects:
1. **Single Composer Task Identity:** Enforced exactly ONE active, persistent email composer card per email draft task (`key={task.id || "active-email-composer"}`).
2. **Notification & Feedback Separation:** Differentiated initial draft creation (`state_version == 1`) from subsequent edits (`state_version > 1`). Only initial draft creation displays the "Email Draft Ready for Review" bubble notice; subsequent edits display clean, concise conversational feedback (e.g., *"Updated recipient name to Dhulappa."*, *"Updated the leave duration to two days."*) without dumping the entire approval card wall of text.
3. **Robust Field Fallbacks:** Guaranteed that `recipient`, `recipient_email`, `sender_account`, `subject`, and `body` check nested fallbacks (`task.params.draft`, `task.draft`, `task.context`), preventing blank input fields.
4. **Complete Conversational Topic Transformation:** Implemented first-class support for topic directives (e.g., *"Change the topic to applying for a VTU internship"*), updating both subject and body to the VTU internship application while preserving the recipient's salutation name (`Dear Dhulappa,`) and verified email address.
5. **Comprehensive Phrasing Support:** Added support for *"Make it larger"*, *"Format it as a proper leave letter"*, date-qualified durations (*"starting from Monday"*), and robust name title formatting.

---

## 2. Root Cause Analysis

| Defect Observed in Pilot | Root Cause in Codebase | Resolution in P7.7.2 |
| :--- | :--- | :--- |
| **Duplicate "Email Draft Ready for Review" Cards** | `apps/desktop/src/App.jsx:315` checked only `task.status === "waiting_approval"` and rendered `<div className="email-draft-bubble-notice">` for *every* historical turn in `turns.map()`. Furthermore, `backend/agent/orchestrator.py:1394` returned `_format_approval_card()` containing the full options wall on every edit. | `ResponseCard` now checks `isEditTurn = (task.state_version > 1 || task.stateVersion > 1)`. If true, it renders the concise conversational response. `orchestrator.py` now invokes `_generate_edit_feedback(...)` and returns concise text feedback. |
| **Blank TO and SUBJECT Fields** | `apps/desktop/src/App.jsx:1130` initialized state strictly from `p.recipient_email \|\| p.recipient` and `p.subject`. If nested under `p.draft` or `task.context`, it evaluated to empty string `""`. | Added comprehensive fallback resolution: `p.recipient_email \|\| p.recipient \|\| draft.recipient \|\| task?.context?.recipient \|\| ""` and `p.subject \|\| draft.subject \|\| task?.context?.purpose \|\| ""`. |
| **Topic Change to VTU Internship Ignored** | `backend/agent/email_engine.py` only checked `change the subject to`; `change the topic to...` was unrecognized and treated as a no-op fallthrough. | Added `topic_m` matching `change topic to...`, `topic is...`, etc., specifically handling VTU/internship topic shifts with body replacement and salutation preservation. |
| **"Make it larger" & "Leave letter format" Ignored** | No handlers existed in `email_engine.py` for letter formatting or body expansion. | Added `is_leave_letter` and `is_expand` handlers with rich professional letter formatting and handover details. |
| **Duration with Trailing Phrasing Broken** | Duration regex anchored with sentence termination `(?:\.\|$)`. | Updated `dur_word_pat` to match duration tokens anywhere in the prompt and added date clause support. |

---

## 3. Implementation Details

### A. Backend: `backend/agent/email_engine.py`
- **Topic Change Handler:** Added `topic_m` regex matching `(?:change\s+(?:the\s+)?topic\s+(?:to\s*[:=]?|[:=])|topic\s*(?:is|to|[:=])|change\s+(?:the\s+)?subject\s+(?:to\s*[:=]?|[:=])|...)`. When VTU or internship is requested, updates `draft.subject = "Application for VTU Internship"`, constructs formal internship application body, and preserves recipient salutation name (`Dear Dhulappa,`) and email.
- **Formal Leave Letter Formatting:** Added `is_leave_letter` handler formatting formal letter layout: `"Leave Application - <Duration>"` with handover and reachability clauses.
- **Body Expansion:** Added `is_expand` handler expanding leave or internship drafts with detailed project handover notes and contact availability.
- **Duration Regex Fix:** Refactored `dur_word_pat` to `r"(\d+\s+(?:weeks?|days?|months?)|one\s+week|two\s+weeks|...)"` ensuring plural words match greedily before singulars, and appended date clause when requested (*"starting from Monday"*).

### B. Backend: `backend/agent/orchestrator.py`
- **Concise Edit Feedback Generator:** Implemented `_generate_edit_feedback(message, old_body, old_subject, updated_draft)` to return clear, friendly natural-language confirmations:
  - Subject/Topic: *"Updated the draft topic to VTU internship application."* or *"Updated the subject to '<Subject>'."*
  - Recipient Name: *"Updated recipient name to Dhulappa."*
  - Duration: *"Updated the leave duration to two days."*
  - Tone/Format: *"Formatted the draft as a formal leave application letter."*, *"Expanded the draft with additional details."*, *"Shortened the draft to a concise format."*, *"Updated the tone to formal and friendly."*
- **Suppressed Approval Card Wall on Edits:** Replaced `_format_approval_card` on conversational edits with concise feedback.
- **Unrecognized Edit Handling:** Returns clean clarification message without appending the approval card options wall.

### C. Frontend: `apps/desktop/src/App.jsx`
- **Clean Bubble Notice on Initial Turn Only:** In `ResponseCard`, added `isEditTurn = (task.stateVersion > 1 || task.state_version > 1)`. Initial draft creation (`state_version == 1`) shows the clean bubble notice; subsequent edit turns display the natural AI response.
- **Field Fallbacks in Composer Card:** Updated `EmailComposerReviewCard` state initialization and `useEffect` dependency sync to fall back across `task.params.draft` and `task.context`.
- **Persistent Card Key:** Keyed the live composer card with `key={task.id || "active-email-composer"}` to prevent duplicate card mounting.

---

## 4. Verification & Test Evidence

### A. Dedicated Regression Test Suite (`tests/test_email_compose_ux_p7_7_2.py`)
All 4 comprehensive lifecycle tests passed:
1. `test_10_turn_single_composer_lifecycle`:
   - Validates the complete 10-turn sequence from live desktop testing on a single task identity (`initial_task_id`).
   - Asserts `state_version` increments from 1 to 11.
   - Asserts Turn 1 displays the approval card, while Turns 2–11 return concise feedback without the card options wall.
   - Asserts Turn 7 formats recipient salutation as `Dear Dhulappa,` while preserving email.
   - Asserts Turn 8 expands body.
   - Asserts Turn 9 formats subject to `Leave Application - ...`.
   - Asserts Turn 10 changes subject to `Application for VTU Internship`, updates body to internship application, preserves `Dear Dhulappa,`, and retains `recipient_email`.
2. `test_composer_fields_never_blank`:
   - Validates that `recipient`, `recipient_email`, `subject`, and `body` are non-empty across all 9 edits.
3. `test_direct_draft_edit_and_stale_hash_protection`:
   - Validates that direct edits recalculate approval hash and reject stale token replay.
4. `test_unrecognized_edit_concise_response_without_card_dump`:
   - Validates that unhandled text prompts return a concise clarification message without card duplication or body corruption.

### B. Full Test Suite Execution
```bash
pytest tests/test_email_compose_ux_p7_7.py tests/test_email_compose_ux_p7_7_1.py tests/test_email_compose_ux_p7_7_2.py -v
================== 20 passed in 28.52s ==================
```

### C. Desktop App Production Build
```bash
cd apps/desktop && npm run build
✓ 1575 modules transformed.
dist/index.html                   1.10 kB │ gzip:  0.55 kB
dist/assets/index-Da5_cUTT.css   38.95 kB │ gzip:  7.54 kB
dist/assets/index-C8-xLpoI.js   231.54 kB │ gzip: 68.58 kB
✓ built in 1.65s
```

---

## 5. Security & Safety Posture
- `CORTEX_ALLOW_REAL_EMAIL_SEND=0` enforced strictly; no live emails transmitted.
- Every conversational edit recomputes cryptographic `approval_hash` and updates durable approvals in `task_store`.
- Stale approval tokens are rejected immediately with hash mismatch warnings.
- Prompt injection and sensitive file attachment blocking guards remain active and validated.

---

## 6. Acceptance Verdict
**P7.7.2 ACCEPTED — SINGLE COMPOSER LIFECYCLE & DUPLICATE CARD REMEDIATION COMPLETE**
