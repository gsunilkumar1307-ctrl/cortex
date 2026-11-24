# CORTEX AGENT — PHASE P3.4 ARCHITECTURE AUDIT
## Universal Site-Agnostic Playwright Browser Intelligence & Interaction Engine

**Date:** November 17, 2026  
**Status:** **AUDIT COMPLETE — REMEDIATION PLAN APPROVED**  
**Component:** Playwright MCP Integration (`@playwright/mcp@0.0.85`), `backend/mcp/playwright_adapter.py`, `backend/agent/planner.py`, `backend/agent/orchestrator.py`, `backend/mcp/website_resolver.py`

---

## 1. EXECUTIVE SUMMARY & OBJECTIVE

Phase P3.4 transforms Cortex's browser automation capability from a hardcoded set of website-specific patterns into a **universal, site-agnostic browser intelligence and interaction engine**.

Cortex must be capable of navigating, inspecting, searching, interacting with forms, playing media, downloading files, and handling authentication on **unfamiliar, previously unconfigured websites** by dynamically inspecting the live accessibility tree and DOM controls exposed by official `@playwright/mcp@0.0.85`.

---

## 2. DEFECT INVESTIGATION & ROOT CAUSE ANALYSIS

### Defect A: Amazon-Specific Selector Leakage on YouTube
- **Reproduction Case:** User prompt: `"Open YouTube and search tere naam tuu"`
- **Observed Error:** `input[aria-label*='Search Amazon'] does not match any elements.`
- **Code Audit & Actual Root Causes:**
  1. **Hardcoded Search Locators Dictionary:** In `backend/mcp/website_resolver.py`, lines 97–129 defined a static `SEARCH_LOCATORS` dictionary with hardcoded CSS selectors for a few named platforms (`amazon`, `flipkart`, `wikipedia`, `github`, `youtube`, `reddit`).
  2. **Substring Match Inversion Bug:** In `backend/mcp/website_resolver.py:194`:
     ```python
     for k, locs in self.SEARCH_LOCATORS.items():
         if k in norm_name or norm_name in k:
             return list(locs)
     ```
     When `site_name` was empty (`""`) or unpopulated, `"" in "amazon"` evaluated to `True`. Because `"amazon"` was the first key in the dictionary, `get_search_locators` returned `SEARCH_LOCATORS["amazon"]`:
     - `input#twotabsearchtextbox`
     - `input[name='field-keywords']`
     - `input[aria-label*='Search Amazon']`
  3. **Blind Loop Without Current-Page Inspection:** In `backend/mcp/playwright_adapter.py:452–459`, `browser_type` sequentially tried each locator without first capturing or checking the live accessibility snapshot of the current page. When all Amazon selectors failed on YouTube, `last_err` captured `input[aria-label*='Search Amazon'] does not match any elements.` and failed the task.

### Defect B: Incomplete Multi-Step Execution on YouTube Playback
- **Reproduction Case:** User prompt: `"Open YouTube and play believer"`
- **Observed Response:** `"YouTube is open."` (Navigation only; playback and search never performed).
- **Code Audit & Actual Root Causes:**
  1. **Intent Parsing Blindness to Media Verbs:** In `backend/agent/orchestrator.py` (`_extract_open_url_params`), the regex for compound browser actions only checked for `search (for) | find | look for`:
     `r"^(?:open|go\s+to|visit)\s+([a-zA-Z0-9_\-\.]+)[,\s]+(?:and\s+)?(?:search|find|look\s+for)(.+)$"`
     Verbs like `play`, `watch`, `listen to`, `view`, `open result`, `fill`, and `download` were not recognized as browser interaction intents.
  2. **Greedy Substring Match in Website Resolver:** In `backend/mcp/website_resolver.py:178`:
     `if key == clean or clean in key or key in clean:`
     `clean` was `"youtube and play believer"`. Because `"youtube" in clean` was `True`, `resolve_website` returned `url = "https://www.youtube.com"` and dropped `"and play believer"`.
  3. **Discarding the Objective:** `_extract_open_url_params` set `browser_intent = "OPEN_WEBSITE"` with `query = None`.
  4. **Premature Task Termination:** `_execute_playwright_browser` hit line 5976:
     `if browser_intent == "OPEN_WEBSITE" or (not query and not params.get("is_comparison")):`
     It immediately set `task.status = TaskStatus.COMPLETED` and responded `"YouTube is open."`.
  5. **Lack of Dynamic Multi-Step Workflow Engine:** Cortex lacked an automated execution sequence to:
     - Open the site
     - Discover the search field dynamically
     - Type query and submit
     - Observe search results
     - Pick the best-matching result
     - Click/open the video
     - Verify actual playback (inspect video element, playing state, time progress, or pause button)

---

## 3. COMPONENT-BY-COMPONENT AUDIT FINDINGS

| Component | Current State | Defect / Limitation | Required P3.4 Architecture |
| :--- | :--- | :--- | :--- |
| `website_resolver.py` | Contains hardcoded `SEARCH_LOCATORS` and `CANONICAL_SERVICES`. | Substring matching causes false selector leakage; hardcoded list fails on unfamiliar sites. | Eliminate `SEARCH_LOCATORS`. Make domain resolution universal with safe domain synthesis (`https://www.{name}.com`) and DNS verification. |
| `playwright_adapter.py` | Hardcodes GitHub button clicks, hardcoded fallbacks, loops over static CSS selectors. | Does not inspect current page accessibility tree before deciding where to type or click. | Integrate `PageInspector` to dynamically classify inputs, searchboxes, buttons, links from accessibility snapshot `[ref=...]`. |
| `planner.py` | Emits fixed 3-step plan (`navigate -> type -> snapshot`) with `target="search"`. | Assumes generic target string `"search"`; has no concept of video playback, form filling, or auth inspection. | Generate semantic action sequences: `navigate` -> `discover_search` -> `type_and_submit` -> `inspect_results` -> `open_result` -> `verify_state`. |
| `orchestrator.py` | Big `if/elif` cascade checking `if "amazon" in site: ... elif "flipkart" in site: ... elif "wikipedia" ...`. | Hardcoded website names and mocked results; stops at "is open" for verbs like "play". | Replace domain `if/elif` branches with universal outcome verifier based on observed snapshot evidence. |
| `playwright_policy.py` | Enforces URL safety, tool prohibitions (`browser_run_code_unsafe`), and consequential actions. | Strong and compliant. | Keep intact. Ensure all new interactions honor approval gates and URL safety boundaries. |

---

## 4. ARCHITECTURE-PRESERVING IMPLEMENTATION PLAN

### Module 1: Universal Page Intelligence (`backend/mcp/page_inspector.py`)
Create a dedicated `PageInspector` that parses Playwright MCP accessibility snapshots (`browser_snapshot` output):
- Parses tree lines, extracting `role`, `accessible_name`, `value`, `ref` (`[ref=...]`), `disabled`, `expanded`, and hierarchy context.
- Classifies elements into semantic categories:
  - `searchboxes` (role `searchbox`, role `textbox` with search-related name/placeholder)
  - `textboxes` (general inputs, forms)
  - `buttons` (search buttons, submit buttons, play buttons, navigation buttons)
  - `links` (result links, navigation links, download links)
  - `media_controls` (play, pause, volume, video players)
  - `forms` (input groups, submission buttons)
- Discovers best candidate dynamically using semantic scoring without hardcoded site selectors.

### Module 2: Universal Search & Interaction Engine (`backend/mcp/universal_browser.py`)
A site-agnostic browser interaction coordinator integrating with `PlaywrightMCPAdapter`:
1. **Dynamic Search Discovery:**
   - Captures snapshot.
   - Finds search input via `PageInspector` (preferring `role="searchbox"`, then `name="Search..."`, placeholder, etc.).
   - Interacts with element using discovered `ref` or accessible selector.
   - Submits query via keyboard Enter or adjacent search button.
   - Waits for navigation/DOM change.
2. **Dynamic Result Selection & Navigation:**
   - Inspects search results from the fresh snapshot.
   - Matches candidate links/items against the user's objective query using fuzzy string similarity.
   - Clicks target result via `browser_click(target=ref)`.
3. **Media Playback & State Verification:**
   - On media/video requests, navigates to the result, inspects page for media player elements, verify playback state (playing, progress, or presence of pause control).
   - If ambiguous, asks user for clarification.
4. **Adaptive Locator Recovery:**
   - If an interaction fails, captures fresh snapshot, re-evaluates page state, rediscovers candidate, and retries safely once.

### Module 3: Orchestrator & Planner Generalization
- Remove domain-specific `if/elif` cascades in `orchestrator.py` (`amazon`, `flipkart`, `github`, `wikipedia`, `aws`).
- Enhance compound intent parsing in `orchestrator.py` and `contracts.py` to recognize multi-step verbs:
  - `play <song/video>`
  - `watch <video>`
  - `search for <query> and open <result>`
  - `find <query> and download`
  - `sign in / log in`
  - `fill out <form>`
- Format universal truthful responses based on observable snapshot evidence.

### Module 4: Verification & Regression
- Retain all existing P0, P1, P2, P3, P3.2, and P3.3 test suites.
- Author dedicated acceptance test suite `scripts/verify_p3_4_universal_browser.py` and unit test suite `tests/test_p3_4_universal_browser.py` testing familiar and unfamiliar sites.
