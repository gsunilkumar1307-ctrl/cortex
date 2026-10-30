# CORTEX AGENT — PHASE 3 DEMO GUIDE
**Multilingual Communication & Email Safety Verification**

- **Date:** October 27, 2026
- **Target Languages:** English (`en`), Kannada (`kn`), Hindi (`hi`), Tamil (`ta`), Telugu (`te`)
- **Important:** No real email is sent during this demonstration without explicit user authorization. All tests and verification scripts execute safely in dry-run / mocked mode.

---

## 1. DEMO OVERVIEW

This guide demonstrates Cortex Agent's Phase 3 capabilities through a short, reproducible 6-step sequence:
1. Composing an email draft in English.
2. Composing an equivalent draft in Kannada (native script).
3. Applying a mixed-language (Hinglish/Kanglish) correction.
4. Rewriting the body into Kannada while keeping the subject in English.
5. Verifying that the language change recomputes the SHA-256 payload digest and invalidates prior approvals.
6. Enforcing mandatory user approval prior to execution.

---

## 2. PREREQUISITES & STARTUP

### Option A: Running with Desktop UI
1. Start the FastAPI backend:
   ```bash
   cd Codex/2026-06-17/files-mentioned-by-the-user-cortex
   python3 -m backend.api.server
   ```
2. In a separate terminal, launch the desktop app:
   ```bash
   cd apps/desktop
   npm start
   ```
3. Use the titlebar language selector badge (top right) to switch between `Auto`, `English`, `ಕನ್ನಡ`, `हिन्दी`, `தமிழ்`, or `తెలుగు`.

### Option B: Interactive Python / Terminal Verification
Execute commands directly via Python interactive shell or orchestrator CLI:
```bash
python3 -c "
from backend.agent.orchestrator import AgentOrchestrator
orc = AgentOrchestrator()
print('Ready for demo sequence')
"
```

---

## 3. STEP-BY-STEP REPRODUCIBLE SEQUENCE

### Step 1: English Email Draft Request
**User Prompt:**
> *"Write an email to prof.kapoor@iitb.ac.in asking for an extension on the project until Friday."*

**System Behavior:**
1. Language detected: `en` (English).
2. Intent identified: `TaskCommand.COMPOSE` (`send_mail`).
3. Extracted fields:
   - **To:** `prof.kapoor@iitb.ac.in`
   - **Subject:** `Project Extension Request`
   - **Body:** `Dear Professor, I would like to request an extension on the project until Friday. Thank you.`
4. An approval card is displayed showing:
   - Recipient, Subject, and Draft Body.
   - **Canonical SHA-256 Approval Hash:** (e.g., `e3b0c44...`)
   - Explicit prompt: *"Do you want me to send this email? (yes/no)"*

---

### Step 2: Request in Another Supported Language (Kannada)
**User Prompt (Native Script):**
> *"prof.sharma@iisc.ac.in ಗೆ ಪ್ರಾಜೆಕ್ಟ್ ವರದಿ ಬಗ್ಗೆ ಇಮೇಲ್ ಕಳುಹಿಸಿ"*

**System Behavior:**
1. Language detected: `kn` (Kannada script `\u0C80-\u0CFF`).
2. Intent identified: `send_mail`.
3. Extracted fields:
   - **To:** `prof.sharma@iisc.ac.in`
   - **Subject:** `ಪ್ರಾಜೆಕ್ಟ್ ವರದಿ` (Project Report)
   - **Body:** `ನಮಸ್ಕಾರ, ಪ್ರಾಜೆಕ್ಟ್ ವರದಿ ಕಳುಹಿಸುತ್ತಿದ್ದೇನೆ.`
4. Recipient address `prof.sharma@iisc.ac.in` is completely preserved without transliteration corruption.
5. New approval card generated with a unique SHA-256 hash.

---

### Step 3: Mixed-Language & Code-Switched Correction
**Context:** Continuing from the draft in Step 1.

**User Prompt:**
> *"Date change maadu, Friday badalu Monday 2026-11-02 maadu"*  
*(Mixed Kanglish/English command: "Change the date, make it Monday 2026-11-02 instead of Friday")*

**System Behavior:**
1. Intent: Follow-up draft edit (`confirm_send`).
2. Preserved fields:
   - Task ID remains identical.
   - Recipient remains `prof.kapoor@iitb.ac.in`.
3. Updated fields:
   - Body date updated to `Monday 2026-11-02`.
4. ISO Date `2026-11-02` is shielded by `EntityPreserver`.

---

### Step 4: Selective Multilingual Translation & Rewriting
**User Prompt:**
> *"Keep the subject in English but rewrite the body in Kannada."*

**System Behavior:**
1. Directive extracted: `extract_explicit_language_directive()` identifies `body_lang="kn"` and `subject_lang="en"`.
2. Subject retained in English: `Project Extension Request`.
3. Body translated to Kannada: `ಗೌರವಾನ್ವಿತ ಪ್ರೊಫೆಸರ್, ಸೋಮವಾರ 2026-11-02 ವರೆಗೆ ವಿಸ್ತರಣೆ ನೀಡಲು ವಿನಂತಿ.`
4. Masked date `2026-11-02` and professor titles are preserved.

---

### Step 5: Invalidation of Prior Approval & Digest Recomputation
**Verification Step:**
1. Before Step 4 edit, the draft had Hash $H_1$:
   ```python
   hash_1 = draft.compute_hash()
   # e.g. "9a7f3b..."
   ```
2. After Step 4 translation/edit, the draft recomputes Hash $H_2$:
   ```python
   hash_2 = draft.compute_hash()
   # e.g. "4c8d1e..."
   ```
3. Invariant Checked:
   - `assert hash_1 != hash_2`
   - Prior approval token for $H_1$ is strictly **invalidated**.
   - Attempting to send using $H_1$ is rejected by `EmailEngine.send_email()`.

---

### Step 6: Mandatory Explicit Approval Before Sending
**User Prompt:**
> *"Yes, send it."*

**System Behavior:**
1. User provides affirmative consent to send.
2. System confirms the token matches current hash $H_2$.
3. Pre-send verification executes:
   - Task status verified.
   - Action attempt record persisted to SQLite before any external call.
   - Sent-folder reconciliation scheduled.
4. Dry-run / test provider records successful dispatch without sending real external emails.

---

## 4. AUTOMATED DEMO VERIFICATION SCRIPT

To run the complete 6-step sequence automatically and view the live assertions:

```bash
cd /Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex
python3 -m unittest tests/test_phase3_multilingual.py -v
```

All 12 acceptance requirements (**ML-01 to ML-12**) execute and confirm PASS in under 0.25 seconds.

---

## 5. HUMAN-LIKE DRAFTING QUALITY & USERNAME NON-INFERENCE DEMO

To demonstrate Cortex Agent's refined drafting quality and non-hallucinated greetings:

### Multi-Turn Conversational Drafting Flow

**Turn 1 (Prompt):**
> *"send mail to gsunilkumar1307@gmail.com"*

**System Behavior:**
1. Direct email detected: `gsunilkumar1307@gmail.com`.
2. No name is hallucinated or inferred from the alphanumeric username `gsunilkumar1307`.
3. System prompts for body content:
   > *"What would you like me to send to gsunilkumar1307@gmail.com?"*

**Turn 2 (Prompt):**
> *"project presentation deadline is on 5 november"*

**System Behavior:**
1. Subject line determined accurately without unsolicited extension requests:
   - **Subject:** `Project Presentation Deadline`
2. Body polished with natural lead article, date formatting (`is on 5 november` → `is November 5`), neutral greeting `Hello,`, and clean sign-off:
   ```
   Hello,

   The project presentation deadline is November 5.

   Best regards
   ```
3. Cryptographic approval card generated:
   - Status: `WAITING_APPROVAL`
   - Explicit approval gate enforced before dispatch.

### Automated Test Command

```bash
cd /Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex
python3 -m unittest tests/test_human_like_email_quality.py -v
```

