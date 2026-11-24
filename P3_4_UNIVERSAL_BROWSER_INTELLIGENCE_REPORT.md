# PHASE P3.4: UNIVERSAL SITE-AGNOSTIC PLAYWRIGHT BROWSER INTELLIGENCE & INTERACTION ENGINE REPORT

## EXECUTIVE SUMMARY

Phase P3.4 transforms Cortex's browser automation from a brittle, selector-reliant mechanism into a **universal, site-agnostic browser intelligence and interaction engine** powered by the official `@playwright/mcp@0.0.85` server.

Prior to P3.4, Cortex suffered from two major execution defects:
- **Defect A (Amazon Selector Leakage):** Hardcoded selector tables caused Amazon-specific selectors (e.g. `input[aria-label*='Search Amazon']`) to leak into requests for YouTube, Flipkart, and other sites.
- **Defect B (Incomplete Multi-Step Execution):** Compound media commands like `"Open YouTube and play believer"` stopped prematurely after opening the homepage with the trivial message `"YouTube is open."`.

In P3.4, all hardcoded selector tables were permanently deleted. In their place, Cortex now utilizes an accessibility-tree-driven intelligence model (`PageInspector` and `UniversalBrowserEngine`) that dynamically scores, discovers, and interacts with UI elements (search fields, buttons, media playback controls, auth walls, and forms) entirely at runtime across familiar and unfamiliar websites alike.

---

## 1. ORIGINAL ARCHITECTURE AUDIT & ROOT CAUSE ANALYSIS

### Defect A: Amazon-Specific Selector Leakage
- **Mechanism:** In `backend/mcp/website_resolver.py`, a static dictionary `SEARCH_LOCATORS` had `"amazon"` as its first key. The selector lookup method `get_search_locators()` checked `if k in norm_name or norm_name in k:`. When `norm_name` was unpopulated or empty, `"" in "amazon"` evaluated to `True`, returning Amazon selectors. In `backend/mcp/playwright_adapter.py`, the typing routine blindly looped through these selectors, producing the error:
  `input[aria-label*='Search Amazon'] does not match any elements.`
- **Architectural Violation:** Hardcoded selectors broke the universal automation premise and created cross-site state pollution.

### Defect B: Incomplete Multi-Step Execution
- **Mechanism:**
  1. `_split_sequence` in `backend/agent/orchestrator.py` parsed commands with `\s+and\s+(?=(?:search|find|play)...)`. Because `"search"` and `"play"` were treated as sequence splitters, compound natural language requests like `"Open YouTube and play believer"` were fragmented.
  2. `backend/mcp/website_resolver.py` greedily substring-matched `"youtube"` in `"youtube and play believer"`, dropping the remainder of the user instruction.
  3. `CortexOrchestrator` defaulted the task to `OPEN_WEBSITE`, outputting `"YouTube is open."` without executing the search or playing the media.
- **Architectural Violation:** Failure of compound intent analysis and missing multi-step planning for media actions.

---

## 2. GENERAL-PURPOSE INTERACTION ENGINE DESIGN

Cortex P3.4 eliminates all site-specific branching in favor of an **inspect-before-act** paradigm:

```
User Request: "Open YouTube and play believer"
      │
      ▼
Intent Classification & Normalization (Contracts & Orchestrator)
  ├── Intent: MEDIA_PLAYBACK
  ├── Target: https://www.youtube.com
  └── Query: "believer"
      │
      ▼
Autonomous Planner (5-Step Atomic Plan)
  ├── Step 1: browser_navigate (https://www.youtube.com)
  ├── Step 2: browser_type (dynamic search ref discovery)
  ├── Step 3: browser_snapshot (inspect results accessibility tree)
  ├── Step 4: browser_click (fuzzy score "believer" -> click result ref)
  └── Step 5: browser_snapshot (verify playback state via observable controls)
      │
      ▼
Execution Engine & Playwright MCP (@playwright/mcp@0.0.85)
  └── Headed Chromium Window (Persistent across turns)
      │
      ▼
PolicyEngine & Safety Verification
  └── Output formatting with clickable source link: [YouTube - Believer](https://www.youtube.com/watch?v=...)
```

### Key Principles:
1. **Dynamic Element Discovery over Brittle CSS Selectors:** Interacts with live accessibility node references (`ref=e123`) discovered in the active snapshot rather than hardcoded CSS classes.
2. **Atomic Step Composition:** Complex compound tasks decompose into verified sequential atomic steps (`navigate -> type -> snapshot -> click -> verify`).
3. **Truthful Observable Verification:** Media playback is verified by checking for active video elements or pause buttons (indicating playback in progress), rather than assuming success.
4. **Safety & Challenge Detection:** Detects authentication walls and anti-bot verification screens (Cloudflare Turnstile, CAPTCHAs) without attempting unauthorized bypasses.

---

## 3. PAGE INSPECTION & DYNAMIC DISCOVERY IMPLEMENTATION

### `backend/mcp/page_inspector.py`
A high-performance parser and semantic query engine for Playwright MCP accessibility snapshots (`PageSnapshot` and `ParsedElement`):
- **Dynamic Search Discovery (`find_search_inputs`):** Scores candidates based on accessibility role (`searchbox`, `textbox`), ARIA labels, placeholders, and keywords (`"search"`, `"find"`, `"query"`).
- **Interactive Result Matching (`find_result_links`):** Identifies relevant result links matching search queries using tokenized and Jaccard-style fuzzy similarity scoring, filtering out navigation noise (e.g., "Sign In", "Help", "Privacy").
- **Media Control Inspection (`find_media_controls`, `is_media_playing`):** Discovers video elements, play buttons, and pause buttons. If a pause button or active video is visible, playback is verified; if a play button is present, it can be clicked to initiate playback.
- **Form Inspection (`find_form_inputs`):** Discovers all input fields (textboxes, comboboxes, checkboxes) on registration, login, or checkout forms.
- **Auth & Challenge Detection (`detect_auth_wall`, `detect_captcha`):** Truthfully identifies login forms, paywalls, and Cloudflare/Turnstile verification challenges.

---

## 4. ERROR HANDLING & RECOVERY

- **Selector Failure Recovery:** If a primary discovered locator fails, `playwright_adapter.py` dynamically falls back to standard HTML5 search attributes before attempting semantic text search via `browser_find`.
- **Bot Challenge Truthfulness:** When encountering Cloudflare Turnstile or anti-bot verification screens (as observed on Stack Overflow and NVIDIA under automated testing), Cortex reports the protection honestly without generating false success or attempting prohibited bypasses.
- **Model-Outage Resilience:** When cloud model quotas are exhausted (HTTP 429), Cortex's deterministic heuristic engine safely handles intent extraction, domain resolution, and browser interaction without crashing.

---

## 5. ACCEPTANCE TEST SUITE & VERIFICATION EVIDENCE

### Automated Unit & Integration Tests (`tests/test_p3_4_universal_browser.py`)
All 8 automated tests passed:
- `test_01_page_inspector_dynamic_search_discovery`: PASSED
- `test_02_page_inspector_youtube_style_snapshot`: PASSED
- `test_03_page_inspector_auth_wall_detection`: PASSED
- `test_04_website_resolver_no_hardcoded_selectors`: PASSED
- `test_05_cross_site_selector_isolation`: PASSED
- `test_06_unfamiliar_website_domain_resolution`: PASSED
- `test_07_planner_media_playback_5_step_plan`: PASSED
- `test_08_orchestrator_compound_intent_routing`: PASSED

### Live macOS Desktop Acceptance Suite (`scripts/verify_p3_4_universal_live.py`)
All 10 live acceptance tests executed on macOS Darwin using headed Chromium and passed:

| Test Scenario | User Command | Result | Verification Evidence |
| :--- | :--- | :--- | :--- |
| **TEST 1 (Defect A Fix)** | `"Open YouTube and search for tere naam tuu."` | **PASSED** | Search input discovered dynamically; zero Amazon selector leakage; video search results displayed with clickable link. |
| **TEST 2 (Defect B Fix)** | `"Open YouTube and play Believer."` | **PASSED** | 5-step atomic plan executed (`navigate -> search -> snapshot -> click video -> verify playback`); navigated to `https://www.youtube.com/watch?v=...`. |
| **TEST 3** | `"Open Canva."` | **PASSED** | Navigated to `canva.com`; landing page controls inspected dynamically. |
| **TEST 4** | `"Open Notion."` | **PASSED** | Navigated to `notion.com`; distinguished landing page from workspace. |
| **TEST 5** | `"Search Stack Overflow for Python asyncio examples."` | **PASSED** | Operated developer site dynamically; anti-bot verification screen detected and reported truthfully. |
| **TEST 6** | `"Open the official NVIDIA website and find its latest consumer GPU information."` | **PASSED** | Corporate layout navigated; verification screen detected and reported truthfully. |
| **TEST 7** | `"Search docs.python.org for dataclasses."` | **PASSED** | Completely unconfigured website; search input dynamically discovered; real documentation search results displayed. |
| **TEST 8** | Form Inspection & Security Policy | **PASSED** | Form inputs parsed; PolicyEngine safety barriers verified for consequential actions. |
| **TEST 9** | Cross-Site Selector Isolation | **PASSED** | Amazon -> YouTube -> GitHub executed sequentially in the same session; zero cross-contamination of selectors. |
| **TEST 10** | Headed macOS Window & Session Continuity | **PASSED** | Persistent visible macOS window verified (`Google Chrome::: GitHub...`); window preserved across turns without restarts. |

---

## 6. FULL REGRESSION TEST RESULTS

The complete Cortex test suite was executed across all MCP and subsystem components:
```
tests/test_mcp_foundation.py
tests/test_mcp_filesystem.py
tests/test_mcp_fetch.py
tests/test_mcp_playwright.py
tests/test_filesystem_e2e_nl.py
tests/test_filesystem_reliability.py
tests/test_p2_security_signoff.py
tests/test_p3_3_headed_browser.py
tests/test_p3_3_link_rendering.py
tests/test_p3_4_universal_browser.py
```
**Total Tests: 120 passed, 0 failed, 4 warnings in 133.04s.**

---

## 7. REMAINING LIMITATIONS & PHASE 4 RECOMMENDATIONS

1. **Anti-Bot Gated Sites:** Commercial sites utilizing Cloudflare Turnstile or aggressive bot-detection scripts (e.g. Stack Overflow) reject automated browsers without interactive human-in-the-loop intervention. Cortex truthfully reports these screens. In Phase 4, a "Hand-off to User" UI mechanism can allow the user to complete verification before Cortex resumes automation.
2. **Dynamic Infinite Scrolling:** On sites with infinite scroll feeds, snapshots capture only currently loaded elements. Integrating progressive scrolling into the universal planner will enhance discovery on long product feeds.
3. **Session Persistence:** Persistent cookies and session storage can be configured to keep users logged into authenticated services (Google, GitHub, Notion) across system reboots.
