# CORTEX AGENT — FILESYSTEM MCP: END-TO-END NATURAL LANGUAGE EXECUTION REMEDIATION REPORT

**Document ID:** CORTEX-DOC-MCP-P1-REMEDIATION-01  
**Version:** 1.0.0  
**Date:** November 16, 2026  
**Status:** APPROVED  
**Verdict:** `COMPLETE — ALL FILESYSTEM ACCEPTANCE SCENARIOS PASS`

---

## 1. EXECUTIVE SUMMARY

An end-to-end remediation of Cortex's natural language filesystem execution pipeline has been successfully designed, implemented, and verified. 

Prior to this remediation, Cortex failed to perform standard filesystem operations requested via ordinary natural-language commands (such as `"Create a new folder named CortexDemo on my Desktop"`, `"Create example.txt on my Desktop containing..."`, or multi-turn slot filling). Instead, Cortex frequently fell back to low-confidence conversational responses, triggered generic questionnaires that discarded user parameters across turns, or gave generic terminal commands rather than delegating to its integrated Filesystem Model Context Protocol (MCP) server (`@modelcontextprotocol/server-filesystem@2.3.0`). Furthermore, the initial path jail strictly confined operations to `~/Documents/CortexWorkspace`, preventing legitimate user requests targeting standard desktop locations (`~/Desktop`, `~/Documents`, `~/Downloads`).

### Summary of Accomplishments:
1. **Preserved Core Architectural Invariants:** No new execution engines were introduced; the canonical `BaseTool` lifecycle (`execute` → `observe` → `verify` → `recover`), `ExecutionEngine`, `AutonomousPlanner`, `PolicyEngine`, native macOS application automation (`DeviceAutomation`), and native fallback `FileTool` were strictly preserved.
2. **Multi-Root Sandbox Confinement:** `FilesystemPathJail` and `config/mcp_servers.json` were upgraded to safely support standard user work roots (`~/Desktop`, `~/Documents`, `~/Downloads`, and `~/Documents/CortexWorkspace`) while enforcing canonical path validation, symlink escape rejection, protected directory blocking (`.git`, `node_modules`, `.ssh`), and sensitive credential shielding (`.env`, `.session_secret`, private keys).
3. **Dynamic Root Authorization:** Implemented conversational authorization for paths outside pre-approved roots. When a user approves an unapproved directory, Cortex grants the jail root, dynamically updates the MCP server configuration arguments, restarts the Node.js MCP server process, and executes the pending task.
4. **End-to-End Orchestration & Multi-Turn Retention:** Enhanced `CortexOrchestrator` and `TaskCommand` contract mappings to recognize folder creation, file creation, reading, searching, editing, and application launch with file paths. Multi-turn slot filling now persists conversational parameters without loss across turns.
5. **Cryptographic Approval & Anti-Replay Integrity:** Consequential mutations (such as overwriting existing files or moving files) strictly require and verify single-use SHA-256 approval hashes. Replays and parameter mutations post-approval are rejected.
6. **Empirical Verification:** 100% of acceptance scenarios passed.
   - `tests/test_filesystem_e2e_nl.py`: **13/13 passed**
   - `tests/test_mcp_filesystem.py` & `tests/test_mcp_foundation.py`: **34/34 passed**
   - Orchestrator regression tests: **27/27 passed**

---

## 2. ROOT CAUSE ANALYSIS

| Issue | Manifestation in Previous Implementation | Technical Root Cause | Remediation Applied |
|---|---|---|---|
| **1. Intent Classifier Gaps** | User command `"Create new folder name it xyz"` gave a low-confidence LLM answer. `"New file creation"` began generic questions. | `command_from_intent` lacked regex patterns for directory creation, file creation with content, file reading, and searching. Missing `TaskCommand.CREATE_DIRECTORY`. | Added `TaskCommand.CREATE_DIRECTORY`, `EDIT_FILE`, `APPEND_FILE`, `COPY_FILE`, `LIST_DIRECTORY`, and `GET_FILE_INFO` to contracts; added high-priority deterministic regex classification in `command_from_intent`. |
| **2. Confinement Boundary Mismatch** | Commands targeting `~/Desktop` failed path validation or failed inside the Node MCP process. | `FilesystemPathJail` and `mcp_servers.json` hardcoded only `~/Documents/CortexWorkspace`. | Extended `DEFAULT_AUTHORIZED_ROOTS` to `Desktop`, `Documents`, `Downloads`, and `CortexWorkspace`. Updated MCP server launch arguments to allow all authorized roots. |
| **3. Conversational State Loss** | Asking for "notes.txt" -> "Desktop" -> "Hello Cortex" lost prior slots or failed on greeting collisions. | Multi-turn slot filling for filesystem was missing from orchestrator; greetings detector (`_is_unrelated_turn`) triggered on `"Hello Cortex."` body content. | Implemented dedicated `_handle_pending_filesystem` state machine with slot persistence; exempted active filesystem pending flows from unrelated turn interception. |
| **4. MCP Child Process Out-of-Sync on Dynamic Grants** | Granting an unauthorized directory in Python jail still caused Node MCP process to fail with `MCPExecutionError`. | `@modelcontextprotocol/server-filesystem` checks arguments supplied at process spawn. Granting access in Python did not inform the Node subprocess. | In `confirm_grant_root`, Cortex appends the new path to server `config.args`, restarts the MCP server via `MCPServerManager.restart_server("filesystem")`, and synchronizes tools. |
| **5. Search Result Clutter** | Natural language file search returned 70+ results from `node_modules` or `.git` instead of relevant user documents. | `search_files` traversed all subdirectories without exclusion or ranking. | Excluded `node_modules`, `.git`, `.venv` during rglob search; added exact-phrase match ranking. |
| **6. Application Launch Missing Target File** | "Open example.txt in TextEdit" launched TextEdit with an empty window. | `DeviceAutomation._open_app` executed `open -a <app>` without passing the canonical target file path. | Added `file_path` argument to `DeviceAutomation.execute("OPEN_APP", ...)` and invoked `open -a <app> <file_path>` on macOS. |

---

## 3. ARCHITECTURE & LIFECYCLE PRESERVATION

```
                        User Natural Language Request
                                     │
                                     ▼
                      ┌─────────────────────────────┐
                      │    Language & Safety Gate   │
                      │  (LanguageCode, SafetyEngine)│
                      └──────────────┬──────────────┘
                                     │
                                     ▼
                      ┌─────────────────────────────┐
                      │    CortexOrchestrator       │
                      │ (Intent, Slots, PendingAct) │
                      └──────────────┬──────────────┘
                                     │
                  ┌──────────────────┴──────────────────┐
                  │                                     │
                  ▼                                     ▼
     ┌────────────────────────┐            ┌────────────────────────┐
     │  AutonomousPlanner     │            │ Multi-Turn Slot Filler │
     │ (Routes to mcp_* tools)│            │ (Prompts for missing)  │
     └────────────┬───────────┘            └────────────────────────┘
                  │
                  ▼
     ┌────────────────────────┐
     │  PolicyEngine          │◄─── Single-use SHA-256 Approval Hash
     │  (Risk, Approvals)     │     (Anti-replay & anti-tampering)
     └────────────┬───────────┘
                  │
                  ▼
     ┌────────────────────────┐
     │  ExecutionEngine       │
     │  (BaseTool Lifecycle)  │
     └────────────┬───────────┘
                  │
                  ▼
     ┌────────────────────────────────────────────────────────┐
     │            MCPFilesystemToolAdapter                    │
     │  ┌──────────────────────────────────────────────────┐  │
     │  │ 1. Arguments & Canonical Path Validation         │  │
     │  │    (FilesystemPathJail: Desktop, Documents, etc.)│  │
     │  │ 2. Single-use Cryptographic Approval Check       │  │
     │  │    (FilesystemPermissionPolicy)                  │  │
     │  │ 3. Dispatch to Official MCP Filesystem Server    │  │
     │  │    (@modelcontextprotocol/server-filesystem)     │  │
     │  │ 4. Verification (Hash match, directory check)    │  │
     │  │ 5. Safe Recovery (Abort on mutation failures)    │  │
     │  └──────────────────────────────────────────────────┘  │
     └────────────────────────────────────────────────────────┘
```

### Key Architectural Invariants Enforced:
1. **Four-Phase Tool Lifecycle:** Every filesystem tool call strictly executes `execute()` → `observe()` → `verify()` → `recover()`.
2. **Single-Use Cryptographic Approvals:** All consequential mutations (overwriting existing files, file moves) compute a SHA-256 hash across `(tool_name, path, destination, content, edits)`. Hashes cannot be reused or replayed; parameter mutations invalidate the token.
3. **No Retries on Failed Consequential Writes:** `MCPFilesystemToolAdapter.recover` aborts immediately if a write, edit, or move fails, preventing accidental partial corruption or duplicate writes.
4. **Native Tool Fallback:** If MCP tools are unavailable or uninitialized, `AutonomousPlanner` seamlessly routes file operations to the native `FileTool`.

---

## 4. MULTI-DIRECTORY CONFINEMENT & SECURITY BOUNDARIES

The filesystem sandbox is strictly enforced by `FilesystemPathJail`:

### A. Pre-Approved Authorized Roots:
- `~/Desktop`
- `~/Documents`
- `~/Downloads`
- `~/Documents/CortexWorkspace`

### B. Prohibited System & Sensitive Paths (Non-Grantable):
- System roots: `/System`, `/Library`, `/etc`, `/usr`, `/bin`, `/sbin`, `/var`, `/Volumes`, `/dev`, `/proc`, `/sys`.
- User home root (`~`) directly (prevents recursive unconstrained home directory access).
- Restricted directories: `.ssh`, `.aws`, `.azure`, `.config/gcloud`, `.git`, `node_modules`.
- Shielded credentials: `.session_secret`, `.memory_key`, `.env`, `.env.*`, `id_rsa`, `id_ed25519`, `authorized_keys`, `known_hosts`, `cortex-memory.key`, shell histories.

### C. Traversal & Symlink Escapes:
- Path traversal sequences (e.g. `../`, `..\\`) are resolved and rejected if the resolved path falls outside authorized roots.
- Symbolic links are resolved to their underlying targets via `os.path.realpath`. Any symlink whose real target resides outside authorized roots is rejected immediately with `MCPSecurityError`.

---

## 5. ACCEPTANCE SCENARIOS (A THROUGH J) VERIFICATION MATRIX

| Scenario | Test Identifier | Natural Language Command / Interaction | Expected Behavior | Verification Evidence | Status |
|---|---|---|---|---|---|
| **A** | `test_a_folder_creation_explicit_location` | `"Create a new folder named CortexDemo on my Desktop."` | Folder created at `~/Desktop/CortexDemo`. Positive verification. No questionnaire. | `folder.is_dir() == True`, response confirms folder creation at path. | **PASS** |
| **A (Default)** | `test_a_folder_creation_default_location` | `"Create new folder name it test_auto_xyz"` | Defaults safely to Desktop, creates folder, notifies user of default location. | `folder.is_dir() == True`, `params["default_location_used"] == True`. | **PASS** |
| **B** | `test_b_file_creation_with_content` | `"Create example.txt on my Desktop containing This is an example file."` | Correct file created with exact content on Desktop. SHA-256 match. No terminal instructions. | `target.read_text() == "This is an example file"`, verification method: `content_sha256_match`. | **PASS** |
| **C** | `test_c_multi_turn_file_creation` | Turn 1: `"Create a new file"`<br>Turn 2: `"notes.txt"`<br>Turn 3: `"Desktop"`<br>Turn 4: `"Hello Cortex."` | Maintains task state across 4 turns; prompts for missing slots; creates file with final content. | `target.read_text() == "Hello Cortex."`, pending action cleared, audit trail complete. | **PASS** |
| **D** | `test_d_empty_file_creation` | `"Create an empty file called empty.txt on Desktop."` | Valid 0-byte file created. Does not fail due to empty output. | `target.is_file() == True`, `target.stat().st_size == 0`. | **PASS** |
| **E** | `test_e_read_file` | `"Read example.txt from my Desktop."` | Resolves path, reads file contents via `mcp_read_file`, returns contents in response. | `"This is an example file" in res["message"]`, `task.status == TaskStatus.COMPLETED`. | **PASS** |
| **F** | `test_f_open_file_in_application` | `"Open example.txt from my Desktop in TextEdit."` | Invokes native application control (`open -a TextEdit <path>`). Passes canonical file path. | `task.command == TaskCommand.OPEN_APP`, `params["file_path"]` resolves to canonical path. | **PASS** |
| **G** | `test_g_search_and_ambiguity` | `"Find my project report."` (with `v1.txt` and `final.txt` on Desktop) | Searches authorized roots; presents candidates with numbers/bullets; asks user to choose. | Response lists both candidates, does not open arbitrary file, prompts user to clarify. | **PASS** |
| **H** | `test_h_overwrite_protection_and_approval` | Turn 1: `"Create example.txt on my Desktop containing Overwritten Value"`<br>Turn 2: `"yes"` | Turn 1: pauses for approval, disk content unmodified.<br>Turn 2: validates single-use SHA-256 approval token, overwrites file. | Pre-turn 2: content remains `"Initial"`; Post-turn 2: content becomes `"Overwritten Value"`. | **PASS** |
| **I** | `test_i_unauthorized_directory_prompt_and_grant` | Turn 1: `"Create a file in /tmp/cortex_unauthorized_test/target.txt containing AuthorizedData"`<br>Turn 2: `"yes"` | Turn 1: identifies unauthorized directory, prompts user to grant access.<br>Turn 2: dynamically grants root in jail & restarts MCP server with args, creates file. | Post-turn 2: `target.exists() == True`, content matches `"AuthorizedData"`. | **PASS** |
| **J (Regression)** | `test_j_regression_native_file_tool` | Fallback invocation of native `FileTool` | Native `FileTool` executes seamlessly with `BaseTool` lifecycle. | `res.ok == True`, written file matches content. | **PASS** |
| **J (Jail Guard)** | `test_j_path_jail_traversal_blocked` | Traversal attempt: `~/Desktop/../../../etc/passwd` | Path jail detects traversal escape and raises `MCPSecurityError`. | Raises `MCPSecurityError`, access rejected. | **PASS** |
| **J (Approvals)** | `test_j_consequential_approval_hash_enforcement` | Token reuse & parameter tampering verification | Replay of consumed token returns `ApprovalReplay`; tampered token returns `ApprovalMismatch`. | Validates `ApprovalReplay` on reuse; validates `ApprovalMismatch` on parameter alteration. | **PASS** |

---

## 6. EMPIRICAL TEST EXECUTION EVIDENCE

### 1. Natural Language End-to-End Acceptance Suite:
```
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
rootdir: /Users/gsunilkumar/Desktop/antigravity/Codex/2026-06-17/files-mentioned-by-the-user-cortex
collected 13 items

tests/test_filesystem_e2e_nl.py::test_a_folder_creation_explicit_location PASSED [  7%]
tests/test_filesystem_e2e_nl.py::test_a_folder_creation_default_location PASSED [ 15%]
tests/test_filesystem_e2e_nl.py::test_b_file_creation_with_content PASSED [ 23%]
tests/test_filesystem_e2e_nl.py::test_c_multi_turn_file_creation PASSED  [ 30%]
tests/test_filesystem_e2e_nl.py::test_d_empty_file_creation PASSED       [ 38%]
tests/test_filesystem_e2e_nl.py::test_e_read_file PASSED                 [ 46%]
tests/test_filesystem_e2e_nl.py::test_f_open_file_in_application PASSED  [ 53%]
tests/test_filesystem_e2e_nl.py::test_g_search_and_ambiguity PASSED      [ 61%]
tests/test_filesystem_e2e_nl.py::test_h_overwrite_protection_and_approval PASSED [ 69%]
tests/test_filesystem_e2e_nl.py::test_i_unauthorized_directory_prompt_and_grant PASSED [ 76%]
tests/test_filesystem_e2e_nl.py::test_j_regression_native_file_tool PASSED [ 84%]
tests/test_filesystem_e2e_nl.py::test_j_path_jail_traversal_blocked PASSED [ 92%]
tests/test_filesystem_e2e_nl.py::test_j_consequential_approval_hash_enforcement PASSED [100%]

======================= 13 passed, 4 warnings in 14.86s ========================
```

### 2. MCP Foundation & Filesystem Security Suites:
```
collected 34 items

tests/test_mcp_filesystem.py::test_filesystem_server_startup_and_tool_discovery PASSED [  2%]
tests/test_mcp_filesystem.py::test_registry_bridge_integration PASSED    [  5%]
tests/test_mcp_filesystem.py::test_filesystem_write_and_read_new_file PASSED [  8%]
tests/test_mcp_filesystem.py::test_filesystem_0_byte_empty_file_handling PASSED [ 11%]
tests/test_mcp_filesystem.py::test_filesystem_create_directory_and_list PASSED [ 14%]
tests/test_mcp_filesystem.py::test_filesystem_search_files_and_get_info PASSED [ 17%]
tests/test_mcp_filesystem.py::test_filesystem_move_file_with_approval PASSED [ 20%]
tests/test_mcp_filesystem.py::test_path_traversal_rejection PASSED       [ 23%]
tests/test_mcp_filesystem.py::test_protected_sensitive_files_rejection PASSED [ 26%]
tests/test_mcp_filesystem.py::test_symlink_escape_rejection PASSED       [ 29%]
tests/test_mcp_filesystem.py::test_overwrite_requires_approval PASSED    [ 32%]
tests/test_mcp_filesystem.py::test_stale_approval_and_replay_rejection PASSED [ 35%]
tests/test_mcp_filesystem.py::test_recovery_policy_prevents_mutation_retries PASSED [ 38%]
tests/test_mcp_filesystem.py::test_recovery_allows_safe_read_retries PASSED [ 41%]
tests/test_mcp_filesystem.py::test_timeout_enforcement PASSED            [ 44%]
tests/test_mcp_filesystem.py::test_unregistered_tool_invocation PASSED   [ 47%]
tests/test_mcp_foundation.py::test_mcp_server_startup PASSED             [ 50%]
tests/test_mcp_foundation.py::test_mcp_server_shutdown PASSED            [ 52%]
tests/test_mcp_foundation.py::test_mcp_session_initialization PASSED     [ 55%]
tests/test_mcp_foundation.py::test_mcp_tool_discovery PASSED             [ 58%]
tests/test_mcp_foundation.py::test_mcp_dynamic_registration PASSED       [ 61%]
tests/test_mcp_foundation.py::test_mcp_tool_invocation PASSED            [ 64%]
tests/test_mcp_foundation.py::test_mcp_invalid_arguments PASSED          [ 67%]
tests/test_mcp_foundation.py::test_mcp_invalid_responses PASSED          [ 70%]
tests/test_mcp_foundation.py::test_mcp_connection_failure PASSED         [ 73%]
tests/test_mcp_foundation.py::test_mcp_process_termination PASSED        [ 76%]
tests/test_mcp_foundation.py::test_mcp_timeout_handling PASSED           [ 79%]
tests/test_mcp_foundation.py::test_mcp_reconnection PASSED               [ 82%]
tests/test_mcp_foundation.py::test_mcp_duplicate_registration_prevention PASSED [ 85%]
tests/test_mcp_foundation.py::test_mcp_approval_enforcement PASSED       [ 88%]
tests/test_mcp_foundation.py::test_mcp_verification_failure PASSED       [ 91%]
tests/test_mcp_foundation.py::test_mcp_cancellation PASSED               [ 94%]
tests/test_mcp_foundation.py::test_mcp_recovery PASSED                   [ 97%]
tests/test_mcp_foundation.py::test_mcp_audit_logging_and_sanitization PASSED [100%]

======================= 34 passed, 4 warnings in 14.28s ========================
```

### 3. Orchestration & System Regression Suite:
```
tests/test_orchestrator.py ................. [17 passed]
tests/test_phase2_step1_unified_orchestration.py .......... [10 passed]

======================= 27 passed in 25.80s ========================
```

---

## 7. FINAL VERDICT

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                                FINAL VERDICT                                 ║
║                                                                              ║
║              COMPLETE — ALL FILESYSTEM ACCEPTANCE SCENARIOS PASS             ║
║                                                                              ║
║  - Scenarios A through J: 100% Verified and Passing (13/13 tests)            ║
║  - MCP Foundation & Filesystem Security Suites: 100% Passing (34/34 tests)   ║
║  - Orchestrator Core Regression Suite: 100% Passing (27/27 tests)            ║
║  - Zero Architectural Regressions; Full Approval & Sandbox Integrity Intact  ║
╚══════════════════════════════════════════════════════════════════════════════╝
```
