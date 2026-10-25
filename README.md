# Cortex — Siri-Inspired Voice-First Personal AI Companion

[![Tests](https://img.shields.io/badge/Tests-210%20Passed-brightgreen)](tests)
[![Platform](https://img.shields.io/badge/Platform-macOS-blue)]()
[![Design](https://img.shields.io/badge/Aesthetic-Anthropic%20Claude%20Editorial-orange)]()
[![License](https://img.shields.io/badge/License-MIT-lightgrey)]()

**Cortex** is an autonomous, voice-first personal AI desktop companion for macOS. Inspired by the conversational simplicity and natural voice interaction of Apple Siri and wrapped in a warm, editorial visual design inspired by Anthropic Claude, Cortex runs seamlessly alongside your work to assist with system automation, email composition, memory retention, and everyday reasoning.

---

## ✨ Features

- 🎙️ **Voice-First Conversational Loop**: Instant voice interactions powered by real-time RMS Voice Activity Detection (VAD), auto-silence cutoff, and natural speech synthesis with instant barge-in/interruption.
- 🪟 **Floating Assistant (`Option + Space`)**: Summon Cortex anywhere on macOS with a universal shortcut. Switch seamlessly between compact floating pill mode and a full workspace.
- 🎨 **Claude-Inspired Editorial Aesthetic**: Warm parchment surfaces (`#f5f4ed`), rich serif headings, terracotta accents (`#c96442`), and a dynamic hearth breathing orb that indicates listening, thinking, and speaking states.
- 🔒 **Encrypted Semantic Memory**: Local SQLite storage hardened with AES-256 / PBKDF2 encryption. Includes full user privacy controls: view, inspect, and delete retained memories anytime.
- ⚡ **Direct Answers & Adaptive Tone**: Skips boilerplate text for factual queries while adapting conversational tone (concise under urgency, structured for technical questions, warm during casual interaction).
- 🛡️ **Cryptographic Human-in-the-Loop**: Sensitive operations (such as sending emails via Apple Mail) require explicit approval backed by SHA-256 state hashing.
- 🌐 **Offline or Cloud-Powered**: Runs completely offline in local mode with built-in heuristic reasoning, or online using Google Gemini multimodal AI.

---

## 🏛 Directory Architecture

```
cortex/
├── apps/
│   └── desktop/                  # Electron + React/Vite companion desktop app
│       ├── electron/             # Native macOS window management & IPC shortcuts
│       └── src/                  # React UI, Claude design tokens, Orb canvas
├── backend/                      # Unified Python backend service
│   ├── agent/                    # Autonomous orchestrator, policy & email reasoning
│   ├── api/                      # FastAPI HTTP & WebSocket endpoints
│   ├── capabilities/             # System automation (device, mail, vision, safety)
│   ├── core/                     # Domain contracts, direct answers, adaptive tone
│   ├── integrations/             # Apple Mail, Gmail, & Web Search adapters
│   ├── persistence/              # SQLite store with AES-256 / PBKDF2 encryption
│   └── voice/                    # Real-time VAD, STT, and speech synthesis pipelines
├── docs/                         # Architecture, Security, and API guides
├── scripts/                      # Startup and live verification scripts
└── tests/                        # 210 comprehensive unit & integration tests
```

---

## 🚀 Quick Start (For You & Friends)

### 1. Prerequisites
- **macOS** 12.0+ (Monterey, Ventura, Sonoma, Sequoia)
- **Node.js** 18+ & npm
- **Python** 3.9+

### 2. Clone the Repository
```bash
git clone https://github.com/gsunilkumar1307-ctrl/cortex.git
cd cortex
```

### 3. One-Command Setup
Install all Node.js and Python dependencies in one step:
```bash
npm run setup
```

### 4. Configure Environment (Optional)
Cortex works **100% offline** out of the box. To enable online Google Gemini multimodal reasoning, configure your API key:
```bash
cp .env.example .env
# Edit .env and paste your GEMINI_API_KEY
```

### 5. Launch Cortex
```bash
npm start
```
This automatically launches the Python brain server (`http://127.0.0.1:8765`) and opens the companion desktop window.

---

## ⌨️ Global Shortcuts

| Shortcut | Action |
| :--- | :--- |
| <kbd>Option</kbd> + <kbd>Space</kbd> | Toggle Floating Assistant on / off |
| <kbd>Cmd</kbd> + <kbd>K</kbd> | Open Command Palette & Quick Memory Search |
| <kbd>Esc</kbd> | Immediately stop voice speech / dismiss overlay |

---

## 🧪 Testing & Quality Assurance

Cortex is tested across 210 automated unit and integration tests:

```bash
# Run all 210 automated tests
npm test

# Run live Apple Mail end-to-end integration verification
npm run verify

# Build production desktop release bundle
npm run build
```

---

## 🔒 Security & Privacy

1. **Zero Secret Leakage**: No credentials, `.env` files, or local user databases are committed to version control.
2. **Encrypted at Rest**: All retained memory fragments and persistent profiles use AES-256 encryption.
3. **Approval Gates**: Sensitive device interactions and outbound messages require your explicit cryptographic confirmation before execution.

---

## 👤 Author

Developed by **G Sunil Kumar** ([@gsunilkumar1307-ctrl](https://github.com/gsunilkumar1307-ctrl))
