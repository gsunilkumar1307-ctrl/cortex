# Cortex Agent — Task 4: Verified Finder Inspection Report

## Executive Summary

Task 4 implements and empirically verifies the Finder inspection workflow in Cortex Agent. The implementation enables Cortex to resolve the user's actual Downloads directory, activate and navigate Finder using supported macOS integrations, retrieve real filenames via read-only filesystem inspection, define and state deterministic ordering honestly, distinguish between filesystem directory entries and UI-visible items, and guarantee zero filesystem modifications.

All 52 automated tests across Tasks 1, 2, 3, and 4 pass, the desktop frontend builds cleanly, and the workflow has been verified against a live macOS session.

---

## 1. Reproduced Failure and Root Cause

### Reproduction Workflow
User prompt:
```text
"Open Finder, navigate to Downloads and show me the first five visible filenames. Do not modify anything."
```

### Pre-Fix Observed Behavior
- **Intent Misrouting:** `command_from_intent()` classified the prompt as `TaskCommand.OPEN_APP` rather than `TaskCommand.SEARCH_FILES`.
- **Parameter Truncation:** `_extract_params()` extracted `appName: "Finder"` and discarded `"navigate to Downloads and show me the first five visible filenames. Do not modify anything."`.
- **Execution Failure:** Cortex executed `open_app("Finder")` which merely brought Finder to the front and returned `"Opened Finder."`. It did not navigate to `~/Downloads`, did not inspect any filenames, and ignored the user's explicit request.

### Root Cause
1. **Compound Command Gap in `contracts.py`:** The file listing keyword matching only recognized exact phrases like `"open finder and list"`, `"list files in"`, and `"show files in"`. Phrases containing compound instructions such as `"Open Finder, navigate to Downloads and show me the first five visible filenames"` were not covered, causing the parser to fall through to `if text.startswith("open "): return TaskCommand.OPEN_APP`.
2. **Missing Finder Navigation & Window Verification in `device_actions.py`:** `_search_files` only performed an ad-hoc filesystem walk sorted by modification time (`mtime`), never activated or navigated Finder to the target folder, did not verify Finder window contents, and did not support deterministic alphabetical ordering or limits.
3. **No Distinction Between Filesystem Entries vs UI Items:** `_search_files` did not distinguish read-only directory enumeration from visually confirmed Finder items, nor did it declare the sorting methodology used.

---

## 2. Files Changed & Implementation Behavior

### 1. `backend/core/contracts.py`
- Expanded `command_from_intent` with robust regex patterns matching compound Finder navigation and inspection requests (e.g., `open finder... navigate to... show... filenames`, `navigate to... and show filenames`, `show me first N visible filenames in...`).
- Added multilingual / code-switched phrases for Kannada (`ಫೈಂಡರ್ ತೆರೆದು ಡೌನ್‌ಲೋಡ್ಸ್‌ನಲ್ಲಿ ಮೊದಲ ಐದು ಫೈಲ್‌ಗಳನ್ನು ತೋರಿಸು`) and Hindi (`Finder खोलें और Downloads में पहली पाँच फाइलें दिखाएं`).

### 2. `backend/capabilities/device_actions.py`
- **Path Resolution:** Resolves target directory using `Path.home() / "Downloads"` dynamically without hardcoded usernames.
- **Path Traversal Security:** Calls `_is_safe_path()` to block directory traversal (`..`) and sensitive system files (`/etc/passwd`, `.ssh`, etc.).
- **macOS Finder Navigation:** Activates Finder and navigates to the POSIX folder via AppleScript (`tell application "Finder" to open (POSIX file "<path>" as alias)`), with fallback to `open -a Finder <path>`.
- **Honest Partial-Failure Separation:** Finder activation/navigation failures are handled separately from filesystem listing failures; if Finder cannot be opened, filesystem listing still succeeds with an honest status notification.
- **Finder Window Verification:** On macOS, inspects the front Finder window via AppleScript to cross-reference items in Finder's visual interface.
- **Deterministic Ordering:** Sorts directory entries alphabetically (case-insensitive, ascending) and explicitly states the ordering in the response.
- **Accurate Counting & No Fabrication:** Respects the requested limit (`limit=5`). If fewer than 5 files exist (or if the directory is empty), displays only available files without fabricating entries.
- **Strict Read-Only Guarantee:** Verifies that no files are created, renamed, moved, deleted, or opened during inspection.

### 3. `backend/agent/orchestrator.py`
- **Sequence Protection:** Updated `_split_sequence()` to prevent compound Finder navigation and inspection commands from being split into isolated fragments.
- **Parameter Extraction:** Extracted target directory (`Downloads`), requested limit (`5`), `open_finder=True`, deterministic alphabetical sort, and read-only flags.
- **Context Preservation:** Persisted `self.last_file_search_result` to enable contextual follow-ups.

---

## 3. Test Suite Verification

### Focused & Regression Test Results
Run command:
```bash
python3 -m pytest tests/test_task1_core_execution_repair.py tests/test_task2_screen_observation.py tests/test_task3_safari_research.py tests/test_task4_finder_inspection.py
```

Output:
```text
======================= 52 passed, 5 warnings in 39.44s ========================
- tests/test_task1_core_execution_repair.py: 11 passed
- tests/test_task2_screen_observation.py: 10 passed
- tests/test_task3_safari_research.py: 17 passed
- tests/test_task4_finder_inspection.py: 14 passed
```

### Coverage Breakdown of `test_task4_finder_inspection.py`
| Test ID | Test Description | Result |
| :--- | :--- | :--- |
| `test_01` | Correct Downloads path resolution using `Path.home()` | **PASS** |
| `test_02` | Directory containing >5 entries displays exactly first 5 | **PASS** |
| `test_03` | Directory containing <5 entries displays available items without fabrication | **PASS** |
| `test_04` | Empty directory reports 0 files and honest empty state | **PASS** |
| `test_05` | Missing directory handled with `DirectoryNotFound` error | **PASS** |
| `test_06` | Permission denied handled with `PermissionDenied` error | **PASS** |
| `test_07` | Non-ASCII and multilingual filenames (`ದಾಖಲೆ_2026.pdf`, `रिपोर्ट_final.docx`, `résumé.pdf`) | **PASS** |
| `test_08` | Stable, explicitly defined ordering (case-insensitive alphabetical) | **PASS** |
| `test_09` | Finder activation failure handled separately from filesystem listing | **PASS** |
| `test_10` | Honest distinction between filesystem directory entries and UI-visible items | **PASS** |
| `test_11` | Strict read-only verification (no files created, modified, renamed, or deleted) | **PASS** |
| `test_12` | Path traversal security protection (`../../etc`) | **PASS** |
| `test_13` | Kannada and Hindi multilingual/code-switched Finder queries | **PASS** |
| `test_14` | Live macOS Finder acceptance workflow | **PASS** |

### Desktop Production Build
Run command:
```bash
npm run build --prefix apps/desktop
```

Output:
```text
vite v5.4.21 building for production...
✓ 1575 modules transformed.
dist/index.html                   1.10 kB │ gzip:  0.55 kB
dist/assets/index-B7oLT-sY.css   31.80 kB │ gzip:  6.44 kB
dist/assets/index-B-gvxTOZ.js   214.86 kB │ gzip: 65.08 kB
✓ built in 871ms
```

---

## 4. Live macOS Acceptance Evidence

### Command Executed
```text
"Open Finder, navigate to Downloads and show me the first five visible filenames. Do not modify anything."
```

### Live System Output
```markdown
### Finder Inspection: Downloads

• **Finder Status:** Activated and navigated to `/Users/gsunilkumar/Downloads`.
• **Inspection Type:** Directory entries (read-only filesystem listing).
• **Ordering:** Alphabetical (case-insensitive, ascending).
• **Items displayed:** First 5 of 24 entries.

1. `2071614.jpg`
2. `Antigravity IDE.dmg`
3. `Antigravity.dmg`
4. `Cline_0.0.43_universal.dmg`
5. `Cortex Elite Prd Trd Master Document (1).pdf`

• **Finder Window Verification:** Confirmed matching front Finder window items via macOS Finder AppleScript.
• **Filesystem Status:** Verified read-only inspection. No files were created, modified, renamed, or deleted.
```

### Independent Empirical Verification
1. **Finder Window Activation:** Finder was observed opening and navigating to `/Users/gsunilkumar/Downloads`.
2. **Directory Content Match:** All 5 filenames exist on disk in `/Users/gsunilkumar/Downloads` and match the case-insensitive alphabetical sorting.
3. **Finder UI Cross-Check:** Querying AppleScript `tell application "Finder" to get name of every item of front Finder window` confirmed that the items in the active window matched the filesystem listing.
4. **Zero Filesystem Modifications:** Verified via file metadata and directory listings before and after execution; no files were created, modified, renamed, or deleted.

---

## 5. Remaining Limitations
- **Visual Sort Customizations:** In Finder, users can configure arbitrary visual sort modes (e.g., sort by Date Added, Size, Kind, or Tags) or icon arrangement grids. The primary listing uses deterministic alphabetical order from the filesystem API and clearly notes this ordering.
- **Headless / Sandbox Environments:** In headless Linux or CI environments without a graphical macOS display server, Finder activation is marked as `Navigation failed or unavailable`, while read-only filesystem listing proceeds normally.
