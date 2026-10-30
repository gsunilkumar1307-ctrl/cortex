# Cortex Agent — Comprehensive Capability & Architectural Audit

**Audit Date:** 2026-10-29  
**Version Baseline:** Cortex Agent v0.3 / Phase 3 Multi-turn Desktop Operator  
**Auditor Classification:** Independent Empirical Capability Audit  

---

## Executive Summary

This audit assesses the Cortex Agent repository against the master engineering mission: evolving Cortex into a reliable, context-aware, goal-driven personal desktop operator ("the user's digital hands").

Every capability has been verified against actual code paths, AST analysis, live test execution, and runtime interfaces. No capability is assumed to exist based on documentation alone.

---

## 1. Architectural Component Map

```
┌────────────────────────────────────────────────────────────────────────┐
│                      Electron Desktop Client                           │
│  (React 18 + Vite, contextIsolation: true, nodeIntegration: false)   │
│  Minimal Preload Bridge (cortexAPI) • Localhost Session Token Scoping │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP / WebSocket (Port 8765)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        FastAPI Backend Server                          │
│  Session Token Authentication (X-Cortex-Session) • Constant-Time HMAC │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    Cortex Cognitive Orchestrator                       │
│  Intent Understanding • Language Detection • Tone Adaptation           │
│  Task State Machine (11 Statuses) • Optimistic Locking • Audit Trail   │
└─────────┬─────────────────────────┬─────────────────────────┬──────────┘
          │                         │                         │
          ▼                         ▼                         ▼
┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│  Email Engine    │      │ Policy & Safety  │      │ Capability &     │
│  Apple Mail /    │      │ PolicyEngine     │      │ Tool Registry    │
│  Gmail Providers │      │ Risk Tiers       │      │ BaseTool Catalog │
│  SHA-256 Approval│      │ Idempotency Key  │      │ Execution Engine │
└──────────────────┘      └──────────────────┘      └──────────────────┘
          │                         │                         │
          └─────────────────────────┼─────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               Persistence, Memory & Desktop Automation                │
│  SQLite + SQLCipher/Fernet Encrypted Store • TaskStore Relational DB   │
│  Device Automation (macOS / osascript / Playwright / Shell Guards)     │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Capability Audit & Classification Matrix

Capabilities are classified into five strict categories:
- **Implemented and Tested**: Functional in code with automated test coverage.
- **Implemented but Not Verified**: Present in code but lacking dedicated end-to-end tests.
- **Partially Implemented**: Skeleton or partial logic exists, but key workflows/edge cases are missing.
- **Missing**: Not implemented in the codebase.
- **Blocked**: Prevented by operating system permissions or external dependencies.

| Capability Area | Capability Identifier | Status | Real Execution Path & Evidence |
|---|---|---|---|
| **Security & Isolation** | Electron Preload Sandboxing | **Implemented and Tested** | `apps/desktop/electron/preload.cjs`, `main.js`: `contextIsolation: true`, `nodeIntegration: false`, minimal IPC bridge (`cortexAPI`). |
| **Security & Isolation** | Session Authentication | **Implemented and Tested** | `backend/core/auth.py`: Cryptographic token in `.session_secret` (0600 mode), verified via constant-time HMAC on `X-Cortex-Session`. |
| **Security & Isolation** | Web Request Header Scoping | **Implemented and Tested** | `main.js` `onBeforeSendHeaders`: strict origin validation restricts token to `127.0.0.1:8765`. |
| **State & Persistence** | Task State Machine | **Implemented and Tested** | `backend/core/contracts.py`, `backend/agent/orchestrator.py`: `Task`, `TaskStatus`, state versioning, audit trail. |
| **State & Persistence** | Relational Task Recovery | **Implemented and Tested** | `backend/persistence/task_store.py`: SQLite `tasks`, `approvals`, `action_attempts` tables. Concurrency & recovery verified. |
| **State & Persistence** | Encrypted Memory Store | **Implemented and Tested** | `backend/persistence/encrypted_store.py`: Fernet AES-256 encryption with local key derivation. |
| **Email Automation** | Intent Interpretation | **Implemented and Tested** | `backend/agent/orchestrator.py`, `backend/core/contracts.py`: distinguishes email from typing/search. |
| **Email Automation** | Recipient Resolution | **Implemented and Tested** | `backend/agent/recipient_resolver.py`: searches contacts, institutional directory, disambiguates duplicates. |
| **Email Automation** | Human-like Body Generation | **Implemented and Tested** | `backend/agent/email_engine.py`: `convert_instruction_to_recipient_content` transforms user instructions to polite recipient-facing text. |
| **Email Automation** | Apple Mail Draft Creation | **Implemented and Tested** | `backend/integrations/email/apple_mail_provider.py`: genuine drafts created in Apple Mail. |
| **Email Automation** | Cryptographic Approval Gate | **Implemented and Tested** | `backend/core/contracts.py`: `EmailDraft.compute_hash()` binds recipient, subject, body, account, cc, bcc. Single-use replay protection. |
| **Email Automation** | Sent Mail Reconciliation | **Implemented and Tested** | `backend/capabilities/mail_actions.py`: verifies sent message in Sent mailbox with duplicate protection. |
| **Multilingual** | Language Detection & Parity | **Implemented and Tested** | `backend/core/language_detector.py`, `localization.py`: English, Hindi, Kannada, Tamil, Telugu support. |
| **Multilingual** | Translation | **Implemented and Tested** | `backend/core/translator.py`: text translation across supported languages. |
| **Desktop Automation** | Open Application | **Partially Implemented** | `backend/capabilities/device_actions.py`: uses `open -a <app>`. Crashes with unhandled exception on missing app. No alias resolution ("chrome" -> "Google Chrome", "vscode" -> "Visual Studio Code"). No running-state check. |
| **Desktop Automation** | Focus Application | **Partially Implemented** | `backend/capabilities/device_actions.py`: basic osascript activate. No window state inspection. |
| **Desktop Automation** | Close / Quit Application | **Partially Implemented** | `backend/capabilities/device_actions.py`: only quits app via `tell application "<app>" to quit`. Does not distinguish closing window (Cmd+W) from quitting (Cmd+Q). Does not check for unsaved changes. |
| **Desktop Automation** | Inspect Application State | **Missing** | No capability to inspect active windows, frontmost app, or unsaved document state. |
| **Messaging / WhatsApp** | WhatsApp Intent Recognition | **Partially Implemented** | `backend/core/contracts.py`: regex matches "send whatsapp message", but maps to generic `SEND_MESSAGE`. Channel is not preserved in task params. |
| **Messaging / WhatsApp** | WhatsApp Contact Resolution | **Missing** | `RecipientResolver` only handles email addresses; does not resolve phone numbers or WhatsApp contacts. |
| **Messaging / WhatsApp** | WhatsApp Message Composition | **Missing** | No transformation of instructions into recipient-facing WhatsApp text; no conversational follow-up ("Make it more formal", "Don't mention time"). |
| **Messaging / WhatsApp** | WhatsApp Application / Web Launch | **Missing** | Execution currently routes to macOS `Messages` (iMessage) via AppleScript! Does not target WhatsApp Desktop (`whatsapp://`) or WhatsApp Web. |
| **Messaging / WhatsApp** | WhatsApp Approval Gate | **Missing** | Approval check in `orchestrator.py` only validates hash for `SEND_MAIL` and `DRAFT_MAIL`. WhatsApp actions have no cryptographic payload binding. |
| **Messaging / WhatsApp** | WhatsApp Delivery Verification | **Missing** | No verification or submission check for WhatsApp messages; no duplicate send protection. |
| **Browser Automation** | Playwright Web Actions | **Partially Implemented** | `backend/capabilities/browser_actions.py`: `open_url`, `click`, `type_text`, `scrape`. Requires Playwright browser binaries; fails if Playwright not installed. No default OS browser launching fallback. |
| **File Operations** | Read / Write / Search Files | **Implemented and Tested** | `backend/capabilities/device_actions.py`, `backend/tools/file_tool.py`: sandbox path verification (`_is_safe_path`). |
| **File Operations** | Move / Rename / Create Document | **Missing** | No `move_file`, `rename_file`, or `create_document` handlers in tool registry. |
| **Productivity** | Notes Automation | **Implemented and Tested** | `backend/capabilities/device_actions.py`: creates note in Apple Notes via osascript. |
| **Productivity** | Web Search | **Implemented and Tested** | `backend/integrations/search/web_search.py`: DuckDuckGo / Google search. |
| **Productivity** | Personal Tasks | **Implemented and Tested** | `backend/capabilities/device_actions.py`: stored in memory / SQLite. |
| **Productivity** | Calendar Management | **Partially Implemented** | `backend/capabilities/device_actions.py`: mock / stub calendar read and create. |
| **User Experience** | Memory & Trust Audit UI | **Implemented and Tested** | `apps/desktop/src/App.jsx`: structured event cards, 50+ event types, localized timestamps, redacted secrets. |

---

## 3. High-Priority Defect & Gap Analysis

### Defect 1: WhatsApp Routed to iMessage
- **Location:** `backend/capabilities/device_actions.py` lines 406–418.
- **Symptom:** When a user asks to "Send Rahul a WhatsApp message saying I'm late", the backend invokes `_send_message`, which executes:
  ```applescript
  tell application "Messages"
    set targetBuddy to buddy "Rahul" of service "iMessage"
    send "I'm late" to targetBuddy
  end tell
  ```
- **Consequence:** The instruction completely ignores WhatsApp, targets Apple Messages instead, and crashes if "Rahul" is not an iMessage buddy.

### Defect 2: Missing Payload Approval Binding for Messages
- **Location:** `backend/agent/orchestrator.py` lines 1754–1772.
- **Symptom:** Cryptographic SHA-256 payload hash verification is exclusively coded for `TaskCommand.SEND_MAIL` and `TaskCommand.DRAFT_MAIL`. `TaskCommand.SEND_MESSAGE` lacks payload-bound approval verification, enabling replay or modified payload execution without detection.

### Defect 3: No Multi-turn Refinement for Chat/Messages
- **Location:** `backend/agent/orchestrator.py` lines 759–815.
- **Symptom:** Refinement instructions such as "Make it more formal" or "Don't mention the time" are only handled when `pending["type"] == "email_draft"`. When `pending["type"] == "message"`, these turns are treated as unrelated or unhandled commands.

### Defect 4: Brittle Application Lifecycle Automation
- **Location:** `backend/capabilities/device_actions.py` lines 295–321.
- **Symptom:** `_open_app` executes `subprocess.run(["open", "-a", app_name], check=True)`. If the application name is not an exact match (e.g., "chrome" instead of "Google Chrome", "vscode" instead of "Visual Studio Code"), `CalledProcessError` is thrown. No running state is checked beforehand, and `_close_app` does not inspect unsaved work.

---

## 4. Remediation Plan Overview

1. **Goal-Driven Agent Engine:** Refactor `contracts.py` to support `StructuredGoal`, expand `TaskCommand` with first-class `SEND_WHATSAPP` / `DRAFT_WHATSAPP` and application management commands, and implement a unified `CapabilityRegistry`.
2. **Desktop Control:** Add verified application alias resolution, running process checks, window closing vs app quitting distinction, and unsaved work inspection.
3. **WhatsApp Automation:**
   - Dedicated `WhatsAppAutomation` provider with WhatsApp Desktop (`whatsapp://`) and WhatsApp Web support.
   - Contact resolution supporting names and phone numbers.
   - Human-like message composition from informal instructions.
   - Multi-turn refinement ("Make it more formal", "Don't mention time").
   - Cryptographic payload approval hashing (`WhatsAppMessage.compute_hash()`).
   - Strong outcome verification with mock support for unit tests.
4. **General Task Execution:** Implement `move_file`, `create_document`, and default browser URL navigation.
5. **Context & Tone:** Ensure emotional/tone directives guide generation safely without hallucination.

