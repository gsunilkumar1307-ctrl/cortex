# Cortex Always-Available Desktop Companion Architecture & Audit

**Date**: 2026-11-13  
**Status**: Completed Pre-Implementation Audit  
**Target Platform**: macOS (Apple Silicon / Intel)  
**Reference Architecture**: Inspired by native macOS desktop assistants & *Google Assistant Unofficial Desktop Client* patterns (excluding obsolete SDKs/dependencies).

---

## Executive Summary

The objective of P0.2 is to upgrade the existing Cortex Agent into an **always-accessible AI desktop companion for macOS**. Users will be able to press a global keyboard shortcut (`Command + Shift + A` by default) anywhere in macOS, instantly summon a compact, floating Cortex assistant, speak or type naturally, observe real-time audio visualization, execute autonomous or guided desktop workflows, and minimize or dismiss Cortex without interrupting background tasks or losing conversational context.

This audit inspects the current codebase across 17 required architectural vectors, maps existing capabilities against requirements, identifies critical architectural gaps, defines security boundaries, and outlines the step-by-step implementation plan.

---

## 1. Codebase Discovery & Existing Architecture Analysis

### 1. Electron Main Process (`apps/desktop/electron/main.js`)
- **Current State**: Uses ES modules. Creates two windows: `mainWin` (standard workspace / floating toggle) and `hudWin` (transparent task execution overlay). Injects `X-Cortex-Session` header via `session.defaultSession.webRequest.onBeforeSendHeaders` to restrict API access to `127.0.0.1:8765`.
- **Existing Shortcuts**: Registers `CommandOrControl+K` and `Alt+Space`.
- **Gaps**:
  - Missing the required P0 default macOS shortcut: `Command + Shift + A`.
  - No dynamic shortcut registration / customization IPC or collision detection.
  - No System Tray / Menu Bar implementation.
  - Window closes on red traffic light rather than hiding to background tray.
  - Multi-monitor awareness missing (always targets `screen.getPrimaryDisplay()`).

### 2. Electron Preload (`apps/desktop/electron/preload.cjs`)
- **Current State**: Exposes minimal `window.cortexAPI` with `showHud`, `hideHud`, `onWindowModeChanged`, `getWindowMode`, `setWindowMode`.
- **Gaps**: Missing methods for shortcut customization, companion settings, tray state synchronization, audio device querying, and launch at login.

### 3. IPC Communication
- **Current State**: Limited one-way events (`hud-show`, `hud-hide`, `set-window-mode`) and one handle (`get-window-mode`).
- **Required**: Typed, validated IPC handlers for:
  - `get-companion-settings` / `update-companion-settings`
  - `register-global-shortcut` / `get-global-shortcut`
  - `set-tray-status`
  - `toggle-window-visibility`
  - `set-launch-at-login`

### 4. Existing BrowserWindow Configuration
- **Current State**: `width: 1120, height: 760, minWidth: 400, minHeight: 520, transparent: true, vibrancy: "under-window", visualEffectState: "active", titleBarStyle: "hiddenInset", trafficLightPosition: { x: 16, y: 16 }`.
- **Assessment**: Well-configured for macOS native vibrancy and dark/light system adaptation.

### 5. Existing Floating Mode Implementation
- **Current State**: `set-window-mode` toggles between `floating` (430x720 pinned top-right) and `standard` (1120x760 centered).
- **Gaps**: Does not remember user repositioning/resizing; does not detect cursor's active display on multi-monitor setups; lacks escape-to-hide and close-on-blur event hooks.

### 6. Existing Assistant-UI Integration
- **Current State**: Fully integrated with `@assistant-ui/react` (`AssistantRuntimeProvider`) in `apps/desktop/src/App.jsx`.
- **Runtime**: Custom runtime (`apps/desktop/src/runtime/useCortexRuntime.js`) communicates with FastAPI SSE endpoint (`/chat/stream`) and REST endpoints (`/threads`).
- **Preservation Directive**: All floating assistant interactions **must** use this exact runtime. No secondary or divergent conversational runtime.

### 7. React Component Architecture
- **Current Components**:
  - `App.jsx`: State controller and layout switch (standard vs floating).
  - `CortexSidebar.jsx`: Thread navigation, settings trigger, audit trigger (hidden in floating mode).
  - `CortexHeader.jsx`: Header bar with language, audio mute, theme, and floating toggle.
  - `CortexThread.jsx`: Message history, markdown streaming, generative UI tool cards (`ApprovalCard`, `MailDraftCard`, etc.).
  - `CortexComposer.jsx`: Prompt input, slash command menu, @-mentions, audio dictation button.
  - Modals: `SettingsModal.jsx`, `AuditModal.jsx`.

### 8. FastAPI Backend (`backend/api/server.py`)
- **Current State**: Runs on `http://127.0.0.1:8765`. Provides `/chat`, `/chat/stream`, `/threads`, `/audio_chat`, `/tts`, `/approve`, `/deny`, `/cancel`, `/draft/edit`.
- **Assessment**: Robust, supports dual streaming and task status events, protected by session secret token middleware.

### 9. Cortex Orchestrator (`backend/agent/orchestrator.py`)
- **Current State**: Central brain with Gemini integration, fallback offline routing, memory management, and action execution engines (Mail, Safari, Finder, WhatsApp, Screen Intelligence).
- **Assessment**: Completely intact and handles multi-turn conversation and task state across requests.

### 10. Existing Voice Input & TTS
- **Current State**:
  - Voice STT: Backend `/audio_chat` transcribes audio via `VoiceTranscriber` (Gemini Multimodal STT first, Google SpeechRecognition fallback).
  - Text-to-Speech: Backend `/tts` produces native audio chunks for English, Kannada, Hindi, Tamil, Telugu with in-memory caching.
  - Renderer speech: `speakText` plays audio stream with Web Speech Synthesis fallback.
- **Gaps**: Renderer dictation in `CortexComposer` currently uses basic browser `SpeechRecognition` without true audio-reactive visualization, audio device selection, or interruption controls.

### 11. Microphone Permissions
- **Current State**: Requested in Electron main process (`systemPreferences.askForMediaAccess("microphone")`) and renderer `getUserMedia`.
- **Gaps**: No visual error state or fallback guidance if macOS privacy settings block the microphone.

### 12. Audio Processing
- **Current State**: Backend uses RMS energy thresholding (`is_audio_silent`) to avoid processing silence.
- **Gaps**: Renderer lacks a Web Audio `AnalyserNode` to drive real-time audio waveforms / level meters.

### 13. Existing Keyboard Shortcuts
- **Current State**: `CommandOrControl+K` (palette), `Alt+Space` (toggle). In renderer: `Cmd+N` (new thread), `Cmd+,` (settings), `Escape` (cancel/stop).
- **Gaps**: Lacks the required `Command + Shift + A` global shortcut and in-app shortcut configuration.

### 14. Application Lifecycle
- **Current State**: `app.on("window-all-closed")` exits on non-macOS. On macOS, closing the window leaves the app running without a UI or tray.
- **Gaps**: Closing window should hide to tray when configured; tray should remain active; explicit Quit action should clean up resources.

### 15. System Tray Implementation
- **Current State**: Completely missing.
- **Gaps**: Requires Electron `Tray` instance with status icons (idle, listening, processing, speaking, error), native macOS dark/light mode icon templates, and full context menu.

### 16. Settings and Persistence
- **Current State**: Persistent data stored in SQLite (`cortex-memory.sqlite3`). UI preferences stored in React state.
- **Gaps**: Need persistent desktop settings store for global shortcut, floating behavior, audio devices, wake-word toggle, and launch-at-login.

### 17. Security Boundaries
- **Current State**: Context isolation enabled, node integration disabled, secure preload, session token authentication on API requests.
- **Requirement**: Maintain zero leakage of privileged Electron APIs; all renderer IPC calls strictly validated.

---

## 2. Capabilities Matrix

| Feature | Requested in Prompt | Current Status | Action Required |
|---|---|---|---|
| Global Shortcut `Cmd+Shift+A` | P0 | Not Implemented | Implement in main.js, register safely, handle conflicts |
| Customizable Global Shortcut | P1 | Not Implemented | Add settings UI + IPC to change and persist shortcut |
| Floating Assistant Window | P0 | Partially Implemented | Polish bounds, add always-on-top toggle, close-on-blur, multi-monitor |
| Remember Position & Size | P1 | Not Implemented | Store bounds in config file upon move/resize |
| macOS System Tray / Menu Bar | P0 | Not Implemented | Implement `Tray` with status icons and context menu |
| Menu Bar Status Indicators | P0 | Not Implemented | Ready, Listening, Processing, Speaking, Error states |
| Shared Conversational Runtime | P0 | Implemented & Verified | Maintain existing `assistant-ui` runtime for both views |
| Real-time Audio Visualization | P0 | Not Implemented | Implement Web Audio API AnalyserNode reactive visualizer |
| Audio Device Configuration | P1 | Not Implemented | Enumerate devices, mic/speaker selector, input level test |
| Stop/Interrupt Voice Playback | P0 | Partially Implemented | Provide explicit stop button & instant shortcut interrupt |
| Launch at Login | P1 | Not Implemented | Add `app.setLoginItemSettings` IPC and settings toggle |
| On-Device Wake Word ("Hey Cortex") | P2 | Design / Optional | Research privacy-first local engine, design modular integration |

---

## 3. Architecture & Implementation Plan

```mermaid
flowchart TD
    subgraph macOS Environment
        GS[Global Shortcut: Cmd+Shift+A]
        Tray[macOS Menu Bar Tray Icon]
        Mic[System Microphone]
    end

    subgraph Electron Main Process
        MainProc[main.js]
        TrayMgr[Tray Manager & Status State]
        ShortcutMgr[Global Shortcut Manager]
        SettingsStore[Persistent Desktop Config]
    end

    subgraph Electron Renderer (assistant-ui)
        App[App.jsx]
        FloatingView[Floating Assistant Mode]
        StandardView[Standard Workspace View]
        AudioViz[Web Audio Analyser Visualizer]
        DeviceMgr[Audio Device Controller]
    end

    subgraph FastAPI Backend :8765
        Server[server.py]
        Orchestrator[CortexOrchestrator]
        VoiceSTT[/audio_chat STT]
        VoiceTTS[/tts Multilingual MP3]
    end

    GS -->|Trigger| ShortcutMgr
    Tray -->|Menu Action| MainProc
    ShortcutMgr -->|Focus / Toggle| MainProc
    MainProc -->|IPC: window-mode, settings, tray| App
    App --> FloatingView
    App --> StandardView
    Mic -->|MediaStream| AudioViz
    App -->|Audio WAV / SSE stream| Server
    Server --> Orchestrator
    Server --> VoiceSTT
    Server --> VoiceTTS
```

---

## 4. Risk Mitigation & Privacy Controls

1. **Audio Privacy**: No continuous cloud streaming. Microphone recording only triggers on explicit push-to-talk, UI voice button, or locally-verified wake word.
2. **Resource Management**: Web Audio contexts and MediaStreams must be completely paused/closed when idle or window hidden to ensure 0% idle CPU and zero audio device locking.
3. **Task Continuity**: Hiding or minimizing the assistant window will never terminate running background orchestrator tasks.
4. **Security Isolation**: Preload API will only expose strictly validated channels; invalid accelerators or payloads will be rejected.
