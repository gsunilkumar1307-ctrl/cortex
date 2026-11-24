# CORTEX AGENT — P3.4 FINAL BLOCKER REMEDIATION (B1 + B2) ACCEPTANCE REPORT

**Date:** November 17, 2026  
**Status:** **BOTH BLOCKERS RESOLVED**  
**Remediation Scope:** Blocker B1 (Removal of Synthetic Search Results) & Blocker B2 (Removal of Legacy Safari Fallback / Routing via Playwright MCP)

---

## 1. EXECUTIVE SUMMARY

In accordance with the findings in `docs/P3_4_FINAL_ARCHITECTURE_AUDIT.md`, a targeted remediation was performed on Cortex's browser automation and orchestration architecture. The two identified architectural blockers have been completely eliminated:

1. **Blocker B1 (Synthetic Search Results):** Completely removed hardcoded/synthetic search results and canned responses across Flipkart, GitHub, AWS, and Wikipedia from production code paths in `backend/agent/orchestrator.py`. Real live Playwright MCP accessibility tree observations and snapshot extractions are preserved, empty search results are reported honestly with zero fabrication, and test fixtures are maintained strictly within tests.
2. **Blocker B2 (Legacy Safari Fallback):** Completely removed the `is_safari_research_context` branch and legacy `subprocess.run(["open", "-a", "Safari", url])` execution paths. All browser research actions and contextual opens (e.g., "open that article", "open the second result") are routed through the headed Playwright MCP Chromium session. If Playwright MCP is unavailable, Cortex fails fast and truthfully without silent fallback to Safari, while non-browser native macOS desktop automation (Notes, Preview, Mail) remains fully preserved.

---

## 2. ROOT-CAUSE ANALYSIS

### 2.1 Blocker B1: Synthetic Search Results
- **Location:** `backend/agent/orchestrator.py:6068–6148`
- **Root Cause:** During earlier iterations of P3.2 and P3.3, hardcoded mock results were introduced in `backend/agent/orchestrator.py` under `_execute_playwright_browser` to satisfy specific test scenarios (e.g., Flipkart ASUS laptops with canned prices `₹37,990`, GitHub repository stars `★ 4,210`, AWS documentation paragraphs, and Wikipedia quantum computing text).
- **Architectural Hazard:** If Playwright MCP returned snapshot data or if a website changed structure, production code fell back or overwrote live results with hardcoded product listings and prices, violating Cortex's truthfulness mandate and risking stale data pollution across consecutive tasks.

### 2.2 Blocker B2: Legacy Safari Subprocess Fallback
- **Location:** `backend/agent/orchestrator.py:5406–5481`
- **Root Cause:** Under `TaskCommand.OPEN_URL`, a legacy branch `if is_safari_research_context:` checked for research keywords and executed `subprocess.run(["open", "-a", "Safari", url])` directly on macOS.
- **Architectural Hazard:** This circumvented Playwright MCP, broke headed browser session continuity, split user interaction between Safari and Chromium, bypassed MCP audit logging and verification hooks, and masked Playwright service failures by silently opening Safari instead of reporting an error.

---

## 3. EXACT CODE MODIFICATIONS

### 3.1 `backend/agent/orchestrator.py`

#### Blocker B1 Remediation
1. **Removed Synthetic Blocks:** Deleted all hardcoded website-specific response dictionaries and static strings for Flipkart, GitHub, AWS, and Wikipedia in `_execute_playwright_browser`.
2. **Site-Agnostic Live Result Extraction:** Replaced synthetic generation with generic extraction from `snapshot_data.get("search_results")`, adapter session data, or dynamic parsing via `PageInspector.find_result_links()`.
3. **Truthful Zero-Result Reporting:** When zero results are discovered, Cortex reports:
   ```text
   Opened <site> and searched for '<query>'. The page loaded successfully, but no matching search results were found.
   
   Source: [<title>](<url>)
   ```
4. **Session State Isolation:** Reset `self.last_browser_results = []` on every navigation/search task to prevent stale result leakage into subsequent queries.

#### Blocker B2 Remediation
1. **Eliminated Safari Execution Path:** Removed `is_safari_research_context`, `subprocess.run(["open", "-a", "Safari", url])`, and all Safari fallback logic from `_execute_open_url`.
2. **Unified Playwright MCP Routing:** All `TaskCommand.OPEN_URL` commands route unconditionally to `_execute_playwright_browser(task)`.
3. **Playwright Availability Guard (Fail-Fast):** Added proactive check in `_execute_playwright_browser` verifying Playwright MCP server status (`MCPServerStatus.CONNECTED`) or registry availability. If unavailable, sets `task.status = TaskStatus.FAILED` and `task.error = "Playwright MCP browser automation service is unavailable."` without falling back to native browsers.
4. **Contextual Article Domain Resolution:** Updated contextual follow-ups ("open that article", "open the second result") to resolve target URLs from `self.last_browser_results` or `self.last_search_results` and use `WebsiteResolver` dynamically rather than hardcoded domain dictionaries.
5. **Preserved Non-Browser Desktop Automation:** Left `DeviceAutomation` intact for `TaskCommand.OPEN_APP`, `CREATE_NOTE`, `OPEN_FILE`, etc., ensuring macOS system applications (Notes, Preview, Finder) operate without disruption.

### 3.2 Test Fixtures Relocation (`tests/test_mcp_playwright.py`)
- Per requirement 5 ("Keep website-specific test fixtures strictly inside tests"), updated the `mock_orch` test fixture in `tests/test_mcp_playwright.py` with mock `side_effect` handlers providing test-specific snapshot data for Scenarios A, B, C, and D, keeping production code 100% agnostic.

---

## 4. REGRESSION SUITES & TEST COVERAGE

Two new comprehensive regression test suites were created specifically to lock in B1 and B2 fixes:

### 4.1 `tests/test_p3_4_remediation_b1.py` (Blocker B1 Suite)
- `test_b1_01_real_browser_search_results_retained`: Proves genuine Playwright MCP search results are rendered in `task.result` without modification or canned prices.
- `test_b1_02_empty_browser_results_honestly_reported`: Proves zero-result queries report truthful absence of results instead of fabricating items.
- `test_b1_03_unknown_website_receives_no_fabricated_records`: Verifies unfamiliar domains do not generate synthetic placeholder listings.
- `test_b1_04_github_search_no_fabricated_stars_or_release`: Proves GitHub queries do not return pre-written star counts (`4,210`) or hardcoded release tags (`v2.4.1`).
- `test_b1_05_wikipedia_search_no_canned_quantum_paragraph`: Proves Wikipedia queries do not return the canned quantum computing paragraph.
- `test_b1_06_search_results_isolated_between_tasks`: Proves search results from Task 1 do not leak into Task 2.

### 4.2 `tests/test_p3_4_remediation_b1_b2.py` (Blocker B2 Suite)
- `test_b2_01_browser_navigation_uses_playwright_mcp_not_safari`: Proves navigation uses Playwright MCP and `subprocess.run` is never called with Safari.
- `test_b2_02_contextual_article_opening_uses_playwright_mcp`: Proves follow-up commands ("open that article") resolve active task URLs via Playwright MCP.
- `test_b2_03_native_apps_preserved_for_non_browser_tasks`: Proves non-browser apps (Notes, Preview) continue using native macOS automation.
- `test_b2_04_playwright_unavailable_honestly_reported`: Proves absence of Playwright MCP results in an explicit failure, NOT a silent fallback to Safari.
- `test_b2_05_browser_security_policies_remain_enforced`: Proves loopback, RFC1918, and file scheme restrictions remain enforced under Playwright MCP.

---

## 5. EMPIRICAL VERIFICATION OUTCOMES

All regression and integration test suites were executed in the repository workspace.

| Test Suite | Purpose | Tests Run | Passed | Failed |
| :--- | :--- | :---: | :---: | :---: |
| `tests/test_p3_4_remediation_b1.py` | B1 Synthetic Result Removal | 6 | 6 | 0 |
| `tests/test_p3_4_remediation_b1_b2.py` | B2 Safari Fallback Removal & MCP Routing | 5 | 5 | 0 |
| `tests/test_p3_4_universal_browser.py` | P3.4 Universal Site-Agnostic Engine | 8 | 8 | 0 |
| `tests/test_p3_3_headed_browser.py` | P3.3 Visible Headed Browser & Window Reuse | 4 | 4 | 0 |
| `tests/test_p3_3_link_rendering.py` | P3.3 Clickable Markdown Link Tokenization | 4 | 4 | 0 |
| `tests/test_mcp_playwright.py` | P3 Official Playwright MCP Core Lifecycle | 15 | 15 | 0 |
| `tests/test_mcp_fetch.py` | P2 Official Fetch MCP & SSRF Security | 20 | 20 | 0 |
| `tests/test_mcp_filesystem.py` | P1 Official Filesystem MCP | 16 | 16 | 0 |
| `tests/test_mcp_foundation.py` | P0 MCP Foundation & JSON-RPC Lifecycle | 18 | 18 | 0 |
| `tests/test_filesystem_e2e_nl.py` | P1.1 Filesystem Natural Language Actions | 13 | 13 | 0 |
| `tests/test_filesystem_reliability.py` | Filesystem Reliability & Document Readers | 10 | 10 | 0 |
| `tests/test_p2_security_signoff.py` | P2 SSRF, TOCTOU & Content Security | 12 | 12 | 0 |
| **TOTAL** | **Full System-Wide Regression Suite** | **131** | **131** | **0** |

---

## 6. FINAL VERIFICATION CHECKLIST

- [x] Zero synthetic or hardcoded search/product records in `backend/agent/orchestrator.py`.
- [x] Zero silent Safari browser fallback branches (`is_safari_research_context` eliminated).
- [x] All browser tasks unconditionally route via official `@playwright/mcp@0.0.85`.
- [x] Honest error reporting when Playwright MCP is unavailable.
- [x] Non-browser desktop tasks preserve native macOS automation.
- [x] 100% of the 131 unit, security, and integration regression tests pass cleanly.

---

## 7. FINAL VERDICT

```text
================================================================================
FINAL VERDICT: BOTH BLOCKERS RESOLVED
================================================================================
Cortex Agent has successfully eliminated Blocker B1 and Blocker B2.
All browser operations are site-agnostic, live-observed, and powered strictly by
Playwright MCP without synthetic data fabrication or legacy browser fallbacks.
The system is fully clean, verified, and ready for subsequent milestones.
================================================================================
```
