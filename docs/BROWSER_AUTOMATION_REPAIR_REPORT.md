# Cortex Agent — Critical P0 Web Automation & Conversational Routing Repair Report

## 1. Executive Summary

### The Reported Production Defect
When the user entered:
> **"Open Safari and search for latest update in AI."**

Cortex incorrectly responded with encyclopedia-style descriptions of Safari and iOS (from Wikipedia), failing to recognize the user's intent to operate Safari, search the web, and synthesize relevant AI developments.

### Status
- **Root Cause Identified & Fixed**: 
  1. `command_from_intent` in `backend/core/contracts.py` lacked support for compound browser automation commands matching `"open [browser] and search for [query]"`, `"launch [browser] and search for [query]"`, and informational `"find the latest/recent..."` requests.
  2. In `_extract_params` in `backend/agent/orchestrator.py`, the prefix stripping regex only checked for `"^(?:google|search the web for|search for|search|look up|research)\s+"`. For compound sentences like `"Open Safari and search for latest update in AI."`, this left the entire sentence intact as the search query.
  3. Wikipedia REST API fallback received `"Open Safari and search for latest update in AI."` as the title, resolving it to the Apple Safari browser page instead of AI updates.
  4. Missing `import urllib.parse` at top of `orchestrator.py` caused a runtime NameError when constructing Google search URLs for Safari.
- **Regression Suite**: **504 tests passing (0 failures)** (increased from 476).
- **Dedicated Test File**: [`tests/test_browser_automation_routing.py`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/tests/test_browser_automation_routing.py) with 28 targeted test cases.
- **Frontend Build**: Verified (`vite build` in `apps/desktop` succeeds in 686ms).

---

## 2. Root Cause Analysis & Live Trace

### Call Path Trace
```
User Message: "Open Safari and search for latest update in AI."
  ↓
CortexOrchestrator.chat(message)
  ↓
command_from_intent(message)  [backend/core/contracts.py]
  - Prior: Did not handle generic compound browser directives; fell through or misclassified.
  - Fix: Added compound browser regex pattern before generic OPEN_APP fallback:
    r"\b(?:open|launch|start)\s+(?:safari|chrome|firefox|edge|browser)\s+and\s+(?:search\s+(?:the\s+web\s+)?(?:for\s+)?|look\s+up\s+|research\s+|find\s+|google\s+)"
  ↓
_extract_params(TaskCommand.WEB_SEARCH, message)  [backend/agent/orchestrator.py]
  - Prior: Did not parse compound sentence clauses. `query` was left as `"Open Safari and search for latest update in AI."`.
  - Fix: Added `_compound_browser_re` extraction. `query` is cleanly isolated as `"latest update in AI"` and `browser` is stored as `"Safari"`.
  ↓
_execute(task)  [backend/agent/orchestrator.py:3182]
  - `task.command == TaskCommand.WEB_SEARCH`
  - `query = "latest update in AI"`
  - `browser = "Safari"`
  - If on macOS and not dry-run:
      Launches `subprocess.run(["open", "-a", "Safari", f"https://www.google.com/search?q={urllib.parse.quote(query)}"])`
  - Fetches web results for `"latest update in AI"` via `search_web()`
  - Synthesizes findings using LLM or structured multi-snippet summary
```

---

## 3. Implementation Details

### Files Modified

1. **[`backend/core/contracts.py`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/core/contracts.py)**:
   - Added regex matching for compound browser search triggers (`open/launch/start <browser> and search/research/find/look up <query>`).
   - Added regex matching for informational research requests (`find the latest/recent/new developments in <topic>`) distinguishing them from local file search.

2. **[`backend/agent/orchestrator.py`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/backend/agent/orchestrator.py)**:
   - Added top-level imports: `import urllib.parse` and `import subprocess`.
   - Updated `_extract_params` for `TaskCommand.WEB_SEARCH` to parse compound clauses and set both `query` and `browser`.
   - Updated `_execute` for `TaskCommand.WEB_SEARCH` to check explicit `browser` param rather than fuzzy substring search against `task.intent`.

3. **[`tests/test_browser_automation_routing.py`](file:///Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/tests/test_browser_automation_routing.py)**:
   - 28 automated tests covering:
     - Compound browser commands: Safari, Chrome, Firefox.
     - Query isolation (clean query without command verbs or browser names).
     - Browser isolation (standalone "Open Safari." retains `OPEN_APP`).
     - Orchestrator dry-run and live macOS Safari launching.
     - Contextual follow-up handling.

---

## 4. Verification & Test Execution Evidence

### Test Suite Execution
```bash
python3 -m pytest tests/test_browser_automation_routing.py -v
======================= 28 passed, 16 warnings in 54.68s =======================
```

```bash
python3 -m pytest tests/ -q
........................................................................ [100%]
504 passed, 21 warnings in 103.28s (0:01:43)
```

### Full Stack Desktop Application Build
```bash
npm run build --prefix apps/desktop
✓ built in 686ms
```
