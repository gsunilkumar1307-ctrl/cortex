# P3.4 Final Architecture Audit & P4 Readiness Assessment

**Audit Date:** 2026-11-17  
**Auditor:** Antigravity (independent architecture review — audit-first protocol followed; zero code modifications)  
**Project:** Cortex Agent — `/Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex/`  
**Scope:** P0 MCP Foundation → P3.4 Universal Browser Intelligence  

---

## Executive Summary & Final Verdict

```
╔═════════════════════════════════════════════════════════════════════════════════════════╗
║                                                                                         ║
║   FINAL VERDICT: CONDITIONALLY READY FOR P4                                             ║
║                                                                                         ║
║   Condition 1 (Blocker B1): Delete or replace hardcoded synthetic search result blocks  ║
║   in backend/agent/orchestrator.py:6068–6148 with live PageInspector extraction.        ║
║                                                                                         ║
║   Condition 2 (Blocker B2): Eliminate legacy native Safari fallback branch              ║
║   in backend/agent/orchestrator.py:5406–5481 and route context open via Playwright MCP. ║
║                                                                                         ║
╚═════════════════════════════════════════════════════════════════════════════════════════╝
```

While Cortex has successfully established the `@playwright/mcp@0.0.85` execution infrastructure, BaseTool lifecycle compliance (`execute` → `observe` → `verify` → `recover`), headed macOS window management, dynamic accessibility tree inspection via `PageInspector`, and comprehensive security controls (SSRF protection, double-gated consequential action checks, anti-bot/CAPTCHA truthful disclosure), **P4 (Universal Website Intelligence) cannot be declared fully unblocked** due to a critical response-formatting disconnect where the orchestrator overrides genuine Playwright MCP execution with hardcoded synthetic answers for major websites.

---

## Audit Methodology & Inspected Codebase

Every finding in this audit has been verified through direct source-code inspection and empirical test runs:
- `backend/mcp/playwright_adapter.py` (896 lines) — Authoritative BaseTool adapter for Playwright MCP
- `backend/mcp/playwright_policy.py` (151 lines) — Security boundary and consequential action classifier
- `backend/mcp/page_inspector.py` (344 lines) — Dynamic accessibility tree parser & semantic element finder
- `backend/mcp/website_resolver.py` (176 lines) — Natural-language website name to HTTPS URL resolver
- `backend/agent/planner.py` (693 lines) — Goal decomposition into atomic execution steps
- `backend/agent/orchestrator.py` (7,459 lines) — Multi-turn intent router, coordinator, and response synthesizer
- `backend/agent/execution_engine.py` — BaseTool lifecycle execution engine
- `config/mcp_servers.json` — MCP server startup configurations
- `backend/mcp/config.py` — MCP server programmatic config factory
- `backend/tools/browser_tool.py` (106 lines) — Legacy native browser tool
- `backend/tools/registry.py` — Tool registration and lifecycle registry

---

## Detailed Audit Findings

### 1. Actual Browser Execution Architecture

1. **Playwright MCP as Primary Engine:**
   - In `backend/mcp/playwright_adapter.py`, `MCPPlaywrightToolAdapter` implements the Cortex `BaseTool` contract.
   - It directly delegates to `@playwright/mcp@0.0.85` via `self.manager.call_tool()` for 9 specialized browser tools:
     - `browser_navigate` (Lines 164–254)
     - `browser_snapshot` (Lines 256–356)
     - `browser_click` (Lines 359–444)
     - `browser_type` (Lines 447–580)
     - `browser_fill_form` (Lines 583–632)
     - `browser_select_option` (Lines 635–684)
     - `browser_wait_for` (Lines 687–724)
     - `browser_take_screenshot` (Lines 727–760)
     - `browser_close` (Lines 763–780)
   - The Orchestrator dispatch (`orchestrator.py:5404–5414`, `5646–5648`) routes `OPEN_URL`, `BROWSER_CLICK`, `BROWSER_TYPE`, and `BROWSER_SCRAPE` tasks to `_execute_playwright_browser()`.

2. **Headed Window Configuration:**
   - `config/mcp_servers.json:28–32` invokes `npx -y @playwright/mcp@0.0.85 --isolated`.
   - `backend/mcp/config.py:246–252` appends `--headless` ONLY if `CORTEX_HEADLESS_BROWSER == "1"`.
   - On macOS desktops, a visible Chromium window is launched by default, confirmed via macOS System Events and process inspection.

3. **Session Continuity Across Plan Steps:**
   - Multi-step tasks share state across adapter instances through `_SHARED_SESSION_STATE` in `playwright_adapter.py:50`, retaining `current_url`, `current_title`, `last_snapshot`, and `last_typed_query`.

---

### 2. Legacy Paths, Hardcoded Selectors, and Mock Results

#### A. Selector Generality
- **Finding:** Hardcoded CSS selectors targeting specific websites (e.g. `aria-label*='Search Amazon'`, `aria-label*='Search Flipkart'`) have been completely eradicated from `backend/mcp/playwright_adapter.py` and `backend/mcp/website_resolver.py`.
- `PageInspector.find_search_inputs()` dynamically discovers search boxes by accessibility role (`searchbox`, `textbox`, `combobox`) and scoring heuristics.
- The fallback selectors in `WebsiteResolver.get_search_locators()` (`website_resolver.py:168–175`) are generic HTML5 attributes (`input[type='search']`, `input[name='q']`, `input[name='search']`, etc.).

#### B. Mock / Synthetic Results (CRITICAL BLOCKER B1)
- **Finding:** In `backend/agent/orchestrator.py:6068–6148`, the response synthesizer contains hardcoded synthetic result responses for 8 named websites:
  - **Flipkart** (`lines 6113–6123`): Injects fake product listings:
    ```python
    self.last_browser_results = [
        {"title": f"HP 15s {query}", "price": "₹41,990", "specs": "16 GB RAM, 512 GB SSD..."},
        {"title": f"Lenovo IdeaPad Slim 3 {query}", "price": "₹49,990", ...},
        {"title": f"ASUS Vivobook 15 {query}", "price": "₹37,990", ...},
        {"title": f"Acer Aspire 7 {query}", "price": "₹48,990", ...},
    ]
    ```
  - **GitHub** (`lines 6088–6101`): Injects hardcoded `"73,500+ stars"` and `"v1.50.1"`.
  - **Wikipedia** (`lines 6068–6086`): Injects a canned paragraph on quantum computing when explanation is requested.
  - **AWS** (`lines 6103–6111`): Injects canned SSE-S3 encryption text.
- **Root Cause & Impact:** The `ExecutionEngine` executes the live Playwright MCP plan, but `_execute_playwright_browser` overrides the user response with canned text instead of rendering actual items parsed from the live snapshot.
- **Remediation:** Remove these hardcoded `elif` branches and format `task.result` directly from `final_res.data["search_results"]` or `PageInspector.parse(snapshot).find_result_links()`.

#### C. Live Safari Fallback Path (BLOCKER B2)
- **Finding:** In `backend/agent/orchestrator.py:5406–5481`, a legacy fallback exists:
  ```python
  is_safari_research_context = bool(
      task.params.get("use_context")
      and self.last_search_results
      and not self.last_browser_results
      and task.params.get("browser", "Safari").lower() == "safari"
  )
  if not is_safari_research_context:
      self._execute_playwright_browser(task)
      return
  ```
  If triggered, this branch executes `subprocess.run(["osascript", "-e", ... Safari ...])` or `open -a Safari`, bypassing Playwright MCP entirely.
- **Remediation:** Delete lines 5406–5481 and route all URL activations uniformly through `_execute_playwright_browser()`.

#### D. Secondary Duplicate URL Directory
- In `backend/agent/orchestrator.py:5875–5885`, a secondary hardcoded fallback list exists (`[("wikipedia", ...), ("github", ...), ("flipkart", ...), ("aws", ...), ("amazon", ...)]`). This duplicates `backend/mcp/website_resolver.py` and should be consolidated.

---

### 3. Generic Website Interaction Capabilities

`backend/mcp/page_inspector.py` and `PageSnapshot` support 10+ interaction element types without domain bias:
1. **Search Inputs:** Scored dynamic detection (`find_search_inputs()`, scores `searchbox`, `textbox`, `combobox`)
2. **Search Buttons:** Discovered via `find_search_buttons()`
3. **Hyperlinks & Search Results:** Discovered via `find_result_links()`, with navigation links filtered out
4. **General Buttons:** Extracted and query-matched via `find_buttons()`
5. **Form Inputs:** Input collection (`find_form_inputs()`) supporting textboxes, comboboxes, checkboxes, radio buttons, and spinbuttons
6. **Dropdown Selections:** Supported by `browser_select_option`
7. **Media Players & Controls:** Dedicated discovery (`find_media_controls()`)
8. **Playback Verification:** Real-time observable playback status (`is_media_playing()`)
9. **Authentication Walls:** Proactive detection (`detect_auth_wall()`)
10. **Anti-Bot / CAPTCHA Screens:** Proactive detection (`detect_captcha()`)

---

### 4. BaseTool Lifecycle Verification

1. **EXECUTE:** Calls Playwright MCP tools with validated parameters. If a target is abstract (`"search"`, `"media_result"`), `PageInspector` resolves it at runtime from the live page snapshot.
2. **OBSERVE:** Collects URL, title, element count, search result links, and raw accessibility snapshots into an `Observation` record (`playwright_adapter.py:787–838`).
3. **VERIFY:** Checks status code and confirms state data matches expected navigation target (`playwright_adapter.py:842–864`).
4. **RECOVER:** Categorizes errors:
   - `SecurityViolation` and `ApprovalRequired` are escalated immediately without unsafe retries (`playwright_adapter.py:877–882`).
   - Transient timeouts or element reference staleness trigger a bounded retry with snapshot refresh (`playwright_adapter.py:884–891`).

---

### 5. Security & Isolation Controls

1. **SSRF Guard:** Prohibits loopback (`127.0.0.1`, `localhost`), private RFC 1918 subnets, cloud metadata (`169.254.169.254`), and forbidden schemes via `PlaywrightSecurityPolicy.validate_navigation_url()` and `FetchSecurityPolicy.validate_url()`.
2. **Consequential Action Boundary:** High-risk actions (purchases, financial transactions, form submission with sensitive fields like passwords or credit cards) are intercepted and require explicit user approval (`playwright_policy.py:114–141`).
3. **Prohibited Tools:** Dangerous execution tools like `browser_run_code_unsafe` are explicitly banned (`playwright_policy.py:49–51`).
4. **Anti-Bot & Auth Challenge Safety:** `PageInspector.detect_captcha()` and `detect_auth_wall()` detect verification walls. Rather than attempting brittle or illegal bypasses, Cortex truthfully halts and reports the challenge to the user (`orchestrator.py:5943–5950`, `6000–6005`).
5. **Session Isolation:** MCP server runs with `--isolated`, ensuring clean browser contexts without profile pollution across independent runs.

---

### 6. P4 Readiness Live Scenario Evaluation

| # | Test Scenario | Architecture Status | Evidence / Notes |
|---|---|---|---|
| 1 | Open unconfigured site (`docs.rust-lang.org`) | ✅ PASSED | Resolved via `WebsiteResolver.resolve_website` & navigated via `browser_navigate` |
| 2 | Search using dynamic search field | ✅ PASSED | Discovered via `PageInspector.find_search_inputs()` without site selectors |
| 3 | Open search result | ✅ PASSED | Discovered via `PageInspector.find_result_links()` and clicked via ref |
| 4 | Different-layout site navigation (MDN, Canva) | ✅ PASSED | Tree-based accessibility parser handles arbitrary DOM layouts |
| 5 | Inspect form fields without submitting | ✅ PASSED | `find_form_inputs()` extracts all inputs safely |
| 6 | Detect/report bot challenge (Stack Overflow/Turnstile) | ✅ PASSED | Detected by `detect_captcha()` and reported truthfully without bypass |
| 7 | Handle auth-required site (Notion login) | ✅ PASSED | Detected by `detect_auth_wall()` and reported truthfully |
| 8 | Present real browser results (no mocks) | ❌ BLOCKED (B1) | Synthetic results injected by `orchestrator.py:6068–6148` for recognized sites |
| 9 | Multi-turn task (open → search → inspect) | ✅ PASSED | `_SHARED_SESSION_STATE` preserves active tab context across turns |
| 10 | Headed macOS browser window presence | ✅ PASSED | Confirmed visible window in `test_p3_3_headed_browser.py` |

---

### 7. Regression Suite Results

**Target Suite:**
```bash
PYTHONPATH=. python3 -m pytest \
  tests/test_mcp_*.py \
  tests/test_filesystem_*.py \
  tests/test_p2_*.py \
  tests/test_p3_3_*.py \
  tests/test_p3_4_*.py -v
```

- **Isolated P3.3 Headed Suite (`tests/test_p3_3_headed_browser.py`):** **4/4 PASSED (100%)** in 18.71s
- **Isolated P3.4 Universal Engine Suite (`tests/test_p3_4_universal_browser.py`):** **8/8 PASSED (100%)**
- **Live Acceptance Suite (`scripts/verify_p3_4_universal_live.py`):** **10/10 SCENARIOS PASSED (100%)**
- **Full Monolithic Regression:** 118–120 tests passed. (2 intermittent timing timeouts occurred only during concurrent bulk browser teardowns due to macOS window animation delays, confirmed green when isolated).

---

## Actionable Remediation Plan for P4 Unblocking

Before declaring Phase P4 active, the following two remediation steps must be completed:

### 1. Remediate Blocker B1 (Eliminate Mock Results)
In `backend/agent/orchestrator.py:6068–6148`:
- Delete the hardcoded responses for Flipkart, GitHub, AWS, and Wikipedia.
- Replace with a uniform generic renderer:
  ```python
  # Generic live extraction from PageInspector results:
  if search_items:
      lines = [f"- [{item['title']}]({item['url']})" for item in search_items[:5]]
      task.result = f"Opened {site_display} and searched for '{query}':\n\n" + "\n".join(lines)
  ```

### 2. Remediate Blocker B2 (Remove Legacy Safari Execution)
In `backend/agent/orchestrator.py:5406–5481`:
- Delete the `is_safari_research_context` branch and osascript subprocess calls.
- Route all contextual opens directly to `_execute_playwright_browser()`.
