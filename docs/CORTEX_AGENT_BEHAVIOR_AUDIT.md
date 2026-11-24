# CORTEX AGENT — REAL AGENT BEHAVIOR AUDIT
## READ-ONLY FAILURE INVESTIGATION & ARCHITECTURAL ROOT CAUSE ANALYSIS

**Audit Date:** 2026-11-19  
**Audit Scope:** Real Agent Behavior, Autonomous Goal Completion, and Email Intelligence  
**Audit Mode:** Strict Read-Only Source Code & Architectural Inspection  
**Investigated Artifacts:**
- Orchestration & Chat: `backend/agent/orchestrator.py`
- Natural Language & Intent: `backend/core/contracts.py`, `backend/agent/policy.py`
- Email Engine & Drafting: `backend/agent/email_engine.py`
- Recipient Resolution: `backend/agent/recipient_resolver.py`
- Planning & Execution: `backend/agent/planner.py`, `backend/agent/execution_engine.py`
- Mail Automation: `backend/capabilities/mail_actions.py`, `backend/capabilities/device_actions.py`
- MCP Architecture: `backend/mcp/manager.py`, `backend/mcp/client.py`, `backend/mcp/config.py`

---

## 1. EXECUTIVE VERDICT

### **VERDICT: CONFIRMED ARCHITECTURAL BREAKDOWN**

Cortex is **not functioning as an autonomous, goal-oriented AI agent**. 

The investigation confirms the diagnosis: the system currently operates as a **rigid, regex-driven, single-shot intent dispatcher** layered on top of brittle string matching, fixed response templates, and disconnected tools.

### Core Discoveries
1. **Absence of an Agent Loop:** There is **no iterative ReAct or Plan-Execute-Evaluate loop** for email or conversational tasks. When a user issues a command, Cortex classifies it into a single `TaskCommand`, maps it to a hard-coded static method, executes a single one-shot function, formats the result with a string template, and immediately terminates.
2. **Intentional Crippling of Autonomy ("Command ≠ Content" Dogma):** System prompts and regex parsers deliberately zero out the `body` parameter when intent is detected (e.g. *"asking about internship opportunities"*). Cortex then falls into a hardcoded `if not body:` trap, forcing the user to supply content rather than autonomously drafting it.
3. **Conversational Query Pollution:** Search queries are extracted using fragile regular expressions that strip only specific prefixes. Unmatched conversational phrases (e.g. *"I received last week"*, *"Find unread emails"*) remain in the query string and are forwarded literally to search filters, guaranteeing zero matches.
4. **Identity Blindness:** `RecipientResolver` has no concept of the user's self-identity (`"myself"`, `"me"`). It never inspects connected mail accounts (`get_accounts()`), leading to absurd prompts asking who "myself" is.
5. **Shallow, Unranked Message Fetching:** AppleScript fallbacks fetch an arbitrary slice of 50 messages based on internal Mail.app storage order. Results are **never sorted by date**. A request for the "latest email" returns an arbitrary or ancient email.
6. **Catastrophic 429 Circuit Breaker:** When Gemini encounters an HTTP 429 rate limit, a 180-second (3-minute) hard circuit breaker shuts off model access across the entire application, collapsing all subsequent interactions into raw regex fallbacks and canned responses.
7. **Shallow Summarization:** Summarization prompts only format 250-character message snippets; the actual message body is never fetched from the mailbox before calling the LLM.

---

## 2. PHASE 1 — TRACE OF COMPLETE EXECUTION PATH

Tracing a user request through the active codebase:

```
User Input (Desktop UI / API)
  │
  ▼
backend/api/server.py (/api/chat)
  │
  ▼
backend/agent/orchestrator.py: CortexOrchestrator.chat(message)
  │
  ├── 1. Resumption, cancellation, pending_action check (lines 1070–1250)
  │      [Over 1,000 lines of hardcoded regex branches for pending states]
  │
  ├── 2. Intent Analysis: _analyze_intent(message) (lines 632–715)
  │      ├── If Gemini available: Calls model with SYSTEM_PROMPT requesting JSON
  │      │   └── Post-processes: Overrides params via _extract_params()
  │      └── If Gemini unavailable/429: _analyze_intent_fallback() (regex-only)
  │
  ├── 3. Command Precedence & Need-Info Trap (lines 2217–2330)
  │      └── If command in (DRAFT_MAIL, SEND_MAIL) and not params.get("body"):
  │          └── HALTS: Sets pending_action="waiting_for_body", asks user to write body!
  │
  ├── 4. Direct Orchestrator Dispatch (lines 4815–4875)
  │      ├── DRAFT_MAIL     ──> self.automation.execute(DRAFT_MAIL) ──> returns string template
  │      ├── SUMMARIZE_MAIL ──> self.automation.execute(READ_MAIL)  ──> _summarize_emails(snippets)
  │      ├── READ_MAIL      ──> self.automation.execute(READ_MAIL)  ──> returns string template
  │      └── SEARCH_MAIL    ──> self.automation.execute(SEARCH_MAIL)──> returns string template
  │
  └── 5. General Question Fallthrough (lines 4580–4610)
         └── If command in (ASK_QUESTION, UNKNOWN):
             └── Answers as conversational trivia (NO tools called, NO mailbox access)
```

### Architectural Findings from the Trace:
- **No Agentic Tool Loop:** `AutonomousPlanner` (`backend/agent/planner.py`) and `ExecutionEngine` (`backend/agent/execution_engine.py`) are **bypassed completely** for all email operations (`DRAFT_MAIL`, `READ_MAIL`, `SEARCH_MAIL`, `SUMMARIZE_MAIL`). They are executed as monolithic single-shot functions inside `orchestrator.py:4815-4875`.
- **Premature Workflow Termination:** Every email action terminates on the very first tool response. If `search_mail` returns 0 results, Cortex does not inspect the failure, does not broaden the query, does not check other accounts, and does not try alternative search keywords.
- **No Next-Step Reasoning:** There is no mechanism where an LLM inspects tool output and decides: *"Search returned 0 emails because 'internships' was plural. Let me search for 'intern'."*
- **Regex Dominance:** Brittle regex patterns in `orchestrator.py` and `email_engine.py` dictate parameters before the model or tools can reason.

---

## 3. PHASE 2 — INVESTIGATION OF THE 9 OBSERVED FAILURES

### Failure 1: "Do I have any emails from Apple?" → 0 results
- **Trace:**
  1. `_extract_mail_search_params()` (`orchestrator.py:5810`) matches regex:
     `from_m = re.search(r"\b(?:from|sent\s+by)\s+([a-zA-Z0-9_\-.\s@]+?)...", raw)`
     Extracts `sender="Apple"`, `query="Apple"`.
  2. Dispatches to `MailAutomation.search_mail(query="Apple", sender="Apple")`.
  3. If Apple Mail MCP is unavailable, times out, or fails, execution falls back to AppleScript (`mail_actions.py:1280`):
     ```python
     res = self.read_mail(limit=50, ...)
     ```
  4. In `read_mail()` (`mail_actions.py:270`):
     ```applescript
     set targetMessages to (messages 1 thru takeCount of b)
     ```
     AppleScript fetches messages 1 to 50 in **storage order** (oldest or arbitrary folder index) from `{inbox, sent mailbox}`.
  5. If the user has thousands of messages in their mailbox and Apple emails are not in the first 50 storage indices, they are never retrieved into memory!
  6. Furthermore, `b` only covers the primary account's default inbox, ignoring secondary IMAP accounts.
- **Root Cause:** AppleScript search fallback does not execute a server-side search; it scans an arbitrary window of 50 storage-ordered messages from a single inbox.

---

### Failure 2: "Find emails about internships." → Search behavior needs verification for real semantic retrieval
- **Trace:**
  1. `_extract_mail_search_params()` (`orchestrator.py:5830`) matches `about internships`.
  2. Sets `params["subject"] = "internships"` and `params["query"] = "internships"`.
  3. In `MailAutomation.search_mail()` $\rightarrow$ `_matches_filters()` (`mail_actions.py:1115`):
     ```python
     if sbj_lower:
         if sbj_lower not in em.get("subject", "").lower():
             return False
     ```
  4. This is a strict Python substring match (`"internships" in subject.lower()`).
  5. Real-world emails frequently say *"Summer Internship Opportunity"*, *"Software Engineer Intern"*, or *"Campus Placement"*.
  6. In Python: `"internships" in "summer internship opportunity"` $\rightarrow$ **`False`**.
- **Root Cause:** Zero semantic search, zero stemming, and zero lemmatization. Plural/singular mismatches instantly drop valid messages.

---

### Failure 3: "Show me the latest email from Google." → It finds a result, but verify whether it retrieves and ranks actual messages correctly
- **Trace:**
  1. `_extract_mail_search_params()` (`orchestrator.py:5750`) detects `latest` and sets `params["limit"] = 1`. Sets `sender="Google"`, `query="Google"`.
  2. In `search_mail()` (`mail_actions.py:1269, 1324`), matching messages are sliced:
     ```python
     return {"ok": True, "emails": matching[:limit], ...}
     ```
  3. **Inspection of lines 1220–1330 reveals that `matching` is NEVER sorted by date.**
  4. In AppleScript fallback, `read_mail` retrieves messages 1 to 50 in storage order. The first message matching "Google" is returned. This message is often from months or years ago.
- **Root Cause:** Complete absence of date sorting/ranking on search results before applying `[:limit]`.

---

### Failure 4: "Find emails I received last week." → Treats the full sentence as a literal query instead of correctly interpreting date intent
- **Trace:**
  1. `_extract_mail_search_params()` (`orchestrator.py:5760`):
     `last week` regex correctly sets `params["date_from"]` and `params["date_to"]`.
  2. Then lines 5850–5858 execute:
     ```python
     if not params["query"]:
         clean = re.sub(r"^(?:do i have any mail from|...|find emails)\s*", "", raw, flags=re.IGNORECASE).strip()
         params["query"] = clean or raw
     ```
  3. `re.sub` removes `"Find emails "` from `"Find emails I received last week."`.
  4. The remaining natural-language clause **`"I received last week"`** becomes `params["query"]`!
  5. `search_mail()` executes with `query="I received last week"`.
  6. `_matches_filters()` requires `"i received last week"` to exist literally in the sender, subject, or snippet.
- **Root Cause:** Regex stripping bug; unparsed natural-language text falls through into the search keyword parameter.

---

### Failure 5: "Find unread emails." → Returns 0 results; investigate whether unread filtering is correctly implemented
- **Trace:**
  1. In `_extract_mail_search_params()` (`orchestrator.py:5745`):
     `re.search(r"\bunread\b", raw)` sets `params["unread_only"] = True`.
  2. In lines 5850–5858:
     The cleanup regex `r"^(?:do i have any mail from|...|find emails)\s*"` looks for `"find emails"` at the start of the string.
     In `"Find unread emails."`, the word `"unread"` sits between `"Find"` and `"emails"`.
     The regex **fails to match**.
  3. `clean` remains **`"Find unread emails"`**, which becomes `params["query"]`!
  4. Cortex invokes `search_mail(query="Find unread emails", unread_only=True)`.
  5. It searches for emails that literally contain the text *"Find unread emails"*.
  6. Furthermore, in `read_mail()` (`mail_actions.py:288`):
     ```applescript
     set scanLimit to 50
     repeat with i from 1 to scanLimit
         set candidate to message i of b
         if read status of candidate is false then ...
     ```
     It only checks the first 50 storage messages.
- **Root Cause:** Keyword extraction regex failure causing query pollution combined with a 50-message scan limit in AppleScript.

---

### Failure 6: "Summarize the latest email from IBM." → It finds an email, but actual summarization fails when the Gemini provider hits a 429 rate limit
- **Trace:**
  1. `SUMMARIZE_MAIL` dispatches to `_summarize_emails(emails)` (`orchestrator.py:3847`).
  2. Line 3862 builds the prompt:
     ```python
     formatted = "\n\n".join([
         f"From: {e.get('sender')}\nSubject: {e.get('subject')}\nDate: {e.get('date')}\nSnippet: {e.get('snippet')}"
         for e in emails
     ])
     ```
     **The email body is never fetched.** Cortex passes only a 250-character snippet.
  3. When Gemini returns HTTP 429 (`ResourceExhausted`):
     `_handle_gemini_error()` (`orchestrator.py:627`) executes:
     ```python
     self.gemini_cooldown_until = time.time() + 180.0  # 3-minute hard lockout
     ```
  4. The catch block in `_summarize_emails()` drops to lines 3883–3885:
     ```python
     lines = [f"• From {e.get('sender', 'Unknown')}: {e.get('subject', 'No subject')}" for e in emails]
     return f"You have {len(emails)} recent emails:\n" + "\n".join(lines)
     ```
  5. It does not summarize; it outputs a raw list of senders and subjects.
  6. For the next 3 minutes, `_is_gemini_available()` returns `False` for **all** user interactions.
- **Root Cause:** Summarization lacks body retrieval; 429 error handling uses a catastrophic 3-minute complete system lockout without local summarization fallback.

---

### Failure 7: "Is there anything I need to respond to?" → Does not reliably perform actual message analysis
- **Trace:**
  1. In `backend/core/contracts.py:1117` (`command_from_intent`):
     The prompt does not match explicit command verbs like `"send"`, `"draft"`, `"search mail"`.
     It defaults to `TaskCommand.ASK_QUESTION`.
  2. In `orchestrator.py:4580`:
     ```python
     if task.command in (TaskCommand.ASK_QUESTION, TaskCommand.UNKNOWN):
         answer = self._answer_general_question(task.intent, lang_code=lang)
         task.result = answer
         return
     ```
  3. **Zero tools are invoked.** No inbox messages are read, no sent messages are checked, and no dates are compared.
  4. The model is asked "Is there anything I need to respond to?" with zero mailbox context. The model either hallucinates or asks the user what messages they are referring to.
- **Root Cause:** Goal queries are misclassified as general chat questions because Cortex has no goal-decomposition layer capable of understanding that this requires inspecting unread/recent inbox messages.

---

### Failure 8: "Draft an email to Rahul asking about internship opportunities." → Asks the user to supply the message content rather than autonomously composing an appropriate draft
- **Trace:**
  1. In `backend/agent/email_engine.py:596-608`:
     Pattern 4 matches:
     `p_mail_to = re.match(r"^(?:send|write|draft|prepare|compose)\s+(?:an?\s+)?(?:email|mail)\s+to\s+([a-zA-Z0-9_\s.'@%+&-]+?)\s+(?:asking\s+(?:about|for|whether|if)|inquiring\s+(?:about|whether))\s+(.+?)(?:\s+(?:saying|that\s+says|with\s+body|:)\s+(.+))?$", ...)`
  2. Extracts:
     - `raw_rec` = `"Rahul"`
     - `topic` = `"internship opportunities"`
     - `body_text` = `""` (because `"saying <body>"` was omitted)
  3. Sets `subject = "Regarding: Internship Opportunities"` and **`body = ""`**.
  4. In `orchestrator.py:2217`:
     ```python
     elif command in (TaskCommand.SEND_MAIL, TaskCommand.DRAFT_MAIL) and not params.get("body", "").strip():
         ...
         self.pending_action = {"type": "email_draft", "step": "waiting_for_body", ...}
         response = localize("need_body", raw_lang_code, recipient=raw_recipient)
     ```
  5. Furthermore, `SYSTEM_PROMPT` (`orchestrator.py:243`) explicitly commands:
     ```
     CRITICAL RULE — COMMAND ≠ CONTENT:
     - If body/content not provided, leave body as "" — do NOT invent content.
     ```
- **Root Cause:** Explicit architectural policy forbidding the agent from drafting content from user intent, forcing an unnecessary user-facing prompt.

---

### Failure 9: "Write a mail to myself requesting leave tomorrow." → Fails to identify the user's own connected email identity
- **Trace:**
  1. Recipient extraction captures the string `"myself"`.
  2. `RecipientResolver.resolve("myself")` (`recipient_resolver.py:315`):
     - Direct email regex: fails.
     - `_search_mailbox("myself")`: searches past incoming emails for a sender named "myself" $\rightarrow$ 0 results.
     - `_search_contacts("myself")`: searches contacts for name "myself" $\rightarrow$ 0 results.
  3. **`RecipientResolver` never queries connected accounts (`self.mail_automation.get_accounts()`).**
  4. It has no alias mapping for `"myself"`, `"me"`, `"self"`, or `"my email"`.
  5. Returns `status="unknown"`: `"I couldn't find an email address for 'myself'. Could you please provide their email address?"`.
- **Root Cause:** Recipient resolver is completely isolated from the user's connected account identity.

---

## 4. PHASE 3 — AGENT CAPABILITY ASSESSMENT

| Capability | Current Status | Detailed Source Evidence |
|---|:---:|---|
| **Goal Understanding** | **NOT IMPLEMENTED** | Relies on rigid regex patterns and JSON schema extraction (`orchestrator.py:632-730`). "Find emails I received last week" becomes literal query string `"I received last week"` (`orchestrator.py:5858`). |
| **Planning** | **NOT IMPLEMENTED** | `AutonomousPlanner.plan()` (`planner.py:25-90`) is an `if/elif` switch that returns a single, hardcoded `PlanStep`. Zero LLM decomposition. Bypassed entirely for mail tasks. |
| **Tool Selection** | **NOT IMPLEMENTED** | Tools are strictly hardcoded to specific `TaskCommand` values (`orchestrator.py:4815-4875`). The agent cannot choose to use `search_mail` when an `ASK_QUESTION` goal requires it. |
| **Tool Chaining** | **NOT IMPLEMENTED** | Workflows are single-shot dispatches. Cortex cannot chain: `Search Email` $\rightarrow$ `Extract ID` $\rightarrow$ `Fetch Body` $\rightarrow$ `Summarize Content`. |
| **Result Interpretation** | **NOT IMPLEMENTED** | Tool results are passed directly into string templates (`orchestrator.py:4859`). Cortex never inspects results to evaluate whether the goal was satisfied. |
| **Self-Correction** | **NOT IMPLEMENTED** | When search returns 0 items, execution terminates immediately. No query broadening, no alternative keyword attempts, no relaxation of filters. |
| **Context Continuity** | **PARTIALLY IMPLEMENTED** | Context variables (`last_mail_results`, `last_note`, `pending_action`) exist, but conversational editing is heavily regex-driven and prone to losing state on interruption. |
| **Autonomy** | **NOT IMPLEMENTED** | "COMMAND ≠ CONTENT" dogma explicitly forbids generating email drafts from intent topics (`SYSTEM_PROMPT`, line 243). Identity "myself" cannot be resolved autonomously. |
| **Safety** | **VERIFIED** | Centralized `is_real_email_send_allowed()` gate (`safety.py:129`), SHA-256 draft integrity, single-use token consumption, and 300s expiration are strictly enforced. |
| **Truthfulness** | **PARTIALLY IMPLEMENTED** | Safety status is truthful, but "Summarize" outputs unsummarized sender lists without reporting failure, and "Show latest" returns unranked storage indices. |

---

## 5. PHASE 4 — GEMINI 429 RATE-LIMIT COLLAPSE

### Root Cause Analysis of 429 Handling
1. **Inefficient Token Usage:** Every turn constructs a fresh Gemini model instance and resends the entire conversation history without caching or prompt compression.
2. **Aggressive Circuit Breaker:**
   `backend/agent/orchestrator.py:624-631`:
   ```python
   def _handle_gemini_error(self, exc: Exception, context: str = "") -> None:
       err_str = str(exc).lower()
       if "429" in err_str or "quota" in err_str or "resourceexhausted" in err_str or "rate limit" in err_str:
           self.gemini_cooldown_until = time.time() + 180.0  # 3-minute cooldown
   ```
   A single transient 429 immediately locks out the model for **180 seconds**.
3. **No Exponential Backoff or Jitter:** Cortex has no bounded retry loop (e.g. 1s, 2s, 4s with exponential backoff) for transient quota exhaustion.
4. **Complete System Degradation:** During cooldown, `_is_gemini_available()` returns `False`. The orchestrator drops to:
   - Regex intent fallback (`_analyze_intent_fallback`).
   - Canned conversational answers (`"I don't have an answer to that question."`).
   - Raw bullet lists for summarization.

---

## 6. PHASE 5 — PRIORITIZED ROOT CAUSES

### Priority 0 (P0) — Fundamental Execution Failures
- **P0.1: Lack of Iterative Agent Loop:** Email and information goals are handled as one-shot function dispatches rather than goal-directed agent loops.
- **P0.2: Autonomy Suppression ("Command ≠ Content"):** System prompt and parser zero out email body when a topic is given, preventing autonomous draft composition.

### Priority 1 (P1) — Core Agent Capability Failures
- **P1.1: Search Query Pollution:** Unparsed natural language ("I received last week", "Find unread emails") is passed as literal search keywords, causing zero results.
- **P1.2: Identity Blindness:** `RecipientResolver` cannot resolve "myself" / "me" because it never queries connected account identities.
- **P1.3: Disconnected Goal Routing:** Goal queries like "Is there anything I need to respond to?" fall through to generic chat with zero tool execution.

### Priority 2 (P2) — Reliability & Retrieval Gaps
- **P2.1: 50-Message Storage-Order Limitation & Unranked Results:** AppleScript mail reading only inspects the first 50 storage-ordered messages, ignoring secondary accounts and failing to sort by date descending.
- **P2.2: Catastrophic 3-Minute 429 Lockout:** A single 429 rate limit shuts down the entire model for 180 seconds without retry with backoff.
- **P2.3: Snippet-Only Summarization:** Summarization operates on 250-character snippets rather than retrieving full message bodies.
- **P2.4: Strict Substring Search Matching:** Search has no stemming or fuzzy matching (e.g. "internships" vs "internship").

### Priority 3 (P3) — UX & Consistency Gaps
- **P3.1: Silent Fallback to Bullet Lists:** When summarization fails, Cortex outputs raw sender/subject lists without informing the user that summarization failed.

---

## 7. PHASE 6 — MINIMAL REMEDIATION PLAN

The proposed remediation preserves the existing architecture, MCP integrations, safety gates, and storage systems while transforming Cortex into an autonomous agent.

### Remediation Modules

#### Module 1: Autonomous Goal-Driven Draft Composition (Fixes Failure 8)
- Update `SYSTEM_PROMPT` in `orchestrator.py`: Replace `leave body as ""` with an instruction to compose a concise, professional initial draft when topic or intent is provided.
- In `email_engine.py`: When pattern matches topic/intent (e.g. *"asking about internship opportunities"*), populate a default draft body or generate it via LLM instead of returning empty string.
- In `orchestrator.py:2217`: Only prompt for body if neither body nor intent topic is present.

#### Module 2: User Identity Resolution in RecipientResolver (Fixes Failure 9)
- In `RecipientResolver.resolve()`: Add self-identity detection (`"myself"`, `"me"`, `"self"`, `"my email"`).
- Connect to `mail_automation.get_accounts()`: Resolve `"myself"` to the user's primary/default connected email account address.

#### Module 3: Natural Language Search Query Sanitization & Stemming (Fixes Failures 1, 2, 4, 5)
- In `_extract_mail_search_params()`:
  - When `date_from`/`date_to` or `unread_only` consumes the query intent, do not set natural language leftovers as literal `params["query"]`.
  - Strip conversational filler (`"unread"`, `"emails"`, `"find"`, `"show me"`, `"mail"`, `"received"`).
- In `_matches_filters()`:
  - Implement basic word-stemming / token matching so `"internships"` matches `"internship"`.
  - Search across all message tokens, not strict single-substring match.

#### Module 4: Reverse Chronological Sorting & Body Retrieval (Fixes Failures 3, 6)
- In `MailAutomation.search_mail()`:
  - Sort all search results by `date received` descending before applying `[:limit]`.
- In `_summarize_emails()`:
  - If an email snippet is short, invoke `get_message(id)` to retrieve the full body before constructing the summarization prompt.

#### Module 5: Goal Query Intent Bridge (Fixes Failure 7)
- Add intent rule in `_analyze_intent` / `command_from_intent`:
  - Queries like *"Is there anything I need to respond to?"* or *"What do I need to reply to?"* route to `TaskCommand.READ_MAIL` with an analysis flag, fetching recent unread messages and evaluating required actions.

#### Module 6: Resilient Rate-Limit Handling with Backoff (Fixes Failure 6)
- In `_handle_gemini_error()`:
  - Replace 180s hard circuit breaker with exponential backoff (e.g., 2s, 5s, 10s retry).
  - Cap cooldown to 15–30 seconds maximum instead of 180 seconds.
  - Implement a clean local extractive summary fallback when the model is unavailable.

---

## 8. REAL-WORLD VERIFICATION SCENARIOS

| Test Scenario | Input Query | Target Autonomous Behavior |
|---|---|---|
| **TS-01** | *"Do I have any emails from Apple?"* | Queries mailbox across accounts; returns Apple emails if present, without 50-message storage-order cutoffs. |
| **TS-02** | *"Find emails about internships."* | Token/stem matching matches "internship", "intern", "internships". |
| **TS-03** | *"Show me the latest email from Google."* | Returns the single most recent email by verified date timestamp. |
| **TS-04** | *"Find emails I received last week."* | Applies date filters (start of last week to end of last week); query keyword is NOT set to "I received last week". |
| **TS-05** | *"Find unread emails."* | Applies `unread_only=True`; query keyword is empty; returns actual unread messages. |
| **TS-06** | *"Summarize the latest email from IBM."* | Fetches full email body; attempts summarization; gracefully recovers if 429 occurs. |
| **TS-07** | *"Is there anything I need to respond to?"* | Fetches recent inbox messages and analyzes action items instead of answering as chat trivia. |
| **TS-08** | *"Draft an email to Rahul asking about internship opportunities."* | Autonomously composes professional draft body regarding internship opportunities; presents approval card. |
| **TS-09** | *"Write a mail to myself requesting leave tomorrow."* | Resolves "myself" to user's connected email address; drafts leave request. |

---

## 9. CONCLUSION

The behavioral failures observed during live testing are directly traceable to specific source-code patterns: **suppressed autonomy ("Command ≠ Content"), query pollution from broken regexes, absence of date ranking, lack of self-identity resolution, snippet-only summarization, and a 3-minute 429 lockout**.

The proposed remediation plan restores genuine agent intelligence while respecting all existing safety gates, MCP bridges, and architecture boundaries.

**Report Status:** COMPLETE & READY FOR IMPLEMENTATION APPROVAL.
