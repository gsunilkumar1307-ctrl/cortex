# CORTEX AGENT — TASK 6 REPORT: PRODUCTION-READY APPLE MAIL, WHATSAPP & NOTES

## Executive Summary

Task 6 hardened and verified the existing Cortex Agent integrations for **Apple Mail**, **WhatsApp**, and **Apple Notes** sequentially. All three integrations operate through the authoritative `CortexOrchestrator`, maintaining conversation context, strict permission models, cryptographic single-use approval replay protection, and real macOS system verification.

Prior task commits were preserved:
- Task 1: `2cb7d7a` (Core execution path repair)
- Task 2: `1260bc9` (Live macOS screen observation)
- Task 3: `a645dd4` & `4836410` (Verified Safari research & contextual article navigation)
- Task 4: `cc0972d` (Verified Finder inspection)
- Task 5: `36a7f52` (Cross-workflow reliability & live acceptance hardening)

Full regression testing across Tasks 1–6 yielded **80 passed tests out of 80** (`tests/test_task*.py`, 319.21s runtime). The desktop frontend build (`vite build`) compiled cleanly.

---

## Phase 1 — Apple Mail

### 1. Requirements & User Workflow
- **Prompt:** `"Draft an email to Rahul about tomorrow's project meeting. Do not send it."`
- **Follow-ups:**
  - `"Make it shorter and more formal"`
  - `"Change the subject to: Project Sync Tomorrow"`
  - `"Cancel this draft"`
  - `"Send it"`

### 2. Issues Diagnosed & Repaired
1. **Instruction vs. Content Separation:**
   - Previous logic copied indirect topic phrases like `"about tomorrow's project meeting"` into the draft body.
   - Fixed `email_engine.py` to recognize indirect topic markers and synthesize professional, recipient-facing text: `"I am writing regarding tomorrow's project meeting. Please let me know your thoughts and availability."`
   - Fixed AI keyword substring match: word `"ai"` previously matched `"availability"`, mistakenly appending AI research bullets to meeting emails. Replaced with word-boundary regex `\b(?:ai|artificial intelligence)\b`.
2. **Subject Edit Robustness:**
   - Prompt `"Change the subject to: Project Sync Tomorrow"` contains a colon after `to`. The regex previously missed colons and lowercased the subject. Updated regex in `update_draft_with_edit` to handle colons/equals and preserve exact subject casing.
   - When updating draft subjects, deleted the old draft to prevent duplicate drafts in Apple Mail.
3. **Draft Verification in Apple Mail:**
   - In macOS Apple Mail, deleted messages can remain in the drafts mailbox with `deleted status = true` before purging.
   - Enhanced `verify_draft_created` in `backend/capabilities/mail_actions.py` to query drafts with `whose deleted status is false` and verify subject and recipient match.
   - Clearly reported: `"Draft created for Rahul with subject '...'. The email has not been sent."`
4. **Cancellation & Draft Cleanup:**
   - On cancellation (`"Cancel this draft"`), `mail_actions.delete_draft()` moves matching drafts to trash and closes unsent compose windows.
5. **Approval Transition on "Send it":**
   - Staging a draft-only email previously marked the `DRAFT_MAIL` task as `COMPLETED`. When the user followed up with `"Send it"`, `self.approve()` rejected the call as an approval replay.
   - Fixed `orchestrator.py` to transition the task to `TaskCommand.SEND_MAIL` with `status = TaskStatus.WAITING_APPROVAL` and bind an approval hash before invoking `approve()`.
   - Prevented external transmission to test/example domains during automated tests.

### 3. Test Suite: `tests/test_task6_apple_mail.py` (6 passed)
- `test_01_draft_creation_and_not_sent_reporting`: Verified recipient resolution, body synthesis, Apple Mail verification, and "The email has not been sent" message.
- `test_02_conversational_refinement_shorter_and_formal`: Verified tone transformation without loss of draft context.
- `test_03_subject_change_with_colon`: Verified `"Change the subject to: Project Sync Tomorrow"` preserves casing and replaces subject.
- `test_04_cancellation_and_draft_cleanup`: Verified draft cancellation and cleanup from mailbox.
- `test_05_explicit_approval_send_and_single_use_hash`: Verified single-use token consumption on `"Send it"`.
- `test_06_replay_protection`: Verified rejection of replayed approval tokens.

---

## Phase 2 — WhatsApp

### 1. Requirements & User Workflow
- **Prompt:** `"Prepare a WhatsApp message to Rahul saying I will arrive 15 minutes late. Do not send it."`
- **Follow-ups:**
  - `"Make it more formal"` / `"Don't mention the time"`
  - Direct unverified phone numbers (`+14155552671`)
  - Ambiguous contact names (`Alex`)
  - Approval and replay attack defense

### 2. Issues Diagnosed & Repaired
1. **Instruction Stripping & Recipient Resolution:**
   - Separated instruction wrapper (`"Prepare a WhatsApp message... Do not send it."`) from body (`"I will arrive 15 minutes late"` -> `"Hi Rahul, Running about 15 minutes late, see you soon!"`).
   - Resolved Rahul to `+91 98765 43210` from verified contacts.
   - Tagged task as `draft_only = True` and surfaced: `"WhatsApp message drafted (Draft only — not sent): Recipient: Rahul (+91 98765 43210)... ⚠️ Draft only — not sent."`
2. **Draft-Only Review Routing in Orchestrator:**
   - `orchestrator.py` previously set `step = "draft_only_review"` in `pending_action`, but `chat()` only matched `step == "confirm_send"`. Subsequent conversational turns ("Make it more formal", "Cancel") fell through.
   - Updated `chat()` routing to handle `step in ("confirm_send", "draft_only_review")`.
   - Blocked premature send attempts while in draft-only mode with: `"Cannot send: this task was prepared as draft-only ('Draft only — not sent'). Ready in WhatsApp composer for review."`
3. **Unverified Direct Numbers & Ambiguous Contacts:**
   - Direct numbers trigger an unverified number warning and require explicit confirmation.
   - Ambiguous contact queries (`"Alex"`) list candidates (`1) Alex Morgan`, `2) Alex Chen`) with single-turn disambiguation.
4. **Approval Hash Consumption & Replay Defense:**
   - Passing `task_id` into `device_actions.py` ensured pre-execution durable logging of `WhatsAppSendAttempt` in SQLite `task_store`.
   - Consumed cryptographic approval hash on first approval; replayed attempts return `Approval replay detected: this cryptographic approval was already consumed.`

### 3. Test Suite: `tests/test_task6_whatsapp.py` (6 passed)
- `test_01_instruction_wrapper_separation_and_recipient_resolution`: Verified wrapper stripping, contact resolution, and draft-only status badge.
- `test_02_unverified_direct_phone_number_warning`: Verified unverified direct phone number warning.
- `test_03_multiple_matching_contacts_clarification`: Verified multi-candidate prompt and numeric disambiguation.
- `test_04_draft_only_protection_against_accidental_sending`: Verified blocked dispatch for draft-only staged messages.
- `test_05_explicit_send_approval_and_single_use_hash_consumption`: Verified single-use token consumption and durable attempt recording.
- `test_06_replay_attack_prevention`: Verified replay rejection when reusing approval tokens.

---

## Phase 3 — Apple Notes

### 1. Requirements & User Workflow
- **Prompt:** `"Create a note titled Project Meeting with the following content: [content]."`
- **Follow-ups:**
  - `"Make the title shorter"` -> Rename note without creating duplicates.
  - `"Add this point: Action item for Rahul"` -> Append to active note without creating duplicates.
  - `"Open that note"` -> Activate Apple Notes and show note.

### 2. Issues Diagnosed & Repaired
1. **Title & Body Extraction:**
   - Removed conversational wrappers (`"with the following content:"`, `"content:"`, `"body:"`) from note bodies in `_extract_params`.
2. **Apple Notes Body vs. UI Title Sync:**
   - In macOS Apple Notes, the title displayed in the user interface is derived from the first paragraph/`<h1>` tag of the note's body. Updating `name of note` alone leaves the UI heading unsynchronized.
   - Implemented `update_note_title()` in `backend/capabilities/device_actions.py` to update both `name of note` and the `<h1>` heading in `body`, ensuring immediate UI synchronization.
3. **Appending & Duplicate Prevention:**
   - Added `_note_store` in `DeviceAutomation` and `self.last_note` tracking in `CortexOrchestrator`.
   - Enhanced `_write_note()` to check if the note already exists in Apple Notes before creating a new one.
   - Routed `"open that note"`, `"open the note"`, and `"open this note"` in `contracts.py` to `TaskCommand.WRITE_NOTE` (`action="open_note"`), preventing misclassification as `OPEN_APP`.
   - Implemented `append_note()` to append text to the active note directly in Apple Notes.
   - Implemented `verify_note()` to empirically confirm note existence and plain text content in Apple Notes.

### 3. Test Suite: `tests/test_task6_notes.py` (5 passed)
- `test_01_create_note_strips_conversational_wrappers`: Verified wrapper stripping, note creation, and content verification.
- `test_02_follow_up_make_title_shorter`: Verified note renaming from "Project Meeting" to "Meeting" and UI title sync.
- `test_03_follow_up_add_point_to_existing_note`: Verified point appended to existing note without duplicating notes.
- `test_04_follow_up_open_note`: Verified `open_note` activation.
- `test_05_duplicate_prevention`: Verified `tell application "Notes" to count notes` returns exactly 1.

---

## Full Regression Test Summary

```
tests/test_task1_core_execution_repair.py ...........                    [ 13%]
tests/test_task2_screen_observation.py ..........                        [ 26%]
tests/test_task3_safari_research.py .................                    [ 47%]
tests/test_task4_finder_inspection.py ..............                     [ 65%]
tests/test_task5_cross_workflow_hardening.py ...........                 [ 78%]
tests/test_task6_apple_mail.py ......                                    [ 86%]
tests/test_task6_notes.py .....                                          [ 92%]
tests/test_task6_whatsapp.py ......                                      [100%]

================== 80 passed, 7 warnings in 319.21s (0:05:19) ==================
```

Frontend desktop build:
```
✓ 1575 modules transformed.
dist/index.html                   1.10 kB │ gzip:  0.55 kB
dist/assets/index-B7oLT-sY.css   31.80 kB │ gzip:  6.44 kB
dist/assets/index-B-gvxTOZ.js   214.86 kB │ gzip: 65.08 kB
✓ built in 653ms
```

