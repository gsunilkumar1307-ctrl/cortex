# Cortex Agent — Security & Governance Model

**Version:** 1.0  
**Status:** Active Engineering Policy  

---

## 1. Core Principle

**Cortex is the user's digital hands, not an autonomous substitute for the user's judgment.**
Under no circumstances may Cortex execute consequential external side-effects (such as sending messages, deleting data, transferring funds, or submitting forms) without explicit, informed, cryptographic human authorization.

---

## 2. Risk Classification Tiers

| Tier | Risk Level | Description | Actions / Commands | Approval Requirement |
|---|---|---|---|---|
| **Tier 1** | **LOW** | Read-only operations, local information retrieval, harmless state queries. | `web_search`, `read_mail`, `summarize_mail`, `search_files`, `read_file`, `calculate`, `open_application`, `focus_application`, `open_url` | Automated execution if permitted. |
| **Tier 2** | **MODERATE** | Reversible state modifications, local draft creation, local file editing. | `write_file`, `create_document`, `draft_mail`, `prepare_whatsapp`, `write_note`, `personal_task_create`, `calendar_create` | Automated if non-destructive; user confirmation required if overwriting existing content. |
| **Tier 3** | **CONSEQUENTIAL** | External communication, irreversible transmissions, data publication. | `send_mail`, `send_whatsapp_message`, `send_message`, `browser_click` (external form submission) | **Mandatory Cryptographic Approval Gate**. Single-use token, 15-minute expiration, payload hash binding. |
| **Tier 4** | **DESTRUCTIVE** | Irreversible data deletion, system state manipulation, credential exposure. | `shutdown`, `restart`, `format disk`, `delete account`, `rm -rf`, `wire money`, `payment` | **Permanently Blocked** or requires multi-factor confirmation with explicit consequence warning. |

---

## 3. Cryptographic Human-in-the-Loop Protocol

For all Consequential actions (Email and WhatsApp):
1. **Payload Hash Generation:**  
   Before requesting approval, Cortex computes a SHA-256 digest of the canonical action parameters:
   $$\text{Hash} = \text{SHA256}(\text{Canonicalize}(\text{recipient, body, attachments, account, channel}))$$
2. **Approval Request:**  
   The UI presents a structured, human-readable preview of the exact recipient, target channel, and complete generated content.
3. **Approval Verification:**  
   When the user clicks "Approve" or responds "yes" / "send it", the backend re-computes the hash from current draft state. If the draft was edited or altered in the interim:
   $$\text{Hash}_{\text{current}} \neq \text{Hash}_{\text{approved}} \implies \text{Approval Invalidated}$$
4. **Single-Use Replay Prevention:**  
   Each consumed approval token is permanently recorded in the SQLite `approvals` store. Subsequent attempts to reuse an authorization are rejected.
5. **Action Attempt Audit:**  
   Prior to contacting any external provider, an `ActionAttempt` record is committed with status `INITIATED`. Following execution, it is updated to `VERIFIED` or `FAILED` based on verifiable evidence.

---

## 4. Electron & Frontend Isolation

- **Context Isolation:** Enabled (`contextIsolation: true`).
- **Node Integration:** Disabled (`nodeIntegration: false`).
- **Preload Bridge:** Strictly restricted to non-privileged UI controls (`cortexAPI.showHud`, `cortexAPI.setWindowMode`). No shell, filesystem, or raw IPC exposure.
- **Session Authentication:** All HTTP requests to `127.0.0.1:8765` require `X-Cortex-Session`.
- **Header Scoping:** Electron `onBeforeSendHeaders` attaches the token only to localhost/127.0.0.1 origins, preventing credential leaks across external redirects.

---

## 5. Privacy & Data Protection

- **No Sensitive Logging:** Passwords, API keys, tokens, session secrets, and message bodies are excluded from standard log output and marked with `••••••` in the UI audit log.
- **Local Persistence:** All task records, audit logs, and memories are stored on the local filesystem with SQLite AES-256 / Fernet encryption. No telemetry or conversation transcripts are sent to third parties without user configuration.
- **Untrusted External Content:** Content fetched from web pages, email inboxes, or external messages is treated as untrusted data. External content cannot trigger commands or grant approvals.

