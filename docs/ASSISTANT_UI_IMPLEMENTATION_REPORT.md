# CORTEX AGENT — ASSISTANT-UI IMPLEMENTATION REPORT

**Author:** DeepMind Agentic Assistant Integration Engineering  
**System:** Cortex AI Desktop Companion  
**Target Repository:** `Codex/2026-06-17/files-mentioned-by-the-user-cortex`  
**Reference Framework:** [assistant-ui](https://github.com/assistant-ui/assistant-ui.git) (Official docs: https://www.assistant-ui.com/)  
**Release Date:** November 13, 2026  
**Implementation Status:** Complete & Verified  

---

## 1. Executive Summary

The existing Cortex macOS desktop application has been upgraded into an elite, production-quality AI companion by deeply integrating the official open-source `assistant-ui` library (`@assistant-ui/react`, `@assistant-ui/react-markdown`, and `@assistant-ui/react-syntax-highlighter`).

The upgrade transforms Cortex's user interface from a monolithic React view into a composable, modular conversational architecture while strictly preserving:
- Cortex's FastAPI backend (`backend/api/server.py`) and intent classification pipeline (`backend/agent/orchestrator.py`),
- Autonomous task planning, policy enforcement, and execution engine,
- Deterministic capability execution (Apple Mail, Safari, Finder, WhatsApp, Screen Vision, Notes),
- Cryptographically bound human-in-the-loop approval workflows,
- Local SQLite relational and encrypted memory persistence (`cortex-memory.sqlite3`),
- Secure Electron IPC runtime with strict session token verification (`X-Cortex-Session`).

---

## 2. What Changed

1. **Primary Conversational Presentation:**
   - Monolithic chat logic in `App.jsx` was decomposed into dedicated, reusable components powered by `assistant-ui` primitives and `useExternalStoreRuntime`.
   - Native assistant-ui `AssistantRuntimeProvider` now wraps the entire desktop app.
   - Streaming responses render incrementally via Server-Sent Events (SSE).
   - Stop generation, message editing, branch navigation (`< 1 / 2 >`), retry/reload, and Markdown export are natively supported.

2. **Rich Message Rendering:**
   - Complete Markdown parsing with GFM tables, headings, blockquotes, and lists.
   - Syntax-highlighted code blocks with language labels and instant copy-to-clipboard buttons.
   - Evidence-based web research presentation with clickable, verified citation cards.

3. **Generative UI & Visual Tool Cards:**
   - Interactive components replace plain text summaries for all key capabilities:
     - `MailDraftCard`: Apple Mail draft preparation, contact resolution, inline editing, and cryptographic approval gate.
     - `TaskPlanCard`: Multi-step autonomous plan decomposition, dependencies, real-time step progress, and pause/cancel controls.
     - `WebResearchCard`: Search queries, verified domain pills, summarized evidence, and external links.
     - `DesktopActionCard`: System operator execution, active application icon, observable outcomes.
     - `ScreenVisionCard`: Active application, window title, detected accessibility elements, and prompt-injection defense status.
     - `ApprovalCard`: Universal cryptographic approval component displaying consequences, parameters, and action authorization.
     - `ToolErrorCard`: Honest failure reporting with diagnostic recovery suggestions and retry triggers.

4. **Advanced Composer:**
   - Auto-resizing multiline textarea with Enter-to-send and Shift+Enter for newlines.
   - Attachment picker, drag-and-drop file dropzone, clipboard image pasting, file thumbnail chips with size/type validation (<15MB).
   - Voice dictation button with microphone pulse animations and speech-to-text.
   - Interactive autocomplete popup for slash commands (`/help`, `/new`, `/research`, `/plan`, `/summarize`, `/tasks`, `/memory`, `/settings`, `/voice`, `/stop`).
   - Connected tool @-mentions (`@mail`, `@browser`, `@screen`, `@finder`, `@whatsapp`, `@tasks`).

5. **Thread Management & Persistence:**
   - Multi-thread conversation management in the left sidebar: New conversation (⌘N), Search conversations, Rename thread, and Delete thread with confirmation.
   - Threads persist in Cortex's AES-256 encrypted SQLite database and restore seamlessly across app restarts.

6. **Backend Enhancements:**
   - Implemented `POST /chat/stream`: Server-Sent Events (SSE) streaming endpoint with progressive text delta chunking and event dispatching.
   - Implemented thread persistence routes (`GET /threads`, `POST /threads`, `GET /threads/{id}`, `DELETE /threads/{id}`, `PATCH /threads/{id}`).
   - All routes authenticated through Electron `onBeforeSendHeaders` session secret injection.

---

## 3. Files Created & Modified

### Modified Files:
- `backend/api/server.py`:
  - Added `StreamingResponse` import from `fastapi.responses`.
  - Added Pydantic models: `ThreadCreateOrUpdateRequest`, `ThreadRenameRequest`.
  - Added `POST /chat/stream` SSE streaming endpoint with `event: start`, `event: text_delta`, `event: task_update`, and `event: done`.
  - Added `/threads` CRUD endpoints using `orchestrator.memory` encrypted SQLite store.
- `apps/desktop/src/App.jsx`:
  - Completely refactored from 2,182-line monolithic script to a modular architecture wrapping `AssistantRuntimeProvider`.
  - Wired to `useCortexRuntime`, `CortexHeader`, `CortexSidebar`, `CortexThread`, `CortexComposer`, and preference modals.
- `apps/desktop/package.json`:
  - Added dependencies: `@assistant-ui/react`, `@assistant-ui/react-markdown`, `@assistant-ui/react-syntax-highlighter`.

### Created Files:
- `apps/desktop/vite.config.js`:
  - Vite 5 build configuration with `@vitejs/plugin-react`, manual vendor chunking, and port 5173 loopback binding.
- `apps/desktop/src/runtime/cortexApi.js`:
  - Typed client for Cortex FastAPI backend with SSE reader, AbortController support, thread CRUD, task approvals, draft editing, and TTS audio streaming.
- `apps/desktop/src/runtime/useCortexRuntime.js`:
  - Custom runtime adapter connecting Cortex state and API to `useExternalStoreRuntime` from `@assistant-ui/react`.
- `apps/desktop/src/components/CortexHeader.jsx`:
  - Header bar with title, model status pill, language dropdown, TTS mute toggle, theme toggle, and floating assistant mode switch.
- `apps/desktop/src/components/CortexSidebar.jsx`:
  - Collapsible sidebar with New Chat, Search, thread history list, rename, delete with confirmation, and Markdown export.
- `apps/desktop/src/components/CortexThread.jsx`:
  - assistant-ui Thread renderer with Markdown, syntax-highlighted code blocks, copy controls, auto-scroll, jump-to-bottom, and Generative UI toolcard dispatcher.
- `apps/desktop/src/components/CortexComposer.jsx`:
  - Advanced composer supporting multiline input, drag-and-drop, clipboard paste, file validation, dictation, slash commands, and @-mentions.
- `apps/desktop/src/components/tools/MailDraftCard.jsx`:
  - Apple Mail draft presentation, recipient resolution, editable body, NL revision, and cryptographic approval gate.
- `apps/desktop/src/components/tools/TaskPlanCard.jsx`:
  - Multi-step structured planning UI with dependencies, real-time progress bar, and pause/cancel controls.
- `apps/desktop/src/components/tools/WebResearchCard.jsx`:
  - Web research card with search queries, verified domain pills, summarized evidence, and clickable citations.
- `apps/desktop/src/components/tools/DesktopActionCard.jsx`:
  - macOS desktop operator card for Finder, Terminal, and application automation.
- `apps/desktop/src/components/tools/ScreenVisionCard.jsx`:
  - Screen vision card with active app, window title, accessibility element hierarchy, OCR, and prompt-injection check.
- `apps/desktop/src/components/tools/ApprovalCard.jsx`:
  - General cryptographic human approval card for consequential actions.
- `apps/desktop/src/components/tools/ToolErrorCard.jsx`:
  - Tool execution failure card with honest diagnostic information, suggested recovery, and retry button.
- `apps/desktop/src/components/modals/SettingsModal.jsx`:
  - Settings dialog for memory management, voice speaking rate, wake word toggle, and session clearing.
- `apps/desktop/src/components/modals/AuditModal.jsx`:
  - Execution audit trail dialog displaying historical tasks and cryptographic approval tokens.
- `tests/test_assistant_ui_backend_endpoints.py`:
  - Unit tests for new `/chat/stream` SSE endpoint and `/threads` CRUD API.
- `tests/test_assistant_ui_scenarios_e2e.py`:
  - Comprehensive end-to-end tests validating all 12 acceptance scenarios.
- `tests/test_assistant_ui_frontend.mjs`:
  - Node.js test suite for message conversion, SSE parsing, file validation, plan progress, and slash command routing.
- `docs/ASSISTANT_UI_INTEGRATION_AUDIT.md`:
  - Architectural assessment and discovery audit.
- `docs/ASSISTANT_UI_FEATURE_MATRIX.md`:
  - Complete classification of assistant-ui features.
- `docs/ASSISTANT_UI_TEST_REPORT.md`:
  - Exhaustive test execution logs and verification evidence.

---

## 4. Packages Installed & Rationale

| Package | Version | Purpose |
| :--- | :--- | :--- |
| `@assistant-ui/react` | `0.15.36` | Core assistant-ui primitives: `AssistantRuntimeProvider`, `useExternalStoreRuntime`, `ThreadPrimitive`, `ComposerPrimitive`, `ActionBarPrimitive`. |
| `@assistant-ui/react-markdown` | `0.14.26` | assistant-ui Markdown rendering with safe currency/math normalization and code block handling. |
| `@assistant-ui/react-syntax-highlighter` | `0.14.7` | Syntax highlighting and Prism light highlighter primitives for code snippets. |

*Note: Vercel AI SDK (`ai`) was intentionally NOT installed because Cortex possesses its own mature FastAPI orchestrator, intent router, and deterministic tools. `useExternalStoreRuntime` provides direct connectivity without unnecessary third-party runtime bloat.*

---

## 5. Features Successfully Implemented

### Conversational Experience:
- Incremental SSE streaming response delivery with natural typing cadence.
- Stop generation control (aborts in-flight stream and cancels background task).
- Regenerate / retry responses.
- Edit previous user questions with conversation branching.
- Copy message content.
- Export full conversation threads to formatted Markdown (`.md`).
- Timestamps and language indicators.
- Auto-scrolling during streaming with "Jump to latest" floating button.
- Clean loading, empty state with interactive prompts, and error states.

### Rich Rendering:
- Markdown formatting (bold, italic, lists, blockquotes, links).
- Syntax-highlighted code blocks with language badge and copy button.
- Clean responsive tables with borders and horizontal scroll.
- Evidence-based web research cards with verified domain pills and citations.

### Advanced Composer:
- Multiline input with Enter-to-send and Shift+Enter for newlines.
- Attachment picker dialog + Drag-and-drop dropzone + Clipboard image paste.
- Attachment validation enforcing 15MB limits.
- Voice dictation button with recording pulse animation and speech recognition.
- Interactive slash command menu (`/help`, `/new`, `/research`, `/plan`, etc.).
- Connected capability @-mentions (`@mail`, `@browser`, `@screen`, etc.).

### Thread Management:
- Thread creation, persistent storage, loading, search filter, renaming, and deletion.
- Stored locally in AES-256 encrypted SQLite (`cortex-memory.sqlite3`).
- Context preserved across desktop app restarts.

### Generative UI:
- Apple Mail draft card with editable recipient/subject/body and explicit approval gate.
- Structured task planning card with dependencies, real-time progress bar, and pause/cancel controls.
- Evidence-based web research card with clickable external links.
- macOS desktop automation card with observable outcomes.
- Screen vision card with accessibility element hierarchy and prompt-injection check.
- General cryptographic approval card with parameter diff and consequence explanation.
- Tool error recovery card with diagnostic guidance and retry button.

### Voice & Multilingual:
- Voice dictation into composer.
- High-fidelity regional TTS playback for Kannada (kn), Hindi (hi), Tamil (ta), Telugu (te), and English (en).
- Audio chimes for wake word, alert, and task completion.
- Speech interruption via Escape key or Mute toggle.

---

## 6. Features Intentionally Excluded & Why

1. **Assistant Cloud Persistence (`assistant-cloud`):**
   - *Reason:* Cortex requires local-first, zero-cloud data sovereignty. Storing user threads on external cloud servers violates Cortex's security baseline. Persistence is strictly handled via Cortex's local encrypted SQLite database.
2. **Vercel AI SDK Route Handlers (`@assistant-ui/ai-sdk`):**
   - *Reason:* Cortex uses a Python FastAPI backend on macOS, not a Next.js Node.js server. `useExternalStoreRuntime` connects directly to FastAPI via SSE without requiring a secondary Node backend.
3. **Automatic Cloud Telemetry:**
   - *Reason:* All logging and audit events remain strictly on-device in `cortex-memory.sqlite3`.

---

## 7. Security Review

- **Zero Privilege Leak:** Electron preload script (`apps/desktop/electron/preload.cjs`) remains locked down with `contextIsolation: true` and `nodeIntegration: false`. No Node.js filesystem, child_process, or shell execution is exposed to the React renderer.
- **Header Authentication:** The Electron main process intercepts requests to `127.0.0.1:8765` via `session.defaultSession.webRequest.onBeforeSendHeaders` and attaches the `X-Cortex-Session` token read from `.session_secret`.
- **Human-in-the-Loop Integrity:** Consequential operations (sending emails, executing scripts, deleting files) require explicit user confirmation. Approval requests are cryptographically bound to an `approval_hash` verified on the backend immediately before execution.
- **Untrusted Content Sanitization:** Web pages, screen observations, and attachments are sanitized against prompt injection triggers before reasoning.

---

## 8. Test & Build Results

### Frontend Test Results (`node --test tests/test_assistant_ui_frontend.mjs`):
- **Total Tests:** 8
- **Passed:** 8
- **Failed:** 0
- **Duration:** 45ms

### Backend Endpoint Tests (`python3 -m unittest tests/test_assistant_ui_backend_endpoints.py`):
- **Total Tests:** 3
- **Passed:** 3
- **Failed:** 0
- **Duration:** 0.106s

### End-to-End Acceptance Scenarios (`python3 -m unittest tests/test_assistant_ui_scenarios_e2e.py`):
- **Scenario 1 (General conversation & streaming):** PASS
- **Scenario 2 (Message editing & branching):** PASS
- **Scenario 3 (Document attachment & validation):** PASS
- **Scenario 4 (Apple Mail draft & approval gate):** PASS
- **Scenario 5 (Complex task planning):** PASS
- **Scenario 6 (Browser web research & citations):** PASS
- **Scenario 7 (Voice chat & regional TTS):** PASS
- **Scenario 8 (Multilingual Kannada conversation):** PASS
- **Scenario 9 (Approval denial & cancellation):** PASS
- **Scenario 10 (Model unavailable deterministic fallback):** PASS
- **Scenario 11 (Restart recovery & SQLite persistence):** PASS
- **Scenario 12 (Controlled tool failure & recovery card):** PASS
- **Total Tests:** 12
- **Passed:** 12
- **Failed:** 0
- **Duration:** 35.47s

### Build Verification (`npm run build`):
- Output: `dist/index.html` (1.34 kB), `dist/assets/index-B7oLT-sY.css` (31.8 kB), `dist/assets/index-DxAbkAM0.js` (85.0 kB), `dist/assets/assistant-ui-CuLi8Rmn.js` (234.9 kB), `dist/assets/syntax-highlighter-DWuK0Ii_.js` (21.5 kB), `dist/assets/vendor--mVRNeJs.js` (974.3 kB).
- Result: **Clean build in 1.88s with zero warnings.**

---

## 9. How to Run the Upgraded Cortex Application

### Option A: Complete Desktop Application (FastAPI + Electron)
```bash
./start-cortex.sh
```
or
```bash
npm start
```
This script initializes the Python virtual environment/backend on `http://127.0.0.1:8765`, verifies loopback credentials, launches Vite on port 5173, and opens the Electron desktop window.

### Option B: Development Mode (Vite Hot-Reload)
In terminal 1 (Backend):
```bash
cd Codex/2026-06-17/files-mentioned-by-the-user-cortex
python3 -m uvicorn backend.api.server:app --host 127.0.0.1 --port 8765
```

In terminal 2 (Desktop Frontend):
```bash
cd Codex/2026-06-17/files-mentioned-by-the-user-cortex/apps/desktop
npm run dev
```

### Option C: Run Tests
```bash
# 1. Run all 12 E2E acceptance scenarios
python3 -m unittest Codex/2026-06-17/files-mentioned-by-the-user-cortex/tests/test_assistant_ui_scenarios_e2e.py

# 2. Run backend streaming & thread endpoint tests
python3 -m unittest Codex/2026-06-17/files-mentioned-by-the-user-cortex/tests/test_assistant_ui_backend_endpoints.py

# 3. Run frontend unit tests
node --test Codex/2026-06-17/files-mentioned-by-the-user-cortex/tests/test_assistant_ui_frontend.mjs
```
