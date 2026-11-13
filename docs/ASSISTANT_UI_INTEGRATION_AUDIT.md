# ASSISTANT-UI INTEGRATION AUDIT & ARCHITECTURAL ASSESSMENT FOR CORTEX

**Document Version:** 1.0.0  
**Status:** Approved for Implementation  
**Target:** Cortex AI Desktop Companion (`apps/desktop` + `backend`)  
**Reference Open-Source Library:** [assistant-ui](https://github.com/assistant-ui/assistant-ui.git) (Official docs: https://www.assistant-ui.com/)  

---

## 1. Executive Summary

This audit assesses the integration of `assistant-ui` into the existing **Cortex Agent** codebase. Cortex is an autonomous, supervised macOS desktop companion featuring local-first execution, AppleScript/PyObjC system automations, bilingual/multilingual NLP (Kannada, Hindi, Tamil, Telugu, English), Apple Mail draft & send workflows, WhatsApp control, Finder inspection, screen vision, and encrypted SQLite persistence.

The goal is to elevate Cortex from an ad-hoc custom React chat view to an elite, production-quality desktop AI assistant leveraging `assistant-ui`'s primitives (Thread, Message, Composer, Toolkits, Generative UI, Branching, Attachments, and Audio) while preserving:
1. Cortex's existing FastAPI backend (`backend/api/server.py`),
2. `CortexOrchestrator` intent engine and autonomous planner (`backend/agent/`),
3. Deterministic tool execution and cryptographic approval security model (`backend/capabilities/`),
4. SQLite relational persistence and encrypted memory (`backend/persistence/`),
5. macOS Electron runtime with secure IPC and session-secret isolation (`apps/desktop/electron/`).

---

## 2. Existing Cortex Architecture

### 2.1 Component Topology

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Electron Desktop Shell                          │
│   (Vibrancy, Hidden-Inset Titlebar, Traffic Lights, Floating / Standard)│
│                                                                        │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │                 React 18.3.1 + Vite 5.4 Frontend               │   │
│   │     (assistant-ui Thread, Composer, Generative UI Cards)       │   │
│   └───────────────────────────────┬────────────────────────────────┘   │
│                                   │ Secure IPC / Loopback HTTP         │
│                                   │ X-Cortex-Session Auto-Injected     │
└───────────────────────────────────┼────────────────────────────────────┘
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       FastAPI Backend Server                           │
│                     (http://127.0.0.1:8765)                            │
│                                                                        │
│  • Session Auth Middleware (X-Cortex-Session validation)               │
│  • Endpoints: /chat, /chat/stream (SSE), /audio_chat, /tts,            │
│               /tasks, /tasks/{id}/approve, /tasks/{id}/cancel,         │
│               /tasks/{id}/edit, /memory, /session/clear, /health       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      Cortex Orchestrator Core                          │
│                                                                        │
│  • Intent Analysis & Classifier (Multilingual: kn, hi, ta, te, en)    │
│  • Autonomous Planner & Task Decomposition                            │
│  • Multi-turn State Machine (Email drafting, WhatsApp, Navigation)    │
│  • Deterministic Policy Guard & Approval Gate (Cryptographic Hash)     │
│  • Model Adapters: Gemini 3.5 Flash + Local Rule Engine Fallback       │
└──────────────────┬────────────────────────────────┬────────────────────┘
                   │                                │
                   ▼                                ▼
┌─────────────────────────────────────┐ ┌────────────────────────────────┐
│         Capability Layer            │ │      Persistence Layer         │
│  • Apple Mail (ScriptingBridge/AS)  │ │  • SQLite 3 WAL Database       │
│  • Gmail OAuth2 Provider            │ │    (cortex-memory.sqlite3)     │
│  • WhatsApp Desktop UI Automation   │ │  • Task & Step State Machine   │
│  • macOS Desktop Operator (Apps/AX) │ │  • Cryptographic Audit Trail   │
│  • Native Screen Vision (Swift AX)  │ │  • Encrypted Memory Store      │
│  • Web Search & Research (DDG)      │ │    (AES-256 Fernet)            │
└─────────────────────────────────────┘ └────────────────────────────────┘
```

### 2.2 Frontend Framework & Package Stack
- **Runtime:** Electron `^33.0.0` with `contextIsolation: true`, `nodeIntegration: false`, and secure preload bridge.
- **Frontend Framework:** React `^18.3.1`, React DOM `^18.3.1`.
- **Bundler:** Vite `^5.4.0` with `@vitejs/plugin-react`.
- **Styling:** TailwindCSS `^3.4.0` with custom macOS vibrancy utilities in `styles.css`.
- **Icons & Animation:** `lucide-react` `^0.468.0`, `framer-motion` `^11.0.0`.
- **Package Manager:** NPM with monorepo workspace (`apps/desktop`).

### 2.3 Backend Stack
- **Framework:** FastAPI `0.115+`, Uvicorn `0.32+`, Pydantic `2.9+`.
- **Python Version:** 3.9.6+ (macOS native).
- **Core Libraries:** `google-generativeai`, `speechrecognition`, `duckduckgo_search`/`ddgs`, `cryptography` (Fernet), `sqlite3`.

---

## 3. Existing Capabilities That Must Be Preserved

1. **Security & Session Isolation:**
   - Electron `onBeforeSendHeaders` attaches `X-Cortex-Session` token read from `.session_secret`.
   - FastAPI enforces authentication middleware on all state-altering routes.
   - Renderer never receives raw filesystem access, shell execution, or API secrets.

2. **Apple Mail Automation:**
   - Natural-language email drafting, contact disambiguation, editable recipient/subject/body.
   - Strictly enforced human-in-the-loop approval: no email is ever sent without explicit confirmation and cryptographic hash matching.

3. **Multilingual Processing:**
   - Native comprehension and response generation for English, Kannada (ಕನ್ನಡ), Hindi (हिन्दी), Tamil (தமிழ்), and Telugu (తెలుగు).
   - Multilingual voice transcription and regional TTS speech synthesis.

4. **Screen Vision & Desktop Control:**
   - Active window detection, accessibility tree parsing, UI element targeting.
   - App launching, window management, menu item execution, and focus switching.

5. **WhatsApp Desktop Automation:**
   - Contact resolution, message preparation, and visible-UI delivery with user confirmation.

6. **Web Search & Evidence-Based Research:**
   - Search query formulation, URL fetching, summarization, and citation attribution.

7. **Persistent Memory & Task Audit Trails:**
   - SQLite relational storage with optimistic concurrency control (`state_version`).
   - Categorized user memories (preferences, facts, system parameters) with encrypted storage.

---

## 4. assistant-ui Features Relevant to Cortex

| assistant-ui Feature | Relevance to Cortex | Integration Strategy |
| :--- | :--- | :--- |
| **`useExternalStoreRuntime`** | **Critical** | Connects Cortex's persistent turns and FastAPI backend to assistant-ui without introducing external servers or Vercel AI SDK lock-in. |
| **Composable `Thread` & `Message`** | **High** | Replaces monolithic custom chat lists with accessible, virtualizable, modular thread primitives. |
| **Streaming & Incremental Rendering** | **High** | Supports real-time text streaming, token animation, and auto-scroll behavior. |
| **Stop, Regenerate & Retry** | **High** | Enables aborting running requests, re-prompting, and recovering from model failures. |
| **Message Branching & Editing** | **High** | Provides alternate message exploration and user turn editing with `BranchPicker`. |
| **Advanced Composer** | **High** | Rich multiline textarea, attachment dropzone/picker, clipboard paste, file previews, and keyboard controls. |
| **Slash Commands & @-Mentions** | **High** | Quick access to Cortex capabilities (`/help`, `/research`, `/plan`, `/tasks`, `/voice`, etc.). |
| **Generative UI & Toolkits** | **Critical** | Custom interactive tool cards: Task Plan, Apple Mail Draft, Web Search, Screen Intelligence, Desktop Automation, and Approval Modals. |
| **Audio & Voice Integration** | **High** | Bridges microphone dictation, voice-to-text, and TTS read-aloud with playback controls. |
| **Markdown, Code & Syntax Highlighting** | **High** | Rich formatting, code block copy, tables, and structured data views via `@assistant-ui/react-markdown`. |

---

## 5. Features Already Implemented vs Missing / Partially Implemented

| Feature | Cortex Baseline Status | Target Upgrade with assistant-ui |
| :--- | :--- | :--- |
| **Message Rendering** | Custom basic markdown via `react-markdown` | `@assistant-ui/react-markdown` with syntax highlighting, tables, math, and copy controls |
| **Streaming Response** | Single-shot JSON payload over `/chat` | Incremental SSE streaming via `/chat/stream` with real-time UI chunking |
| **Message Branching** | Not implemented (linear turns only) | Native assistant-ui branching and branch navigation |
| **Message Editing** | Not implemented | Edit previous user turns, trigger re-evaluation |
| **Composer Attachments** | Not implemented | Drag-and-drop, clipboard paste, file previews, and validation |
| **Slash Commands** | Palette modal only (⌘K) | Inline composer autocomplete menu (`/help`, `/research`, `/plan`, etc.) |
| **Tool Execution Cards** | Custom card implementations in `App.jsx` | Formal assistant-ui Generative UI / Toolkit cards with standardized lifecycle |
| **Human Approval UI** | Inline buttons in `ResponseCard` | Cryptographically bound approval component with parameter diff and audit status |
| **Thread History Management** | Single active session + Clear History | Multi-thread management (New, Search, Rename, Delete, Switch, Export to Markdown) |
| **Voice Dictation** | Audio chunk recording via Web Audio | Native composer dictation button integrated with Cortex transcription |
| **Read Aloud / TTS** | Custom audio element + Web Speech | Assistant message speech controls with regional TTS playback and interruption |

---

## 6. Proposed Integration Architecture

### 6.1 Package Selection
- `@assistant-ui/react` (`^0.15.36`): Core primitives, Thread, Composer, BranchPicker, `useExternalStoreRuntime`, `defineToolkit`.
- `@assistant-ui/react-markdown` (`^0.14.26`): Markdown, code blocks, syntax highlighting, table rendering.
- `lucide-react`: Cohesive icon set (already present).
- `framer-motion`: Smooth transitions and state changes (already present).

### 6.2 Frontend Architecture (`apps/desktop/src/`)
```
apps/desktop/src/
├── App.jsx                     # Top-level shell (sidebar, window modes, theme, modals)
├── components/
│   ├── CortexThread.jsx        # assistant-ui Thread with custom AssistantUI components
│   ├── CortexComposer.jsx      # Advanced composer (attachments, dictation, slash commands)
│   ├── CortexSidebar.jsx       # Thread management, search, persistent history, actions
│   ├── CortexHeader.jsx        # App header, model status, language badge, window mode toggle
│   ├── tools/                  # Generative UI Toolcards
│   │   ├── TaskPlanCard.jsx    # Structured plan, steps, progress, pause/cancel
│   │   ├── MailDraftCard.jsx   # Apple Mail draft preview, editor, approval gate
│   │   ├── WebResearchCard.jsx # Search results, citations, verified external links
│   │   ├── DesktopActionCard.jsx # macOS automation execution and results
│   │   ├── ScreenVisionCard.jsx# Screen intelligence, active window, OCR
│   │   ├── ApprovalCard.jsx    # Cryptographic action approval / denial
│   │   └── ToolErrorCard.jsx   # Error details, recovery options, retry
│   ├── modals/
│   │   ├── SettingsModal.jsx   # Cortex settings & memory controls
│   │   ├── AuditModal.jsx      # Audit trail & activity logs
│   │   └── ConfirmModal.jsx    # Deletion / destructive action confirmation
├── runtime/
│   ├── useCortexRuntime.js     # Custom runtime adapter wrapping useExternalStoreRuntime
│   ├── cortexApi.js            # Typed client for Cortex FastAPI backend (HTTP + SSE stream)
│   └── attachments.js          # File validation, size limits, and preview generators
└── styles.css                  # Cortex design system & assistant-ui theme variables
```

### 6.3 Backend Streaming Enhancement (`backend/api/server.py`)
To fulfill Part 3.A (Streaming assistant responses, incremental rendering, and cancellation), we augment `backend/api/server.py` with:
- `POST /chat/stream`: An SSE (`text/event-stream`) streaming endpoint using FastAPI's `StreamingResponse`.
- Streaming lifecycle:
  1. Emit `start` event with language and intent metadata.
  2. If model streaming is available, stream text deltas (`chunk`).
  3. Emit `tool_call` when tools or capabilities are invoked.
  4. Emit `task_update` with audit events and approval tokens.
  5. Emit `done` with final task state.
- Graceful cancellation: When the client disconnects or aborts, generation is cleanly stopped.
- Full backwards compatibility: The existing `POST /chat` endpoint is retained untouched for tests and deterministic operations.

---

## 7. Dependency Compatibility & Risks

1. **React 18 Compatibility:**
   - Both Cortex and `@assistant-ui/react` support React 18.3.1.
2. **Vite Bundling:**
   - Vite 5 builds ES modules seamlessly. `@assistant-ui/react` ships ESM bundles compatible with modern bundlers.
3. **Electron Context Isolation:**
   - Preload script maintains zero Node.js leak to renderer.
   - IPC channels (`showHud`, `setWindowMode`, `getWindowMode`) remain unaffected.
4. **Tailwind CSS & assistant-ui Styles:**
   - assistant-ui uses standard Tailwind utility classes and CSS variables. Cortex's `styles.css` will define a sleek, minimal, premium dark/light theme.

---

## 8. Security Implications & Guardrails

1. **Loopback Secret Verification:** All requests between the React frontend and FastAPI backend must include `X-Cortex-Session`.
2. **Untrusted Content Sanitization:** Markdown and tool outputs are rendered securely with safe HTML/DOM sanitization to prevent XSS.
3. **Strict Human-in-the-Loop Approvals:** Consequential tools (email sending, file modifications, system operations) generate a server-side cryptographic `approval_hash`. The frontend can only present the decision to the user; approval validation occurs on the backend immediately before execution.
4. **No Privilege Escalation:** Electron preload remains locked down without exposing `fs`, `child_process`, or shell APIs to renderer scripts.
5. **Prompt Injection Defense:** Screen observations, web page contents, and file attachments are marked as untrusted input and sanitized through regex and policy filters before LLM consumption.

---

## 9. Testing & Verification Strategy

1. **Preserve Baseline Tests:** All existing unittest discovery tests must continue to run and pass.
2. **Frontend Component Tests:** Verify that `CortexThread`, `CortexComposer`, and toolcards render correctly and handle edge cases (empty states, loading, errors).
3. **Streaming & API Tests:** Test `POST /chat/stream`, SSE chunk parsing, stop generation, retry, and cancellation.
4. **End-to-End Scenarios:** Validate all 12 scenarios from Part 11:
   - General conversation & streaming.
   - Message editing and branching.
   - Document attachments and validation.
   - Apple Mail draft preparation, natural language editing, and approval confirmation.
   - Complex task planning and tracking.
   - Browser web research with verified source citations.
   - Voice dictation and regional TTS read-aloud.
   - Kannada and multilingual conversation.
   - Approval denial handling.
   - Model unavailable fallback.
   - Session recovery across restarts.
   - Controlled tool failure and error recovery card.

---

## 10. Conclusion & Next Steps

The integration of `assistant-ui` provides Cortex with a world-class conversational experience while honoring its architectural identity. With this audit completed, we immediately proceed to:
1. Installing the required assistant-ui frontend packages in `apps/desktop`.
2. Implementing the typed streaming backend endpoint `POST /chat/stream`.
3. Constructing the custom `useCortexRuntime` adapter.
4. Implementing the Generative UI toolcards and advanced composer.
5. Building the premium Cortex desktop interface with thread persistence.
6. Running complete test verification and producing the required reports.
