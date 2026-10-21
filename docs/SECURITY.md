# Cortex Security & Safety Policy

## Security Model Overview
Cortex operates directly on user workstations with access to local filesystem resources, applications, and mailboxes. A defense-in-depth security model prevents unauthorized actions, prompt injection, and accidental data exposure.

---

## 1. Cryptographic Human Approval Gates
- **High-Risk Action Protection:** Irreversible actions—specifically sending real emails, deleting files, or modifying system configurations—strictly require human confirmation before execution.
- **SHA-256 Approval Hashes:** Every email draft or critical action payload is hashed:
  ```python
  payload = f"{recipient}:{sender_account}:{subject}:{body}:{attachments}"
  approval_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
  ```
- **Automatic Invalidation:** If a user requests an edit (e.g., *"make it more formal"* or *"change deadline to Friday"*), any prior approval token is instantly invalidated and a fresh hash must be confirmed.

---

## 2. Prompt Injection Defense & Input Sanitization
All untrusted text from incoming emails, web search results, and scraped web pages passes through an active injection filter (`sanitize_untrusted_input`):
- Filters override patterns: `ignore all previous instructions`, `system prompt:`, `forget all prompts`, `developer mode:`, etc.
- Prevents exfiltration payloads targeting environment variables, API keys, or private files.
- Command vs. content separation guarantees that forwarded or quoted messages are never executed as agent directives.

---

## 3. Filesystem Sandboxing & Traversal Prevention
- Device actions enforce strict path resolution:
  - Relative paths and symlinks are resolved against the active workspace boundary.
  - Path traversal sequences (`../`, `..\\`) targeting sensitive system roots (`/System`, `/etc`, `/usr/bin`, Windows system directories) are rejected immediately.
- Shell commands undergo whitelist and argument verification to block destructive actions (`rm -rf /`, `mkfs`, format commands).

---

## 4. Local Data Encryption
- Local conversation logs, learned entity profiles, and contact address books stored in `work/cortex-memory.sqlite3` are protected by PBKDF2 key derivation and AES-256 encryption.
- No user credentials, tokens, or plaintext private messages are sent to third parties outside authorized model providers (Google Gemini API).
