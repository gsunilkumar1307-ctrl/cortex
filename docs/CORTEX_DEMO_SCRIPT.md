# CORTEX AGENT — 5–7 MINUTE LIVE DEMONSTRATION SCRIPT

**Target Duration:** 5–7 minutes  
**Target Audience:** Project Evaluators, College Project Examination Committee  
**Environment:** macOS (Apple Silicon / Intel), Terminal + Electron Desktop App  
**Prerequisites:** Accessibility & Screen Recording permissions enabled in System Settings.

---

## Pre-Flight Checklist (1 Minute Before Demo)

1. Launch backend and desktop app:
   ```bash
   bash scripts/start-cortex.sh
   # Or run rehearsal test: python3 scripts/rehearse_presentation_demo.py
   ```
2. Verify Apple Mail is open or available on macOS.
3. Open Safari with any webpage (e.g. ScienceDaily or Apple.com).
4. Ensure `~/Downloads` has at least 3–5 files for inspection.

---

## Demo Step 1: Conversational Intelligence & Grounded Capabilities (1.0 Minute)

### Presenter Action:
Type or speak:
> **"Hi Cortex. What can you help me with?"**

### Expected Output:
Cortex responds with its actual verified capabilities on this Mac:
- **Safari Web Research & Live Inspection**
- **macOS Screen Observation & UI Perception**
- **Apple Mail Drafting & Iterative Revision**
- **Finder File & Directory Inspection**
- **Apple Notes Management**

### Presenter Talking Point:
> *"Notice that Cortex does not fabricate unverified abilities. It clearly distinguishes capabilities verified in this active session from those requiring system permissions or external credentials."*

### Follow-up Query:
> **"Explain the key difference between a process and a thread."**  
> *(Followed by)*: **"Can they share memory with each other?"**

### Presenter Talking Point:
> *"Context is preserved across turns without history contamination or hallucination."*

---

## Demo Step 2: Native macOS Control & Screen Observation (1.5 Minutes)

### Presenter Action:
> **"Open Safari."**

### Expected Output:
Safari is brought to the front immediately.

### Next Prompt:
> **"Determine which application is active and describe five visible elements."**

### Expected Output:
```markdown
- **Active application:** Safari
- **Active window:** Artificial Intelligence News -- ScienceDaily
- **Visible elements:**
  1. [Application] Safari (source: accessibility)
  2. [Menu item] Apple (source: accessibility)
  3. [Menu item] About This Mac (source: accessibility)
  4. [Menu item] System Information (source: accessibility)
  5. [Menu item] System Settings… (source: accessibility)
- **Limitations:** None
```

### Presenter Talking Point:
> *"Cortex uses native macOS Accessibility APIs and Apple Vision OCR. Crucially, it filters out invalid or negative nodes like `[Unknown]` or `-1`, reporting only grounded, interactive elements."*

---

## Demo Step 3: Verified Finder Inspection (Read-Only) (1.0 Minute)

### Presenter Action:
> **"Open Finder, navigate to Downloads and show me the first five visible filenames. Do not modify anything."**

### Expected Output:
```markdown
### Finder Inspection: Downloads

• **Finder Status:** Activated and navigated to `/Users/gsunilkumar/Downloads`.
• **Inspection Type:** Directory entries (read-only filesystem listing).
• **Ordering:** Alphabetical (case-insensitive, ascending).
• **Items displayed:** First 5 of 26 entries:
  1. 2071614.jpg
  2. Antigravity IDE.dmg
  3. Antigravity.dmg
  4. Cortex Elite Prd Trd Master Document (1).pdf
  5. Cortex-Autonomous-Agentic-AI.pdf
• **Filesystem Status:** Verified read-only inspection. No files created, modified, or deleted.
```

### Presenter Talking Point:
> *"This demonstrates safe read-only desktop inspection. Cortex guarantees that no files are modified, renamed, or deleted during inspection."*

---

## Demo Step 4: Apple Mail Professional Draft & Revisions (1.5 Minutes)

### Presenter Action:
> **"Create a professional draft in Apple Mail to Rahul about our project presentation. Do not send it."**

### Expected Output:
Draft created in Apple Mail with:
- Recipient: `Rahul Verma <rahul@example.com>`
- Subject: `Our Project Presentation`
- Body: Professional presentation review copy
- Status: Saved to Apple Mail Drafts mailbox; awaiting explicit approval.

### Revision 1:
> **"Make it shorter."**  
*(Body is concisely updated in-place; old draft window is cleaned up).*

### Revision 2:
> **"Add this paragraph: Please bring your project report copies."**  
*(Paragraph appended cleanly without duplicate draft accumulation).*

### Presenter Talking Point:
> *"Notice multi-turn conversational editing. Cortex updates the draft in Apple Mail without leaving behind orphaned draft windows."*

---

## Demo Step 5: Gmail Integration Disclosure (0.5 Minutes)

### Presenter Action:
> **"Draft an email in Gmail to Rahul about the project saying let's review Phase 3 deliverables."**

### Expected Output:
Draft generated in the transactional Gmail Sandbox store (or live if `GMAIL_ACCESS_TOKEN` is supplied).

### Presenter Talking Point:
> *"We maintain strict truth-in-reporting: without a live production OAuth token, Cortex operates Gmail in a local sandbox mode and explicitly labels it as such, rather than claiming live dispatch."*

---

## Demo Step 6: Safety, Cryptographic Binding & Replay Prevention (1.0 Minute)

### Presenter Action:
When Cortex presents the draft confirmation card, reply casually:
> **"looks good"**

### Expected Output:
```text
I'm glad the draft looks good! However, Cortex requires explicit authorization before sending any message. Please say 'Send it' or click Approve to confirm sending.
```

### Presenter Talking Point:
> *"Vague affirmations like 'looks good' or 'sounds fine' are deliberately rejected. Cortex enforces human-in-the-loop governance: only explicit commands like 'Send it' or the cryptographic UI Approve button can trigger external transmission."*
>
> *"Furthermore, every approval token is bound to a SHA-256 hash of the exact draft body. If content is tampered with, or if an attacker attempts to replay an already-consumed token, the execution is blocked."*

---

## Demonstration Wrap-Up & Conclusion

> *"To summarize: Cortex is an end-to-end, safety-first desktop assistant combining cloud foundation models with native macOS systems intelligence. 654 automated regression tests verify every capability, and every live action is strictly grounded, verifiable, and safe."*

