# CORTEX AGENT — P7.7.1 CONVERSATIONAL DRAFT EDITING RELIABILITY REPORT

**Phase:** P7.7.1 — Conversational Draft Editing Reliability Fix  
**Mode:** Targeted Audit → Root-Cause Reproduction → Minimal Implementation → Regression → Live API Verification  
**Status:** COMPLETED & VERIFIED  
**Final Verdict:** `P7.7.1 ACCEPTED — CONVERSATIONAL DRAFT EDITING VERIFIED`

---

## 1. EXECUTIVE SUMMARY & ROOT CAUSE ANALYSIS

During supervised live testing of Cortex P7.7, a conversational editing failure was identified where successive natural-language modification requests did not reliably update the canonical email draft.

### The Live Failure Sequence
The user issued this 5-step sequence in the Cortex desktop application:
1. `send mail to myself for requesting a leave permission`
2. `make it more formal and friendly tone`
3. `recipient name is sunil`
4. `make it short`
5. `make the leave permission for 1 week`

**Observed Defects in P7.7:**
1. **Unresolved Placeholder:** Salutation remained `Dear [Recipient / Manager],`.
2. **Missing Duration:** The 1-week leave duration was never incorporated into the message body.
3. **Catastrophic Instruction Leakage:** In `backend/agent/email_engine.py` (lines 2322–2334), unrecognized instructions fell through to `paras.append(edit_instruction.strip())`, causing the user's meta-instructions (`recipient name is sunil`, `make it short`, `make the leave permission for 1 week`) to be literally injected as body paragraphs!
4. **Missing "short" Keyword:** `is_shorten` matched `("shorter", "concise", "brief", "shorten", "condense", "summarize")` but omitted `"short"`, causing `"make it short"` to fail to trigger shortening.
5. **Missing Recipient Name / Salutation Extractor:** Instructions like `recipient name is sunil` or `recipient is sunil` only matched email address patterns, missing plain name directives.
6. **Tone Replacement No-Op:** `make it more formal and friendly tone` matched `is_formal` and ran regex replacements for `Hi -> Dear` and `Thanks -> Sincerely`. Because the initial draft already had `Dear` and `Sincerely`, the edit was a complete no-op and ignored `"friendly tone"`.
7. **Frontend State Desynchronization:** In `apps/desktop/src/App.jsx`, `EmailComposerReviewCard` lacked `task.stateVersion` and `task.params.formatted_body` in its `useEffect` dependency array, risking stale draft display.
8. **Silent Orchestrator Persistence Gaps:** In `backend/agent/orchestrator.py`, `task.params["draft"]` was not updated to `updated_draft.to_dict()`, `task.approval_hash` was not updated on the task root, `task.state_version` was not incremented, and unapplied edits falsely reported success.

---

## 2. TARGETED IMPLEMENTATION & REMEDIATION

### A. Email Engine (`backend/agent/email_engine.py`)
1. **Recipient Name & Salutation Handler:**
   - Extracts recipient names from diverse phrasings: `recipient name is X`, `recipient is X`, `address recipient as X`, `address him as X`, `name is X`, `dear X`, `salutation to X`.
   - Properly titles names (e.g. `dr. ramesh` -> `Dr. Ramesh`, `sunil` -> `Sunil`).
   - Updates the opening salutation to `Dear {Name},` and eliminates all lingering bracketed placeholders (`[Recipient / Manager]`, `[Recipient]`, `[Manager]`, `[Name]`).
2. **Leave Duration & Period Handler:**
   - Detects leave duration directives: `make the leave permission for 1 week`, `make leave for 1 week`, `for 1 week`, `for 3 days`, `leave duration is one month`.
   - Modifies the request clause to `request leave of absence for {duration}` cleanly without duplicate prepositions.
3. **Tone & Conciseness Processing:**
   - Added `\bshort\b` to word boundary matching: `r"\b(?:short|shorter|concise|brief|shorten|condense|summarize|compress)\b"`.
   - First-class support for combined `is_formal and is_friendly`: Produces courteous, warm, respectful wording (`"I hope this email finds you well..."`, `"Thank you for your understanding and consideration."`, `"Sincerely,\nSunil Kumar"`).
   - Paragraph-based concise shortening that preserves the entire sign-off block (`Sincerely,\nSunil Kumar`) without dropping lines.
4. **Elimination of Catastrophic Fallthrough Leakage:**
   - Replaced raw text paragraph insertion with strict explicit addition detection (`r"^(?:add\s+(?:paragraph|detail|note|line|text)?\s*[:=]?|insert\s+[:=]?|include\s+[:=]?)\s*(.+)"`).
   - Unrecognized edit instructions are safely logged in audit notes and return an unchanged draft without corrupting the body.

### B. Orchestrator Sync & Honesty (`backend/agent/orchestrator.py`)
1. **Material Change Detection (`is_changed`):**
   - Compares body, subject, recipient, account, attachments, CC, and BCC before and after edit.
   - If no change occurred, Cortex honestly informs the user:
     `"I couldn't identify the specific change to make from '{message}'. The draft remains unchanged. You can ask to change the recipient, subject, duration, tone, or specific details."`
2. **State & Hash Synchronization:**
   - On valid edit: Updates `task.approval_hash`, `task.params["approval_hash"]`, `task.params["draft"]`, `task.params["formatted_body"]`, and increments `task.state_version += 1`.
   - Calls `self._persist_task(task)` to commit changes to durable task storage.

### C. Desktop UI Live Card Sync (`apps/desktop/src/App.jsx`)
- Added `task?.stateVersion`, `task?.approvalHash`, `task?.params?.formatted_body` to `EmailComposerReviewCard`'s `useEffect` dependencies, guaranteeing immediate UI reflection upon backend conversational edit updates.

---

## 3. VERIFICATION & EMPIRICAL EVIDENCE

### A. Exact 5-Step Sequence Verification
Tested end-to-end through `CortexOrchestrator.chat()`:

```
TURN 1: "send mail to myself for requesting a leave permission"
Dear Sunil Kumar,

I am writing to respectfully request leave of absence. I will ensure that my pending tasks and responsibilities are coordinated and addressed prior to taking leave.

Thank you for your consideration.

Sincerely,
Sunil Kumar
--------------------------------------------------------------------------------
TURN 2: "make it more formal and friendly tone"
Dear Sunil Kumar,

I hope this email finds you well. I am writing to respectfully request leave of absence. I will ensure that all my pending tasks and responsibilities are fully coordinated and addressed prior to taking leave.

Thank you for your understanding and consideration.

Sincerely,
Sunil Kumar
--------------------------------------------------------------------------------
TURN 3: "recipient name is sunil"
Dear Sunil,

I hope this email finds you well. I am writing to respectfully request leave of absence. I will ensure that all my pending tasks and responsibilities are fully coordinated and addressed prior to taking leave.

Thank you for your understanding and consideration.

Sincerely,
Sunil Kumar
--------------------------------------------------------------------------------
TURN 4: "make it short"
Dear Sunil,

I am writing to respectfully request leave of absence. I will ensure all pending responsibilities are coordinated before my leave.

Thank you for your consideration.

Sincerely,
Sunil Kumar
--------------------------------------------------------------------------------
TURN 5: "make the leave permission for 1 week"
Dear Sunil,

I am writing to respectfully request leave of absence for 1 week. I will ensure all pending responsibilities are coordinated before my leave.

Thank you for your consideration.

Sincerely,
Sunil Kumar
```

**Outcome:**
- Salutation: `Dear Sunil,` (Properly addressed, zero brackets/placeholders)
- Duration: `for 1 week` (Explicitly included in the leave request)
- Tone: Formal, polite, and friendly
- Conciseness: Clean, single-paragraph request with complete handover commitment
- Instruction text leakage: ZERO. Prompts never leaked into body paragraphs.
- State version: Incremented cleanly on each turn (`v1 -> v2 -> v3 -> v4 -> v5`).

### B. Order-Independence Verification
Tested all **24 permutations** of the 4 edit instructions (`test_permutations_of_conversational_edits`). Every permutation consistently yielded a pristine draft containing `Dear Sunil,`, `1 week`, no placeholders, and no instruction text leakage.

### C. Stale Hash & Security Gate Verification
- Attempting approval with an older hash (`initial_hash`) after an edit is rejected with `Approval token mismatch`.
- Approving with the updated hash succeeds and passes to the execution engine where it is safely halted by the `CORTEX_ALLOW_REAL_EMAIL_SEND` safety gate.

---

## 4. REGRESSION TEST RESULTS

All deterministic test suites executed successfully without regression:

| Test Suite | Tests Run | Result | Focus Area |
| :--- | :---: | :---: | :--- |
| `tests/test_email_compose_ux_p7_7_1.py` | 8 | **PASSED** | P7.7.1 5-step sequence, 24 permutations, honest unhandled edit, hash replay |
| `tests/test_email_compose_ux_p7_7.py` | 8 | **PASSED** | P7.7 Unified composer, dual-mode editing, cryptographic security gate |
| `tests/test_email_intelligence_p7_6.py` | 13 | **PASSED** | P7.6 Body hygiene, conversational thread context, sender search |
| `tests/test_email_intelligence_batch1.py` | 10 | **PASSED** | Deterministic intent routing, recipient resolution |
| `tests/test_email_intelligence_batch2.py` | 27 | **PASSED** | Goal-oriented email intelligence, attention filters |
| **Total Passed** | **66** | **100% PASS** | Zero regressions |

Desktop application build (`npm run build` in `apps/desktop`): **SUCCESS (752ms)**.

---

## 5. FINAL CONCLUSION & ACCEPTANCE VERDICT

All reported live defects from the P7.7 supervised Mail pilot have been eliminated:
1. `Dear [Recipient / Manager],` is cleanly replaced by the resolved recipient name.
2. Leave durations (`1 week`) are accurately extracted and inserted.
3. Conversational prompts (`make it short`, `recipient name is sunil`) are never injected into email content.
4. Unrecognized inputs are honestly reported without corrupting the draft.
5. All 24 edit permutations produce coherent, concise drafts.

**VERDICT:**  
`P7.7.1 ACCEPTED — CONVERSATIONAL DRAFT EDITING VERIFIED`
