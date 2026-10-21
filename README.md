# Cortex — Autonomous AI Desktop Companion

[![Tests](https://img.shields.io/badge/Tests-177%20Passed-brightgreen)](tests)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Windows%20%7C%20Linux-blue)]()
[![Architecture](https://img.shields.io/badge/Architecture-Clean%20Monorepo-purple)](docs/ARCHITECTURE.md)
[![License](https://img.shields.io/badge/License-Proprietary-lightgrey)]()

**Cortex** is a production-grade autonomous AI desktop companion designed to operate seamlessly across applications, system tools, local mailboxes, and web interfaces. It combines multimodal reasoning (Google Gemini & local offline engines), closed-loop verification, native OS device automation, and cryptographic human-in-the-loop approvals.

---

## 🏛 Directory Architecture

The repository is organized following high-standard monorepo conventions:

```
cortex-workspace/
├── apps/
│   └── desktop/                  # Electron + React/Vite companion widget
├── backend/                      # Unified Python backend
│   ├── agent/                    # Planning, execution loop, policy & email reasoning
│   ├── api/                      # FastAPI HTTP & WebSocket endpoints
│   ├── capabilities/             # System automation (device, mail, browser, vision, safety)
│   ├── core/                     # Domain contracts, language detection, localization
│   ├── integrations/             # Service adapters (Apple Mail, Gmail, Web Search)
│   ├── persistence/              # SQLite store with AES-256 / PBKDF2 encryption
│   ├── tools/                    # Modular tool registry & contract implementations
│   └── voice/                    # Local STT transcription & voice pipelines
├── docs/                         # System Architecture, Security, & Developer guides
├── scripts/                      # Startup, verification, and operations scripts
└── tests/                        # Comprehensive unit & integration test suites
```

---

## ⚡ Quick Start

### One-Command Startup
To start both the Python backend brain and the Electron desktop companion:
```bash
npm start
# OR directly
./start-cortex.sh
```

### Key URLs
| Service | Endpoint | Description |
| :--- | :--- | :--- |
| **Backend API** | `http://127.0.0.1:8765` | REST & WebSocket orchestration server |
| **Health Check** | `http://127.0.0.1:8765/health` | Health & provider diagnostic status |
| **Voice / Web UI** | `http://127.0.0.1:8765/` | Direct browser-based companion UI |
| **Vite Dev Server** | `http://127.0.0.1:5173` | React frontend development server |

---

## 🧪 Testing & Verification

Cortex includes a comprehensive 177-test suite covering agent planning, multi-turn editing, security hash validation, Apple Mail / Gmail providers, closed-loop execution, and path traversal guards.

```bash
# Run all 177 automated tests
npm test

# Run live end-to-end email agent verification
npm run verify

# Build production desktop bundle
npm run build
```

---

## 🔒 Security & Safe Execution
Cortex enforces defense-in-depth safety:
1. **Mandatory Human-in-the-Loop:** Irreversible actions (sending emails, modifying critical files) require explicit user approval.
2. **Cryptographic Invalidation:** Approval tokens are bound to SHA-256 payloads. Any multi-turn edit invalidates prior authorization.
3. **Prompt Injection Filtering:** Untrusted email and web contents are scrubbed before reaching model context.
4. **Sandboxed Device Actions:** Path traversal guards prevent unauthorized access to sensitive system directories.

For complete details, see [docs/SECURITY.md](docs/SECURITY.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
