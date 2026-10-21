# Cortex System Architecture

## Overview
Cortex is an enterprise-grade autonomous AI desktop companion designed for cross-platform task orchestration, grounded contextual reasoning, system automation, and secure human-in-the-loop email management.

```
cortex-workspace/
├── apps/
│   └── desktop/                  # Electron + React/Vite UI companion
├── backend/                      # Unified Python core backend
│   ├── agent/                    # Planning, execution loop, policy & email reasoning
│   ├── api/                      # FastAPI HTTP/WebSocket server & voice UI endpoints
│   ├── capabilities/             # System automation (device, mail, browser, vision, safety)
│   ├── core/                     # Domain contracts, language detection, localization
│   ├── integrations/             # External service adapters (email providers, search)
│   ├── persistence/              # SQLite store with AES-256 / PBKDF2 encryption
│   ├── tools/                    # Modular tool registry & contract implementations
│   └── voice/                    # Local STT transcription & voice pipelines
├── scripts/                      # Startup, build, and verification harnesses
├── tests/                        # 177 unit & integration test suites
└── docs/                         # Architecture, Security, and Development documentation
```

---

## Core Components

### 1. `apps/desktop` (Desktop Companion)
- **Framework:** Electron with React 18, Vite, and Lucide React.
- **Role:** Floating, frameless, draggable companion widget offering real-time streaming feedback, live execution step visualization, voice waveform indicators, and interactive human-approval cards.
- **IPC & Networking:** Communicates with the backend server over local REST and WebSocket (`http://127.0.0.1:8765`).

### 2. `backend/agent` (Cognitive & Reasoning Engine)
- **`orchestrator.py`:** Central cognitive hub connecting Gemini / local models, intent decomposition, multi-turn conversation memory, and tool invocation.
- **`planner.py`:** Generates dependency-ordered, validated action plans (`Plan`, `PlanStep`).
- **`execution_engine.py`:** Closed-loop execution engine enforcing:
  $$\text{Execute Step} \longrightarrow \text{Observe} \longrightarrow \text{Verify} \longrightarrow \text{Auto-Recover / Replan}$$
- **`email_engine.py`:** Context-aware, grounded email composition engine. Enforces strict zero-hallucination protocols, relationship-based tone adaptation, recipient resolution, and mandatory cryptographic approval gates.
- **`recipient_resolver.py`:** Discovers and validates recipient email addresses from local mailboxes, address books, and structured user intent.
- **`policy.py`:** Evaluates risk levels (LOW, MEDIUM, HIGH, CRITICAL) and enforces safety constraints before dispatching actions.

### 3. `backend/capabilities` (System Automation Engine)
- **`device_actions.py`:** Safe local file operations, directory listings, path traversal guards (`_is_safe_path`), and native application launching.
- **`mail_actions.py`:** Mailbox interaction routines interfacing with connected email providers.
- **`browser_actions.py`:** Playwright-based headless and visual web navigation, DOM inspection, and authenticated web workflows.
- **`vision.py`:** Screen capture, OCR, and visual UI element localization.
- **`safety.py`:** Action boundary enforcement, system command blocklists, and sensitive file protection.

### 4. `backend/integrations` (External Adapters)
- **`email/apple_mail_provider.py`:** Native macOS AppleScript provider that creates genuine drafts and reads local mailbox accounts without requiring third-party cloud credentials.
- **`email/gmail_provider.py`:** Standard Google Gmail REST API client with OAuth2 token authentication.
- **`email/manager.py`:** Dynamic provider fallback chain (Apple Mail $\leftrightarrow$ Gmail $\leftrightarrow$ Session Mock).
- **`search/web_search.py`:** Web search integration via DuckDuckGo and Google Search API.

### 5. `backend/persistence` (Encrypted Memory)
- **`encrypted_store.py`:** Encrypted local key-value store using SQLite and SQLCipher / AES-256 with PBKDF2 key derivation for conversation history, learned contacts, and session state.

---

## Backward Compatibility Shims
To guarantee zero breakage across legacy scripts, import facades (`cortex_sdk`, `cortex_automation`, `cortex_memory`, `cortex_voice`, etc.) are maintained at the repository root, pointing directly to their corresponding `backend/` implementations.
