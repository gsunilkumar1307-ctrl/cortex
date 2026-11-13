# CORTEX AGENT — KNOWN LIMITATIONS & SYSTEM BOUNDARIES

**Date:** November 9, 2026  
**Status:** Code Freeze / Production Ready  
**Architecture:** Electron + React (Desktop) + FastAPI (Backend) + Google Gemini (`gemini-3.5-flash`) + Native macOS Accessibility/AppleScript

---

## 1. Executive Summary

Cortex is designed as a grounded, safety-first macOS assistant. In accordance with strict engineering standards, Cortex never invents facts, never fabricates UI elements, and never bypasses human authorization. This document provides an honest accounting of the actual runtime boundaries and external dependencies.

---

## 2. Model & Cloud API Limits

### 2.1 Google Gemini Quota & Rate Limits
- **Configured Model:** `gemini-3.5-flash` via the official Google Generative AI Python SDK.
- **Quota Behavior:** Google AI Studio free-tier quotas enforce daily request caps (20 requests/day per project/model).
- **Circuit Breaker:** When HTTP 429 quota exhaustion occurs, Cortex activates an automatic 3-minute circuit breaker to prevent cascading timeouts.
- **Fallback Behavior:** During quota cooldowns, conversational requests automatically utilize local deterministic reasoning, offline knowledge bases, and live web research (DuckDuckGo Search) without silently swapping model providers.

### 2.2 Model Availability Disclosure
- Cortex explicitly discloses when the model is in cooldown rather than pretending to generate AI responses.
- General knowledge inquiries during cooldown provide grounded web search summaries with cited source links.

---

## 3. Email & Messaging Boundaries

### 3.1 Apple Mail
- **Status:** **LIVE & FULLY AUTHENTICATED** on macOS.
- **Runtime Mechanism:** Direct AppleScript Events to the native macOS Mail application (`/System/Applications/Mail.app`).
- **Account Binding:** Uses the active configured macOS Mail accounts (`gsunilkumar1307@gmail.com`).
- **Safety Gate:** Messages are strictly composed into the Mail drafts mailbox. No message is ever dispatched without explicit human authorization.
- **AppleScript Latency:** High load on Mail may incur 2–4s AppleScript execution latency. A 10-second safety timeout protects against process hangs.

### 3.2 Gmail REST Provider
- **Status:** **SANDBOX-MODE ONLY (unless OAuth token provided)**.
- **Requirement:** Live dispatch requires a valid `GMAIL_ACCESS_TOKEN` in the environment.
- **Sandbox Guarantees:** When tokens are not configured, Gmail commands execute within an in-memory transactional sandbox that models draft creation, in-place revision, and replay attack prevention.
- **Verification Rule:** Sandbox tests are never reported as live Gmail API success.

---

## 4. macOS Native Automation & Permissions

### 4.1 Accessibility (`AXUIElement`)
- **Permission Requirement:** *System Settings > Privacy & Security > Accessibility*.
- **Integrity Rule:** Cortex strictly filters out invalid, unhelpful, or negative nodes (`[Unknown]`, `-1`, empty labels). If an application exposes an empty accessibility tree, Cortex refuses to invent elements and reports that only valid nodes or OCR fallback text were observed.

### 4.2 Screen Recording (`CGWindowListCopyWindowInfo` / ScreenCaptureKit)
- **Permission Requirement:** *System Settings > Privacy & Security > Screen Recording*.
- **Functionality:** Required for Apple Vision OCR text recognition and multi-window enumeration.
- **Limitation:** If screen recording permission is revoked, accessibility inspection continues to function, but OCR visual perception falls back gracefully with an explicit limitation notice.

### 4.3 Application Lifecycle & Safety
- **No Force-Quits:** Cortex issues graceful `close` requests. It never executes `kill -9` or force-quits applications without explicit user command.
- **Unsaved Documents:** If an application reports unsaved document state, Cortex halts and notifies the user rather than discarding unsaved work.

---

## 5. Filesystem & Terminal Boundaries

### 5.1 Finder Navigation
- **Scope:** Read-only inspection of user directories (e.g., `~/Downloads`, `~/Documents`, `~/Desktop`).
- **Safety Guarantee:** Cortex strictly forbids destructive deletion or modification during directory inspection workflows.
- **Path Traversal Protection:** Directory traversal attacks (`../../`) and access outside user-permitted boundaries are blocked with `AccessBlocked` exceptions.

### 5.2 Shell Execution
- Arbitrary shell execution from untrusted natural language instructions is disabled by the Supervised Safety Policy.

