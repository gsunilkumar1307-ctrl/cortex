# CORTEX AGENT — PERSONAL WHATSAPP DEMO GUIDE

This guide walks you through verifying the safe, user-supervised personal WhatsApp integration in Cortex on macOS Apple Silicon.

---

## 1. Prerequisites & Launching

### A. Environment Check
- **macOS Apple Silicon:** Ensure macOS Accessibility permissions are granted to your terminal / Electron (`System Settings → Privacy & Security → Accessibility`).
- **Official WhatsApp Desktop:** Installed at `/Applications/WhatsApp.app` (Net.whatsapp.WhatsApp) and authenticated with your personal account.

### B. Launching Cortex Backend & Desktop App
```bash
# Terminal 1: Start Cortex Agent Backend
cd Codex/2026-06-17/files-mentioned-by-the-user-cortex
export CORTEX_EXECUTION_MODE=live
python3 -m backend.api.server

# Terminal 2: Start Desktop App
cd Codex/2026-06-17/files-mentioned-by-the-user-cortex/apps/desktop
npm start
```

---

## 2. Interactive Demo Scenarios

### Scenario 1: The P0 Incident Remediation (Unknown Contact Fail-Closed)
**User Input:**
> *"Send a WhatsApp to Rahul Engg saying are you free to discuss the presentation?"*

**Expected Behavior:**
1. Cortex focuses WhatsApp and executes a bounded search for `"Rahul Engg"`.
2. Because *"Rahul Engg"* is not in your contacts, Cortex does **not** substitute *"Rahul Sharma"* or any other contact.
3. Cortex does **not** invent or synthesize a phone number.
4. Cortex responds cleanly:
   > *"No contact found for 'Rahul Engg' in WhatsApp visible UI."*
5. Task status transitions to `NEED_INFO`. No message draft is prepared or sent.

---

### Scenario 2: Draft-Only Message Preparation (Zero Send Risk)
**User Input:**
> *"Open WhatsApp and prepare a message to Rahul Engg saying: 'Hi Rahul, this is a test message from my Cortex Agent project. Please ignore this message; I am testing message preparation.' Show me the exact recipient and message, but do not send it."*

**Expected Behavior:**
1. Cortex identifies the explicit draft-only intent (`draft_only: true`).
2. Message body preserves the exact quoted message:
   `"Hi Rahul, this is a test message from my Cortex Agent project. Please ignore this message; I am testing message preparation."`
3. Cortex prepares the message in WhatsApp composer for visual inspection.
4. The result card displays:
   - Recipient: `Rahul Engg [Phone number not visible in UI]`
   - Badge: **"Draft only — not sent"** (in blue)
   - Notice: *"Draft only — not sent. Ready in WhatsApp composer for review. Direct send disabled."*
   - The **"Approve & Send"** button is **completely hidden**.
5. Even if an approval API call is attempted programmatically, the backend rejects it with:
   > *"Cannot send: task was designated as draft-only ('Draft only — not sent')."*

---

### Scenario 3: Instruction Wrapper Stripping & Tone Adaptation
**User Input:**
> *"Send WhatsApp to Priya Patel saying: Inform her that the project presentation deadline is November 5."*

**Expected Behavior:**
1. Cortex strips the command wrapper (`"Inform her that"`) and formats a natural message:
   > *"Hi Priya, just a reminder that the project presentation deadline is November 5."*
2. Cortex displays the approval card showing:
   - To: `Priya Patel (+91 98765 67890)`
   - Contact Provenance: `✓ Verified Contact (user_authorized_contacts)`
   - Message: `Hi Priya, just a reminder that the project presentation deadline is November 5.`
   - Cryptographic SHA-256 Approval Hash
3. **Conversational Refinement (Tone):**
   - User says: *"Make it more formal."*
   - Cortex updates the draft to:
     > *"Dear Priya, I wanted to inform you that the project presentation deadline is November 5."*
   - Cortex recalculates the approval hash and displays the revised card.

---

### Scenario 4: Cryptographic Approval & Send Execution
**User Input:**
> *"Approve"* (or click **"Approve & Send"**)

**Expected Behavior:**
1. Cortex verifies the approval token matches the canonical SHA-256 hash.
2. Cortex checks that the active conversation in WhatsApp Desktop matches `"Priya Patel"`.
3. Cortex creates a durable `WhatsAppSendAttempt` record in the database.
4. Cortex dispatches the return key and verifies the composer cleared.
5. Cortex marks the attempt `confirmed_sent` and updates task status to `COMPLETED`.
6. **Replay Protection Check:** If you replay the approval token or click send again, Cortex rejects the request:
   > *"Approval replay detected: this cryptographic approval was already consumed."*

---

### Scenario 5: Multilingual Cancellation
**User Input:**
1. User says: *"Send WhatsApp to Alex Chen saying review the design."*
   (If multiple contacts match, Cortex displays candidate 1 and candidate 2)
2. User cancels in Kannada: *"ಬೇಡ"* (or in Hindi: *"रद्द करें"*, or in English: *"cancel"*)
3. Cortex immediately cancels the task and invalidates any pending tokens:
   > *"Task canceled. No message was sent."*

