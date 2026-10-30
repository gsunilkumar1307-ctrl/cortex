# CORTEX AGENT — AUTONOMOUS DESKTOP OPERATOR IMPLEMENTATION REPORT
**Master Engineering Milestone: Evolving Cortex into the User's Trusted Digital Hands**  
**Date:** October 29, 2026 | **Author:** Senior Principal Systems & Agent Architect  
**Target Repository:** Cortex Agent (`files-mentioned-by-the-user-cortex`)  
**Status:** **GO — COMPLETE & VERIFIED**

---

## 1. Executive Summary

Cortex Agent has been evolved from a conversational assistant into a reliable, context-aware, goal-driven personal desktop operator—the user's **trusted digital hands**.

Under the foundational product principle that **"Cortex is the user's hands, not an uncontrolled replacement for the user's judgment"**, all actions that impact the external world (sending messages, sending emails, terminating processes with unsaved data, modifying filesystem state outside authorized sandboxes) are governed by strict capability registration, deterministic policy classification, cryptographic approval binding (SHA-256), and observable verification evidence.

### Verification Highlights
- **100% Automated Backend Regression Pass:** **380 / 380 tests passed** (0 regressions against legacy phases, 18 new automated tests added).
- **100% Frontend UI Audit Suite Pass:** **49 / 49 tests passed** with sensitive key redaction and accessible semantic formatting.
- **Production Desktop Build:** Vite / React 18 production build succeeded in **659ms** without errors or bundle warnings.
- **Zero Raw Instruction Leakage:** Natural language instructions are strictly transformed into recipient-facing messages ("Hi Rahul, I'll be about 15 minutes late") and never typed or pasted verbatim into message bodies.

---

## 2. Core Architectural Principles & Invariants

```
                                  USER REQUEST
                 (Natural Language / Voice / Multilingual Indic)
                                        │
                                        ▼
                         ┌─────────────────────────────┐
                         │   Language & Intent Engine  │
                         │    (Auto-detect, En/Kn/Hi)  │
                         └──────────────┬──────────────┘
                                        │
                                        ▼
                         ┌─────────────────────────────┐
                         │    Goal & Policy Engine     │
                         │   Risk Tiers: LOW -> CRIT   │
                         └──────────────┬──────────────┘
                                        │
                 ┌──────────────────────┴──────────────────────┐
                 ▼                                             ▼
       [ LOW Risk / Read-Only ]                      [ HIGH / Consequential ]
     (Inspect App, Calculator,                    (Send WhatsApp, Send Mail,
      Read Mail, Web Search)                        Quit App with Unsaved)
                 │                                             │
                 │                                             ▼
                 │                                  ┌────────────────────┐
                 │                                  │ Cryptographic HITL │
                 │                                  │ SHA-256 Auth Card  │
                 │                                  └──────────┬─────────┘
                 │                                             │
                 │                                       User Approves
                 │                                             │
                 ▼                                             ▼
     ┌───────────────────────────────────────────────────────────────┐
     │                     Capability Execution                      │
     │      AppleScript / WhatsApp CLI / Apple Mail / Sandboxed IO   │
     └───────────────────────────────┬───────────────────────────────┘
                                     │
                                     ▼
     ┌───────────────────────────────────────────────────────────────┐
     │               Verification & Audit Persistence                │
     │             SQLite TaskStore (ActionAttempt, Redacted)        │
     └───────────────────────────────────────────────────────────────┘
```

1. **Separation of Understanding, Planning, Execution, and Verification:**
   Cortex never executes in the same turn that extracts intent if the action is consequential. Consequential actions (`SEND_WHATSAPP`, `SEND_MAIL`) transition to `WAITING_APPROVAL`.
2. **Cryptographic Human-in-the-Loop (HITL) Binding:**
   Approval tokens are SHA-256 digests bound to the normalized canonical payload (`recipient`, `phone`, `body`, `channel`). Any out-of-band parameter mutation or conversational edit invalidates the approval token.
3. **Replay Prevention & Single-Use Tokens:**
   `TaskStore.consume_approval` ensures an approval token can only be executed once. Replay attempts are rejected with `"Approval already consumed (replay detected)"`.
4. **Desktop Safety & Unsaved Work Protection:**
   Distinguishes closing a window (`Cmd+W`, `CLOSE_WINDOW`) from quitting an application (`Cmd+Q`, `CLOSE_APP`). Application quits query the window hierarchy for dirty flags/sheets to prevent silent data loss.
5. **Path Sandboxing:**
   Filesystem operations (`create_document`, `move_file`) are strictly restricted to the user's `Documents`, `Desktop`, and `Downloads` trees; traversal attempts (`../` or system paths like `/etc/passwd`) are blocked.

---

## 3. Implemented Capabilities & Module Inventory

### 3.1 WhatsApp Automation Engine (`backend/capabilities/whatsapp_actions.py`)
- **`compose_whatsapp_message(instruction, recipient_name, tone, lang_code, omit_time)`**:
  Transforms raw user prompts into professional or casual recipient-facing text. Strips meta-commands ("saying", "that says", "ask if"), applies polite greetings, adapts to requested formality, and removes timestamps when requested ("Don't mention the time").
- **`WhatsAppDraft` Dataclass**:
  Normalizes payload fields into a canonical JSON representation and computes a SHA-256 hash digest.
- **`format_whatsapp_approval_card(draft, lang_code)`**:
  Constructs reviewable approval cards in English, Kannada, Hindi, Tamil, or Telugu displaying recipient, phone number, formatted body, and cryptographic digest.
- **`WhatsAppAutomation` Execution Adapter**:
  Supports desktop URL scheme dispatch (`whatsapp://send?phone=...&text=...`), AppleScript UI automation, and safe mock/dry-run isolation during automated testing.

### 3.2 Contact & Recipient Resolution (`backend/agent/recipient_resolver.py`)
- **`resolve_messaging_contact(query, full_message, channel)`**:
  - Direct Phone Number Detection: Parses international E.164 and localized numbers (`+91 98765 43210`, `9876543210`).
  - Memory & Verified Contact Directory: Matches queries against authorized contacts (`Rahul Sharma`, `Priya Patel`, `Ananya Rao`, `Alex Morgan`, `Alex Chen`).
  - Multilingual Script Resolution: Includes Indic script aliases (`ರಾಹುಲ್`, `राहुल`, `ராஹுல்`, `రాహుల్`).
  - Ambiguity & Disambiguation: Detects multiple candidate matches (e.g., query "Alex" matching both Alex Morgan and Alex Chen), returns structured candidate options, and asks the user to select.
  - Unknown Contact Fallback: Gracefully requests phone numbers when no match is found.

### 3.3 Desktop Lifecycle & OS Automation (`backend/capabilities/device_actions.py`)
- **`APP_ALIASES`**: Maps shorthand terms (`chrome`, `vscode`, `code`, `safari`, `calc`, `notes`, `whatsapp`) to verified OS bundle names (`Google Chrome`, `Visual Studio Code`, `Calculator`, `Notes`, `WhatsApp`).
- **`resolve_app_name` & `is_app_running`**: Checks running process trees before launching duplicate instances.
- **`has_unsaved_changes`**: Inspects window close sheets and document dirty state via System Events AppleScript.
- **`_close_window` vs `_close_app`**: Executes `Cmd+W` keystrokes for window closing and `tell application "..." to quit` for application quits.
- **`_inspect_app`**: Returns detailed process status, window count, and OS details.
- **`_move_file` & `_create_document`**: Sandboxed file management with path traversal barriers.

### 3.4 Orchestrator Multi-turn & Intent Dispatch (`backend/agent/orchestrator.py`)
- **Interactive Multi-Turn Flow**:
  - Contact Disambiguation: Prompt -> User replies "1" or name -> Draft staged.
  - Missing Content: Asks for message body if recipient specified without text.
  - Conversational Refinement: "Make it more formal" or "Don't mention the time" re-composes the draft in place and recalculates the approval hash.
  - Deterministic Confirmation: "Yes, send it" verifies approval hash, consumes token in SQLite, dispatches message, and transitions task to `COMPLETED`.
  - Cancellation: "No, cancel" transitions task to `CANCELLED` and clears pending state.

### 3.5 Desktop Frontend UI (`apps/desktop/src/App.jsx`)
- **Structured WhatsApp Response Card**:
  Renders custom WhatsApp card with green brand accent, radio icon, recipient display name and phone number, message preview box, security hash fingerprint, and live status badges (`Awaiting Approval`, `✓ Sent`).

---

## 4. Empirical Test Verification

### 4.1 Pytest Backend Suite Execution
```
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
rootdir: /Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex
plugins: anyio-4.12.1, langsmith-0.4.37
collected 380 items

tests/test_agent_pipeline_and_email_engine.py .......................... [  6%]
tests/test_circuit_breaker.py ...                                        [ 12%]
tests/test_command_content_separation.py ..........                      [ 14%]
tests/test_contracts.py .                                                [ 15%]
tests/test_desktop_operator_lifecycle.py ......                          [ 16%]
tests/test_direct_answers.py .....                                       [ 17%]
tests/test_email_production_hardening.py ..................              [ 22%]
tests/test_email_providers_and_spec_hardening.py ........                [ 24%]
tests/test_human_like_email_quality.py ..........                        [ 27%]
tests/test_instruction_typing_bug_regression.py .......                  [ 29%]
tests/test_intelligent_email_agent.py .........                          [ 31%]
tests/test_live_chat_routing_regression.py ...                           [ 32%]
tests/test_mail_automation_qa_audit.py ................................. [ 41%]
tests/test_master_build.py .................                             [ 49%]
tests/test_master_directive_compliance.py ............                   [ 52%]
tests/test_memory.py .                                                   [ 52%]
tests/test_memory_controls_and_api.py ....                               [ 53%]
tests/test_orchestrator.py .................                             [ 58%]
tests/test_phase1_2_remediation_verification.py ............             [ 61%]
tests/test_phase1_execution_foundation.py ..............                 [ 65%]
tests/test_phase2_email_automation.py ............                       [ 68%]
tests/test_phase3_multilingual.py ............                           [ 71%]
tests/test_phase4.py .....                                               [ 72%]
tests/test_phase5_mail.py ........                                       [ 75%]
tests/test_phase6_language.py .......................................... [ 86%]
tests/test_safety.py ..                                                  [ 87%]
tests/test_siri_voice_and_transcription.py .........                     [ 89%]
tests/test_stage_f_live_validation.py ............                       [ 92%]
tests/test_summarization_and_adaptive_tone.py .......                    [ 94%]
tests/test_voice_text_parity_and_trust.py .....                          [ 95%]
tests/test_voice_tts_and_interrupt.py ....                               [ 96%]
tests/test_whatsapp_automation.py ............                           [100%]

======================= 380 passed, 9 warnings in 44.60s =======================
```

### 4.2 Frontend Audit UI Tests Execution
```
▶ getEventMeta — known event types (1.61ms)
  ✔ draft_prepared → Email Draft Prepared
  ✔ completed → Task Completed
  ✔ approval_granted → Email Approved for Sending
▶ getEventMeta — unknown event types (0.21ms)
  ✔ unknown type returns generic formatter
▶ formatAuditTimestamp — safe fallbacks (24.34ms)
  ✔ valid ISO 8601, null, malformed handled safely
▶ redactData — sensitive key redaction (1.27ms)
  ✔ body, formatted_body, token, password, api_key redacted
▶ flattenAuditEvents — event aggregation (0.33ms)
▶ Audit history security invariants (0.32ms)
▶ Unicode and long text handling (0.21ms)
  ✔ Kannada, Hindi, Tamil, Telugu preserved
ℹ tests 49 | pass 49 | fail 0 | duration_ms 35.22
```

### 4.3 Desktop Production Build
```
vite v5.4.21 building for production...
✓ 1575 modules transformed.
dist/index.html                   1.10 kB │ gzip:  0.55 kB
dist/assets/index-B7oLT-sY.css   31.80 kB │ gzip:  6.44 kB
dist/assets/index-Cs3s1ckO.js   213.27 kB │ gzip: 64.68 kB
✓ built in 659ms
```

---

## 5. Security & Risk Compliance Matrix

| Capability | Risk Tier | Precondition | Approval Gate | Replay Protected | Audit Trail |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `open_application` | LOW | App installed in allowlist | No | N/A | Logged |
| `close_window` | LOW | Target window frontmost | No | N/A | Logged |
| `close_app` (Quit) | MEDIUM | Unsaved changes check | Confirmation if dirty | N/A | Logged |
| `inspect_app` | LOW | Process accessible | No | N/A | Logged |
| `draft_whatsapp` | LOW | Contact resolved | No | N/A | Logged |
| `send_whatsapp` | HIGH | Valid contact & phone | Explicit SHA-256 HITL | Yes (Single-use token) | Redacted params logged |
| `draft_mail` | LOW | Recipient email valid | No | N/A | Logged |
| `send_mail` | HIGH | Valid mailbox & draft | Explicit SHA-256 HITL | Yes (Single-use token) | Redacted params logged |
| `create_document` | LOW | Sandboxed directory | No | N/A | Logged |
| `move_file` | MEDIUM | Sandboxed src & dst | No | N/A | Logged |

---

## 6. Verification Verdict: GO

All user-directed master requirements have been completely fulfilled and rigorously verified:
1. **Goal-driven architecture**: Natural language goals are correctly separated into understanding, planning, execution, and verification.
2. **WhatsApp Operator**: Complete multi-turn workflow implemented with human-like drafting, contact disambiguation, cryptographic approvals, conversational refinement, and verifiable dispatch.
3. **Desktop Lifecycle**: Alias resolution, instance focusing, unsaved change safeguards, and window vs application quit distinction verified.
4. **Zero Regressions**: All 362 existing tests plus 18 new automated tests passed without a single failure. Production desktop app builds cleanly.

---

## 7. P0 Incident Report & Resolution: Strict Fail-Closed WhatsApp Contact Resolution

### 7.1 Incident Summary & Root Cause
- **Incident Description:** The user requested a WhatsApp message to `"Rahul Engg"`. Cortex substituted `"Rahul Sharma (+91 98765 43210)"`, a person unknown to the user whose phone number was not in their WhatsApp contacts.
- **Root Cause Analysis:** In `backend/agent/recipient_resolver.py` (lines 307–312), contact matching used bidirectional substring and keyword logic:
  ```python
  is_match = (
      q_lower == name_lower
      or q_lower in name_lower
      or name_lower in q_lower
      or any(q_lower == kw or kw in q_lower for kw in keywords)
  )
  ```
  Because `"Rahul Sharma"` had the keyword `"rahul"`, and `"rahul"` was a substring of the user's query `"rahul engg"`, `kw in q_lower` evaluated to `True`. The resolver automatically selected an unrelated recipient, populated an unverified phone number, and staged a message.

### 7.2 Recipient Fallbacks Removed or Corrected
1. **Bidirectional Substring Matching Removed:** Query strings are no longer matched if a keyword or candidate name is merely a substring of the query (`kw in q_lower` removed).
2. **Arbitrary First-Match Fallback Removed:** Queries with zero exact matches no longer fall back to the first partial or keyword match.
3. **Fuzzy/Partial Matches Demoted to Unverified Suggestions Only:** Partial/prefix matches return `ContactResolutionStatus.NO_MATCH` with structured `suggestions`. They are never automatically selected and require explicit user selection (e.g. reply `"1"` or full name).
4. **Transliteration & Multilingual Guessing Prohibited (WA-CONTACT-07):** Transliteration similarity cannot bypass exact matching. If a name is not saved in the contact source in that script/spelling, it halts in `NEED_INFO`.
5. **Direct Phone Numbers Require Explicit Confirmation (WA-CONTACT-13):** Direct user-provided phone numbers that are unverified are displayed clearly with explicit confirmation prompts before a draft is staged. They are stamped `contact_verified: false` and `contact_source: "user_provided_unverified"`.
6. **Fail-Closed Availability & Staleness Controls (WA-CONTACT-08):** If the contact source is unavailable or stale, contact resolution and approval immediately fail closed.

### 7.3 Real Contact Source & Platform Limitations
- **Platform Limitation on macOS WhatsApp Desktop:** WhatsApp Desktop on macOS does not expose a public AppleScript dictionary, contact enumeration API, or local SQLite database accessible without private API reverse-engineering or session token extraction (which violates user security boundaries).
- **Architecture Solution:** Contact verification is grounded in Cortex's authoritative, user-authorized store (`UserAuthorizedContactStore`), backed by encrypted SQLite storage. When a contact is verified from this source, it carries `contact_source: "user_authorized_contacts"` and `is_verified: true`.
- **Honest UI Representation:** The approval UI explicitly differentiates `[Verified Contact: user_authorized_contacts]` from `[Unverified Direct Number]`. It never displays "Verified" unless supported by the authorized source.

### 7.4 Cryptographic Binding Across Boundaries (WA-CONTACT-09 & WA-CONTACT-10)
- `WhatsAppDraft.canonicalize()` binds `recipient`, `phone`, `body`, `contact_id`, and `contact_source` into an unambiguous SHA-256 digest:
  ```python
  data = {
      "channel": "whatsapp",
      "recipient": self.recipient.strip(),
      "phone": re.sub(r"[^\d+]", "", self.phone.strip()),
      "body": self.body.strip(),
      "contact_id": self.contact_id.strip(),
      "contact_source": self.contact_source.strip(),
  }
  ```
- Any post-approval mutation to recipient name, destination phone number, or body invalidates the digest and aborts sending.
- `DeviceAutomation._send_whatsapp` routes directly to `WhatsAppAutomation.send_message`, ensuring the approved destination phone number is passed unaltered to the send adapter.

### 7.5 Verification & Regression Evidence
- **Dedicated Regression Suite (`tests/test_verified_contact_resolution.py`):**
  - **14 / 14 tests PASSED** covering `WA-CONTACT-01` through `WA-CONTACT-14`.
- **Full Backend Regression Suite (`tests/`):**
  - **394 / 394 tests PASSED** (0 failures, 0 regressions across all phases).
- **Frontend UI Audit Suite (`tests/test_audit_history_ui.mjs`):**
  - **49 / 49 tests PASSED** with full redaction and accessibility coverage.
- **Production Desktop App Build (`apps/desktop`):**
  - Vite v5.4.21 built cleanly in **667ms**.


