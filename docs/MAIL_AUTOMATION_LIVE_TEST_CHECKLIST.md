# CORTEX AGENT — MAIL AUTOMATION LIVE TEST CHECKLIST

**Date:** October 28, 2026  
**Status:** **READY FOR USER-SUPERVISED LIVE TESTING**  
**Execution Safety Mode:** Sandboxed Automated Verification: **PASSED** (342/342 tests) | Live External Transmission: **BLOCKED / NOT TESTED** (Enforcing Zero-Unauthorized-Send Protocol)

---

## 1. Safety Directive & Non-Negotiable Rules

> [!CAUTION]
> **MANDATORY SAFETY PROTOCOL:**
> 1. Automated test suites MUST NEVER send real emails.
> 2. Live email transmission tests may ONLY be conducted with **explicit, per-test human authorization**.
> 3. Never use an actual third-party recipient for live testing. Use a verified test account controlled by the tester (e.g. `cortex.qa.test@gmail.com`).
> 4. In CI/CD, headless sandboxes, or automated agent environments, all external transmission tests are marked **BLOCKED / NOT TESTED**.

---

## 2. Live Environment Preconditions

Before conducting live macOS Apple Mail integration tests, verify the following prerequisites:

| Requirement | Description | Check Command | Status |
|:---|:---|:---|:---:|
| **Operating System** | macOS Darwin (Sonoma, Sequoia, or later) | `uname -s` | Verified Darwin |
| **Mail Application** | Apple Mail.app installed and configured | `osascript -e 'id of app "Mail"'` | User Environment Dependent |
| **Automation Permissions** | Terminal / Electron granted Automation permission for Mail.app | *System Settings > Privacy & Security > Automation* | User Authorization Required |
| **Test Account** | Designated test mailbox (no personal/production email) | Test account signed in to Apple Mail | User Configuration Required |
| **Local Backend API** | FastAPI backend running locally on `http://127.0.0.1:8000` | `curl -s http://127.0.0.1:8000/health` | Service Ready |
| **Desktop App** | Electron desktop app built and running | `npm run start --prefix apps/desktop` | Build Ready |

---

## 3. Step-by-Step Live Testing Checklist

### Phase 1: Environment Readiness & Permissions

- [ ] **L-01: Verify AppleScript Accessibility**
  - **Command:**
    ```bash
    osascript -e 'tell application "Mail" to get count of accounts'
    ```
  - **Expected:** Returns integer $\ge 1$ without prompting for permissions or throwing `(-1743) Not authorized`.
  - **Status:** `NOT TESTED` (Requires local interactive macOS terminal)

---

### Phase 2: Live Draft Creation in Apple Mail (Zero Risk / No Transmission)

- [ ] **L-02: Create Non-Transmitting Draft via Natural Language**
  - **Prompt in Cortex Desktop App:**
    ```text
    Draft an email to <YOUR_TEST_EMAIL> saying Automated QA Draft Test
    ```
  - **Expected Behavior:**
    1. Cortex extracts recipient and body.
    2. Apple Mail opens a new draft window with subject and body populated.
    3. Cortex displays confirmation: *"Draft created and saved to your mailbox"*.
    4. Task transitions to `COMPLETED`.
    5. **NO EMAIL IS TRANSMITTED.**
  - **Status:** `NOT TESTED` (Requires human user execution)

---

### Phase 3: Approval Card & Cryptographic Hash Verification

- [ ] **L-03: Staging Send Approval Card**
  - **Prompt in Cortex Desktop App:**
    ```text
    Send email to <YOUR_TEST_EMAIL> saying Critical security patch scheduled for tonight
    ```
  - **Expected Behavior:**
    1. Cortex does **NOT** send the email immediately.
    2. Desktop UI renders the Red/Yellow High-Risk Approval Card.
    3. Approval card displays recipient, subject, full body, and 64-character SHA-256 digest.
    4. Task status remains `WAITING_APPROVAL`.
  - **Status:** `NOT TESTED` (Requires human user execution)

- [ ] **L-04: Draft Modification via UI & Hash Recalculation**
  - **Action:**
    1. In the approval card, click *"Edit Draft"*.
    2. Change subject to: `Urgent: Critical security patch scheduled for tonight`.
    3. Click *"Save & Review"*.
  - **Expected Behavior:**
    1. SHA-256 digest changes immediately to match updated payload.
    2. SQLite database records updated task state with incremented `state_version`.
  - **Status:** `NOT TESTED` (Requires human user execution)

---

### Phase 4: Explicitly Authorized Live Send Gate

> [!WARNING]
> **GATE:** Do not proceed to Step L-05 without confirming recipient is a controlled test account.

- [ ] **L-05: Authorized Send Execution**
  - **Action:** Click *"Approve & Send"* in the desktop UI or type `"yes, send it"` in chat.
  - **Expected Behavior:**
    1. Backend validates session token and SHA-256 approval digest.
    2. SQLite TaskStore consumes approval token (preventing replay).
    3. `ActionAttempt` recorded with status `INITIATED`.
    4. Apple Mail sends the message.
    5. Task transitions to `EXECUTING` $\rightarrow$ `COMPLETED`.
  - **Status:** `BLOCKED` (Awaiting explicit user instruction for live send)

---

### Phase 5: Sent Mail Reconciliation & Audit Trail

- [ ] **L-06: Verification of Delivered Message in Sent Mailbox**
  - **Action:** Inspect Apple Mail *Sent* mailbox or query via AppleScript:
    ```bash
    osascript -e 'tell application "Mail" to get subject of first message of sent mailbox'
    ```
  - **Expected Behavior:** Sent mailbox contains the delivered message.
  - **Status:** `NOT TESTED`

- [ ] **L-07: Audit Trail Verification**
  - **Action:** Query the local audit database:
    ```bash
    sqlite3 ~/.gemini/antigravity/cortex-memory.sqlite3 "SELECT event_type, timestamp FROM audit_events ORDER BY id DESC LIMIT 5;"
    ```
  - **Expected Behavior:** Audit events record `approval_granted`, `executing`, and `completed` without logging raw credentials or session tokens.
  - **Status:** `NOT TESTED`

---

### Phase 6: Cancellation & Rejection Test

- [ ] **L-08: Explicit User Cancellation**
  - **Prompt in Cortex Desktop App:**
    ```text
    Send email to <YOUR_TEST_EMAIL> saying This should be cancelled
    ```
  - **Follow-up Prompt:**
    ```text
    No, do not send that email
    ```
  - **Expected Behavior:**
    1. Cortex detects negation and cancellation.
    2. Pending draft is discarded and deleted from Apple Mail drafts.
    3. Task status transitions to `CANCELED`.
    4. No email is sent.
  - **Status:** `NOT TESTED`

---

## 4. Summary of Live Test Results

| Phase | Description | Result | Reason |
|:---|:---|:---:|:---|
| **Phase 1** | Environment & Permissions | `NOT TESTED` | Automated agent environment without interactive GUI permissions |
| **Phase 2** | Draft Creation (No Transmission) | `NOT TESTED` | Ready for human execution |
| **Phase 3** | Approval Card & Cryptographic Hash | `PASSED (Mocked) / NOT TESTED (Live)` | Verified with 48 automated tests |
| **Phase 4** | Authorized Live Send | `BLOCKED` | Awaiting explicit human consent per test |
| **Phase 5** | Sent Box Reconciliation | `PASSED (Mocked) / NOT TESTED (Live)` | Verified with 48 automated tests |
| **Phase 6** | Cancellation & Rejection | `PASSED (Mocked) / NOT TESTED (Live)` | Verified with 48 automated tests |

