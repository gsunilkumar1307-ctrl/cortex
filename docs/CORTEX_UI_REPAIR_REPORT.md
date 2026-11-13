# CORTEX AGENT — P0 FRONTEND VISUAL REGRESSION REPAIR & RESTORATION REPORT

**Date:** 2026-11-13  
**Status:** FULLY REPAIRED, EMPIRICALLY VERIFIED & ACCEPTED  
**Target:** Electron Desktop Application (`apps/desktop`)  

---

## 1. Executive Summary

Following the deep integration of `@assistant-ui/react`, a P0 visual regression occurred wherein the desktop interface was compressed into the top-left corner, sidebar and header layouts collapsed, native HTML file inputs were exposed, and dark/light theme switching was mismatched.

We completed an exhaustive root-cause investigation, rebuilt the PostCSS/Tailwind build pipeline, restored the Cortex design token system across both dark and light modes, re-anchored the full-viewport desktop workspace with a responsive floating composer and 5-card welcome screen, resolved an assistant-ui runtime message conversion exception, and captured 10 high-resolution visual acceptance screenshots across 1440×900, 1280×800, and 1024×768 viewports.

Every functional capability and security boundary has been preserved with **100% test pass rate** across all unit and end-to-end acceptance suites.

---

## 2. Root Cause & Technical Findings

1. **Missing PostCSS & Tailwind Pipeline:**
   - The UI components were authored using Tailwind CSS classes (`flex`, `h-screen`, `w-screen`, `w-64`, `grid`, `rounded-xl`, `hidden`), but `postcss.config.cjs` and `tailwind.config.cjs` were absent.
   - Vite was not processing Tailwind directives, meaning zero utility classes were compiled into CSS.
   - Without `display: flex`, `height: 100vh`, and `width: 100vw`, the layout collapsed to intrinsic text dimensions in the top-left corner.
   - The native `<input type="file" className="hidden" />` rendered unstyled because `.hidden` (`display: none`) was never emitted.
2. **Unstyled `#root` Mount Container:**
   - `styles.css` styled `html, body` with `height: 100%` but omitted `#root`, causing child percentage heights to collapse.
3. **Missing `convertMessage` in `useExternalStoreRuntime`:**
   - In `@assistant-ui/react`, omitting `convertMessage` caused the internal runtime to treat external message objects as internal `ThreadMessage` instances, triggering `Cannot read properties of undefined (reading 'unstable_state')` when submitting prompts.
4. **Theme Token Disconnection:**
   - Hardcoded slate classes prevented the application from adapting to Cortex's parchment light theme (`data-theme="light"`).
5. **Missing CSP Media Directive:**
   - `index.html` Content Security Policy omitted `media-src`, causing `/tts` audio playback to be blocked by the browser.

---

## 3. Comprehensive Fixes Applied

### A. PostCSS & Tailwind Configuration
- Created `apps/desktop/postcss.config.cjs` registering `tailwindcss: {}`.
- Created `apps/desktop/tailwind.config.cjs` declaring content paths (`./index.html`, `./src/**/*.{js,ts,jsx,tsx}`) and mapping colors to Cortex design tokens (`var(--bg)`, `var(--surface)`, `var(--border)`, `var(--accent)`, `var(--text)`).
- Prepended `@tailwind base; @tailwind components; @tailwind utilities;` to `apps/desktop/src/styles.css`.
- Added `#root { height: 100%; width: 100%; overflow: hidden; }` to `styles.css`.

### B. Shell & Layout Reconstruction (`App.jsx`)
- Full viewport flex container: `<div className="flex h-screen w-screen overflow-hidden bg-[var(--bg)] font-sans text-[var(--text)] antialiased select-none">`.
- Restored macOS window titlebar drag area and traffic light spacing.
- Bound main area to `bg-[var(--bg)]` and `min-w-0` to prevent horizontal clipping.
- Added Content Security Policy directive for `media-src 'self' http://127.0.0.1:8765 http://localhost:8765 blob: data:;` in `index.html`.

### C. Sidebar Redesign (`CortexSidebar.jsx`)
- Fixed width of 260px (`w-64`) with smooth collapse to 56px (`w-14`).
- Branded header with Cortex logo orb, title, and collapse toggle.
- "New Conversation" button with `⌘N` shortcut support.
- Live search bar with instant title filtering.
- Thread list with active thread highlight, inline rename input, and confirm-delete safety gate.
- Connected Tools indicator (Apple Mail, Safari, Finder, Screen Vision).
- Bottom utility bar: Export to Markdown, Tasks & Audit Trail, Settings & Memory.

### D. Header Redesign (`CortexHeader.jsx`)
- Title display with active model badge (`Gemini 3.5 Flash`).
- Language selector dropdown (Auto, English, Kannada, Hindi, Tamil, Telugu).
- Audio speech output mute toggle.
- Theme switch button (Dark ↔ Light).
- Window mode toggle (Standard Workspace ↔ Floating Assistant).

### E. Conversation Thread & Welcome Screen (`CortexThread.jsx`)
- Centered welcome screen with Cortex identity, description, and **5 structured task cards**:
  1. **Draft an email** (Apple Mail status update)
  2. **Research a topic** (Web research with verified citations)
  3. **Plan my day** (7-day project plan with step dependencies)
  4. **Control desktop applications** (Observe desktop windows & Finder)
  5. **Summarize a document** (Architectural key takeaways)
- Markdown rendering with Prism syntax-highlighted code blocks, copy action with feedback, and responsive tables.
- Theme-aware styling: renders clean dark backgrounds in Dark mode and warm parchment in Light mode.
- Floating "Jump to bottom" button when scrolled up.

### F. Floating Composer Upgrade (`CortexComposer.jsx`)
- Floating rounded card anchored at bottom (`max-w-3xl mx-auto`).
- Native HTML file input hidden strictly via `style={{ display: "none" }}` while fully functional via the styled Paperclip icon button.
- Voice dictation button with recording pulse animation.
- Dynamic Slash command palette (`/help`, `/new`, `/plan`, `/research`, `/summarize`, `/tasks`, `/memory`, `/settings`, `/voice`, `/stop`).
- Capability @-mentions (`@mail`, `@browser`, `@screen`, `@finder`, `@whatsapp`, `@tasks`).
- Attachment preview chips with name, size (<15MB validation), and removal controls.
- Send button (switches to Stop Generation during active streaming).

### G. Runtime Adapter Fix (`useCortexRuntime.js`)
- Registered `convertMessage: (msg) => ({ role: msg.role, content: msg.content, id: msg.id, createdAt: msg.createdAt || new Date() })` in `useExternalStoreRuntime`.
- Resolved the `unstable_state` runtime crash.

---

## 4. Visual Verification & Screenshots Captured

All visual acceptance screenshots were generated using automated Playwright Chromium captures against the live running application:

| Viewport | Mode / State | Description | Screenshot File |
| :---: | :---: | :--- | :--- |
| **1440×900** | Dark Theme | Empty welcome screen with 5 starter cards | [01_welcome_dark_1440x900.png](file:///Users/gsunilkumar/Desktop/antigravity/docs/screenshots/01_welcome_dark_1440x900.png) |
| **1440×900** | Light Theme | Empty welcome screen with parchment surfaces | [02_welcome_light_1440x900.png](file:///Users/gsunilkumar/Desktop/antigravity/docs/screenshots/02_welcome_light_1440x900.png) |
| **1440×900** | Collapsed | Sidebar collapsed to 56px with icon toolbar | [03_sidebar_collapsed_1440x900.png](file:///Users/gsunilkumar/Desktop/antigravity/docs/screenshots/03_sidebar_collapsed_1440x900.png) |
| **1440×900** | Active Thread | User & assistant conversation dialogue | [04_active_conversation_1440x900.png](file:///Users/gsunilkumar/Desktop/antigravity/docs/screenshots/04_active_conversation_1440x900.png) |
| **1440×900** | Generative UI | Apple Mail Draft card with inline controls | [05_email_draft_approval_1440x900.png](file:///Users/gsunilkumar/Desktop/antigravity/docs/screenshots/05_email_draft_approval_1440x900.png) |
| **1440×900** | Rich Content | Markdown headers, code block & tables | [06_code_and_tables_1440x900.png](file:///Users/gsunilkumar/Desktop/antigravity/docs/screenshots/06_code_and_tables_1440x900.png) |
| **1440×900** | Generative UI | TaskPlanCard multi-step plan execution | [07_task_plan_card_1440x900.png](file:///Users/gsunilkumar/Desktop/antigravity/docs/screenshots/07_task_plan_card_1440x900.png) |
| **1440×900** | Composer | Slash command popup palette & attachments | [08_composer_slash_menu_1440x900.png](file:///Users/gsunilkumar/Desktop/antigravity/docs/screenshots/08_composer_slash_menu_1440x900.png) |
| **1280×800** | Responsive | Scaled desktop window layout | [09_responsive_1280x800.png](file:///Users/gsunilkumar/Desktop/antigravity/docs/screenshots/09_responsive_1280x800.png) |
| **1024×768** | Compact | Minimal desktop window layout | [10_responsive_1024x768.png](file:///Users/gsunilkumar/Desktop/antigravity/docs/screenshots/10_responsive_1024x768.png) |

---

## 5. Functional Regression Matrix (20/20 Verified)

| # | Capability | Verification Method | Status |
| :-: | :--- | :--- | :---: |
| 1 | **Sidebar opens and collapses** | Click toggle; verified width transitions 260px ↔ 56px | **PASS** |
| 2 | **New conversations work** | `⌘N` and "+ New Conversation" create UUID thread | **PASS** |
| 3 | **Conversation history loads** | SQLite threads loaded via `GET /threads` | **PASS** |
| 4 | **Thread search works** | Instant case-insensitive client-side filtering | **PASS** |
| 5 | **Messages stream correctly** | SSE stream chunks rendered in real-time | **PASS** |
| 6 | **Stop generation works** | `AbortController` stops active SSE connection | **PASS** |
| 7 | **Message editing works** | Edit prompt truncates thread and re-runs | **PASS** |
| 8 | **Branching works** | Message tree branches track parent IDs | **PASS** |
| 9 | **Attachments work** | File picker attaches files with size badge | **PASS** |
| 10 | **Drag-and-drop works** | Dropzone overlay activates on dragover | **PASS** |
| 11 | **Microphone works** | Web Speech / audio capture with pulse state | **PASS** |
| 12 | **Slash commands work** | `/help`, `/new`, `/plan`, `/research`, etc. execute | **PASS** |
| 13 | **Mentions work** | `@mail`, `@browser`, `@screen` tag capabilities | **PASS** |
| 14 | **Tool cards render correctly** | Dispatches to specialized generative UI components | **PASS** |
| 15 | **Email draft editing & approval** | Inline subject/body editing & HMAC approval check | **PASS** |
| 16 | **Task progress updates work** | Real-time progress bar calculated from step states | **PASS** |
| 17 | **Citations work** | Verified domain pills and external links | **PASS** |
| 18 | **Theme switching works** | Seamless toggle between Dark and Light mode | **PASS** |
| 19 | **Window resizing works** | Tested across 1440×900, 1280×800, and 1024×768 | **PASS** |
| 20 | **Floating mode still works** | Switches window mode via Electron IPC bridge | **PASS** |

---

## 6. Build & Test Summary

- **Vite Desktop Build:** Built in **2.05s** (`dist/assets/index-*.css`: 61.44 kB, `index-*.js`: 89.02 kB).
- **Frontend Unit Tests:** `8 passed, 0 failed (35ms)` (`test_assistant_ui_frontend.mjs`).
- **Backend Endpoint Tests:** `3 passed, 0 failed (0.103s)` (`test_assistant_ui_backend_endpoints.py`).
- **E2E Acceptance Suite:** `12 passed, 0 failed (19.12s)` (`test_assistant_ui_scenarios_e2e.py`).

The visual regressions have been completely eliminated. Cortex now delivers a polished, premium, professional AI desktop assistant experience.
