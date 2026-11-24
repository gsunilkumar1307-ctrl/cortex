# CORTEX AGENT — PHASE P1.1 FILESYSTEM MCP SECURITY ACCEPTANCE AUDIT
**Strict Read-Only Security, Integrity & Confinement Audit**
**Date:** November 16, 2026  
**Status:** AUDIT COMPLETE  
**Target:** Phase P1 Filesystem MCP Integration  
**Policy:** STRICT AUDIT ONLY — ZERO CODE MODIFICATIONS  

---

## 1. Executive Verdict

$$\mathbf{P1\ CONDITIONALLY\ ACCEPTED\ —\ MINOR\ FIXES\ REQUIRED}$$

### Summary Assessment
A rigorous, read-only security and integration audit of the completed Phase P1 Filesystem MCP implementation was conducted across all core components, execution paths, boundary controls, approval mechanisms, and test suites.

The foundational security architecture is **robust, resilient, and multi-layered**:
- **Dual-Layer Confinement:** Both Cortex's Python execution boundary (`FilesystemPathJail`) and the underlying Node.js MCP server process (`@modelcontextprotocol/server-filesystem@2.3.0`) independently enforce workspace confinement. Bypassing the Python jail still results in server-level rejection of out-of-bounds paths and symlink escapes.
- **Cryptographic Approval:** Consequential operations (overwriting existing files, edits, moves/renames, copy collisions) strictly require single-use `approved_hash` tokens. Argument tampering (`ApprovalMismatch`) and token reuse (`ApprovalReplay`) are demonstrably rejected.
- **Empirical Verification:** The adapter does not rely on server claims; it performs direct on-disk verification (SHA-256 matching, file/dir existence, and valid 0-byte file handling).
- **Zero Regression:** All **34 MCP tests** (18 P0 foundation + 16 P1 filesystem) and all **126 baseline Cortex regression tests** pass cleanly (**126/126 PASSED**).

Two minor, non-blocking hygiene items were identified for remediation before proceeding to Phase P2:
1. **`roots/list` URI Argument Parsing:** In `backend/mcp/client.py`, the handler naively converts non-flag CLI arguments into `roots/list` URIs, which inadvertently exposes the npm package string (`file://@modelcontextprotocol/...`) as a root entry.
2. **Default Workspace Directory Pre-Creation:** If `config/mcp_servers.json` launches the server pointing to `~/Documents/CortexWorkspace` before `FilesystemPathJail` has instantiated, the Node.js server fails to start if the directory does not physically exist on disk.

---

## 2. Actual Architecture & Execution Path

The end-to-end execution path was audited across the Cortex stack:

```
[ Natural Language Request / Task Intent ]
                     │
                     ▼
             CortexOrchestrator
                     │
                     ▼
             AutonomousPlanner
                     │ Decomposes into PlanSteps with canonical tool names
                     ▼
              ExecutionEngine
                     │
                     ├─► ToolRegistry.get_instance("mcp__filesystem__write_file")
                     │    └─► Returns MCPFilesystemToolAdapter
                     │
                     ├─► PolicyEngine.evaluate(tool, inputs, context)
                     │    └─► Validates user policies, risk tier, action permissions
                     │
                     ▼
          MCPFilesystemToolAdapter.execute()
                     │
                     ├─► 1. Argument Extraction & Schema Validation
                     │       (validate_input_schema against declared MCP tool schema)
                     │
                     ├─► 2. FilesystemPathJail.validate_tool_arguments()
                     │       - Canonical path resolution against approved roots
                     │       - Rejects null-bytes, ../ traversals, symlink escapes
                     │       - Denies sensitive patterns (.ssh, .env, .session_secret, .git)
                     │
                     ├─► 3. FilesystemPermissionPolicy.validate_approval()
                     │       - Checks if action is consequential (e.g. overwrite existing file)
                     │       - Compares approved_hash against deterministic SHA-256 digest
                     │       - Enforces single-use token consumption (anti-replay)
                     │
                     ├─► 4. Pre-Execution Disk Snapshot
                     │       - Captures pre-existing file stat, size, and SHA-256
                     │
                     ├─► 5. MCPServerManager.call_tool()
                     │       - Dispatches JSON-RPC tools/call over stdio to child process
                     │       - Enforces call timeout and manages stdio locks
                     │
                     ▼
         @modelcontextprotocol/server-filesystem (Node.js)
                     │
                     ├─► Server-Side Boundary Validation (CLI allowed directories)
                     ├─► Physical OS Filesystem Mutation / Read
                     └─► Emits JSON-RPC Response over stdio
                     │
                     ▼
          MCPFilesystemToolAdapter.observe()
                     │
                     └─► Directly reads OS filesystem state (stat, size, SHA-256)
                     │
                     ▼
          MCPFilesystemToolAdapter.verify()
                     │
                     ├─► Validates physical side-effects on disk
                     ├─► Matches on-disk SHA-256 against written content
                     ├─► Validates 0-byte empty file reads
                     └─► Never trusts unverified server success claims
                     │
                     ▼
          ExecutionEngine / TaskStore
                     │
                     └─► Persists audit event, step state, observation, and cryptographic hash
```

---

## 3. Server-Side & Cortex-Side Confinement Findings

### 3.1 Server-Side Confinement (Node.js Subprocess)
- **Launch Command:** `npx -y @modelcontextprotocol/server-filesystem@2.3.0 <allowed-directory>`
- **Boundary Verification:** An adversarial test was conducted to bypass Cortex's Python jail entirely and send raw JSON-RPC requests directly to the Node.js process:
  - **Direct Out-of-Bounds Request (`/etc/passwd`):**
    - Result: `isError: True`
    - Server Message: `Access denied - path outside allowed directories: /etc/passwd not in /private/...`
  - **Direct Symlink Escape Request:**
    - A symlink pointing to an outside sensitive file was placed inside the allowed directory and requested directly.
    - Result: `isError: True`
    - Server Message: `Access denied - symlink target outside allowed directories: ... not in ...`
- **Confinement Verdict:** The server-side process independently enforces strict directory confinement and realpath symlink resolution.

### 3.2 Cortex-Side Confinement (`FilesystemPathJail`)
- **Execution Boundary Enforcement:** Path checking occurs in Python *before* arguments are transmitted to the child process.
- **Root Validation:**
  - Prohibits root filesystem `/` and `/private`.
  - Prohibits raw user home directory `~` (must be a dedicated subfolder).
  - Enforces `DEFAULT_WORKSPACE_ROOT = ~/Documents/CortexWorkspace`.
- **Sensitive Path Denials:**
  - Blocks all sensitive files (`.env*`, `.session_secret`, `.memory_key`, `id_rsa`, `authorized_keys`, `cortex-memory.key`, etc.) even when located inside the workspace.
  - Blocks all restricted directory structures (`.ssh`, `.aws`, `.azure`, `.git`, `node_modules`).

---

## 4. Adversarial Path Test Results

An empirical test battery was executed against the active implementation:

| Attack Vector | Test Description | Expected Behavior | Actual Observed Result | Status |
|---|---|---|---|---|
| `../` Traversal | `workspace/../../../etc/passwd` | Intercepted at Python boundary | `SecurityViolation: outside all approved workspace roots` | **SECURE** |
| Absolute Escape | `/etc/passwd` directly | Intercepted at Python boundary | `SecurityViolation: outside all approved workspace roots` | **SECURE** |
| Nested Symlink Escape | `workspace/sub1/sub2/leak -> outside_file` | Intercepted by realpath check | `SecurityViolation: outside all approved workspace roots` | **SECURE** |
| Case Variation in Denied File | `workspace/.ENV`, `workspace/.Env` | Lowercase normalization matches blocklist | `SecurityViolation: Access to sensitive file '.ENV' is strictly denied` | **SECURE** |
| Case Variation in Denied Dir | `workspace/.GIT/config`, `workspace/.SSH/id_rsa` | Lowercase path part checks | `SecurityViolation: Access to restricted directory '.GIT' is strictly denied` | **SECURE** |
| Multiple Allowed Roots | `[workspace_a, workspace_b]` | Both roots accessible, third root blocked | Both allowed roots permitted; external paths blocked | **SECURE** |
| Direct Symlink Bypass (TOCTOU) | Symlink created post-check sent to server | Server-side realpath check rejects | `Access denied - symlink target outside allowed directories` | **SECURE** |
| Server-Level Direct Escape | Send `/etc/passwd` over raw stdio | Server-side directory check rejects | `Access denied - path outside allowed directories` | **SECURE** |
| Hard Link Ingestion | External file hard-linked inside workspace | Handled as local inode | Inode resolves to workspace path; external access requires pre-existing local write access | **MONITORED** |

---

## 5. Approval & Replay Protection Findings

### 5.1 Operation Binding
The cryptographic approval token (`approved_hash`) is strictly bound to:
1. `tool_name` (e.g. `write_file`, `move_file`, `edit_file`).
2. Canonical `path` (or canonical `source` and `destination`).
3. Payload content digest ($\text{SHA-256}$ of text content or sorted JSON string of `edits`).

### 5.2 Tampering & Replay Tests
- **Argument Modification:** When approval was generated for file content `Clause 2`, but the execution input provided `Clause 3 - Tampered`:
  - Result: **Rejected** (`error="ApprovalMismatch"`).
  - Physical file on disk remained unmodified.
- **Replay Attack:** When a consumed approval token was re-submitted for the exact same operation:
  - Result: **Rejected** (`error="ApprovalReplay"`).
- **Missing Approval on Consequential Operation:** When `write_file` was invoked on an existing file without a token:
  - Result: **Rejected** (`error="ApprovalRequired"`).
- **Cross-Operation Cross-Over:** Approval generated for `write_file` cannot authorize `move_file` or `edit_file` because `tool_name` is prepended to the hash payload.

---

## 6. Tool Inventory & Capability Accuracy

### 6.1 Discovered Tools vs. Advertised Capabilities
The official `@modelcontextprotocol/server-filesystem@2.3.0` server exposes exactly 16 tools:
1. `read_file` (deprecated upstream in favor of `read_text_file`)
2. `read_text_file`
3. `read_media_file`
4. `read_multiple_files`
5. `write_file`
6. `append_file`
7. `edit_file`
8. `create_directory`
9. `list_directory`
10. `list_directory_with_sizes`
11. `directory_tree`
12. `move_file`
13. `copy_file`
14. `search_files`
15. `get_file_info`
16. `list_allowed_directories`

### 6.2 Key Inventory Findings
- **Deletion Support:** `@modelcontextprotocol/server-filesystem@2.3.0` **does not provide any file or directory deletion tool**. This is an upstream security choice by Anthropic/MCP maintainers. Cortex correctly classifies deletion as consequential in its policy rules, but does **not** falsely advertise deletion as an available MCP tool.
- **Policy Fail-Safe on Unlisted Tools:** `append_file` is not in the automatic tools whitelist and therefore correctly defaults to **Approval Required** (`is_approval_required() == True`).
- **Tool Annotations:** Annotations such as `readOnlyHint`, `idempotentHint`, and `destructiveHint` provided by the server are treated purely as advisory hints and are **never** used to override Cortex's authoritative `FilesystemPermissionPolicy`.

---

## 7. Verification & Recovery Findings

### 7.1 Verification Integrity
`MCPFilesystemToolAdapter.verify()` enforces positive empirical validation directly against the filesystem:
- **`write_file`:** Computes SHA-256 of the physical file on disk and verifies exact byte-for-byte equivalence with input content.
- **`move_file`:** Confirms destination file exists and confirms source file has ceased to exist.
- **`create_directory`:** Verifies directory exists and is a directory on disk.
- **0-Byte Empty Files:** If a file is 0 bytes on disk, `read_file` correctly validates the empty result rather than raising an `EmptyOutput` error.

### 7.2 Recovery & Anti-Retry Enforcement
- For all consequential / mutating operations, `adapter.recover()` returns:
  `{"can_retry": False, "strategy": "escalate"}`
- Blind automated retries of writes, edits, and moves are **strictly prohibited**, preventing accidental file clobbering or duplicate state mutations.
- Idempotent read operations allow up to 2 safe retries on transient transport failures.

---

## 8. Regression Comparison

### 8.1 Complete Test Suite Execution

1. **MCP Phase P1 Tests (`tests/test_mcp_filesystem.py`):**
   - Result: **16 / 16 PASSED** (11.89s)
2. **MCP Phase P0 Foundation Tests (`tests/test_mcp_foundation.py`):**
   - Result: **18 / 18 PASSED** (1.45s)
3. **Total MCP Tests:** **34 / 34 PASSED**

### 8.2 Full 126-Test Cortex Regression Baseline
The earlier 126-test baseline was re-executed across the full suite:
- `tests/test_contracts.py`
- `tests/test_safety.py`
- `tests/test_orchestrator.py`
- `tests/test_phase1_execution_foundation.py`
- `tests/test_circuit_breaker.py`
- `tests/test_command_content_separation.py`
- `tests/test_browser_automation_routing.py`
- `tests/test_macos_application_control.py`
- `tests/test_phase2_email_automation.py`
- `tests/test_phase2_step2_1_audit_and_recovery.py`
- `tests/test_memory.py`
- `tests/test_task4_finder_inspection.py`

**Result:** **126 / 126 PASSED** (1m 18s, 0 failures, 0 regressions).

*Explanation of Previous 89-Test Run:* During the initial P1 implementation check, a faster 89-test subset was executed. All 37 previously omitted tests have now been executed; **100% of the original 126-test baseline passes**.

---

## 9. Confirmed Vulnerabilities & Severity

| ID | Issue Description | Component | Severity | Exploitable |
|---|---|---|---|---|
| **VULN-P1-01** | `_handle_server_request` in `MCPClient` naively converts non-flag CLI arguments into `roots/list` URIs, causing package specifiers like `@modelcontextprotocol/server-filesystem@2.3.0` to be advertised as `file://@modelcontextprotocol/...`. | `backend/mcp/client.py` | **LOW** | No (Server ignores invalid URI; access is restricted by CLI arg) |
| **VULN-P1-02** | If `config/mcp_servers.json` is used directly before `FilesystemPathJail` creates `DEFAULT_WORKSPACE_ROOT`, the Node.js server exits immediately on startup because the workspace directory does not physically exist yet. | `backend/mcp/config.py` | **LOW (Operational)** | No (Fails closed / denial of startup) |
| **VULN-P1-03** | `list_directory_with_sizes` is not explicitly categorized in `AUTOMATIC_TOOLS`, causing a read-only tool to default to requiring approval. | `backend/mcp/filesystem_policy.py` | **INFORMATIONAL** | No (Fail-safe, slightly conservative) |

---

## 10. Exact Files & Functions Requiring Correction

1. **`backend/mcp/client.py`**:
   - Function: `_handle_server_request(self, req_id: Any, method: str, params: dict[str, Any])`
   - Lines: 270–282
2. **`backend/mcp/config.py`**:
   - Function: `validate_server_config` or server initialization hook
   - Lines: 170–185
3. **`backend/mcp/filesystem_policy.py`**:
   - Definition: `AUTOMATIC_TOOLS` set
   - Line: 26

---

## 11. Recommended Minimal Fixes (Without Implementing)

*(Per mission instructions, no code modifications have been made during this audit turn).*

### Fix 1: Filter `roots/list` in `backend/mcp/client.py`
Replace naive argument parsing with validation that only advertises genuine, existing directory paths:
```python
# Recommended correction for backend/mcp/client.py
if method == "roots/list":
    roots = []
    if self.process.config.args:
        for arg in self.process.config.args:
            if not str(arg).startswith("-") and not str(arg).startswith("@"):
                p = Path(str(arg)).expanduser().resolve()
                if p.exists() and p.is_dir():
                    roots.append({"uri": f"file://{p}", "name": p.name or "workspace"})
    if not roots:
        default_dir = Path.home() / "Documents" / "CortexWorkspace"
        default_dir.mkdir(parents=True, exist_ok=True)
        roots = [{"uri": f"file://{default_dir.resolve()}", "name": "workspace"}]
    await self._send_raw_response(req_id, result={"roots": roots})
```

### Fix 2: Auto-Create Default Workspace in `backend/mcp/config.py`
Ensure the target directory physically exists prior to spawning `npx`:
```python
# Recommended correction in backend/mcp/config.py
def get_filesystem_server_config(allowed_dir: str | Path | None = None, ...):
    if not allowed_dir:
        allowed_dir = Path.home() / "Documents" / "CortexWorkspace"
    p = Path(allowed_dir).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    ...
```

### Fix 3: Add `list_directory_with_sizes` to Automatic Tools
```python
# Recommended addition in backend/mcp/filesystem_policy.py
AUTOMATIC_TOOLS = {
    ...
    "list_directory_with_sizes",
}
```

---

## 12. Final Conclusion

Phase P1 Filesystem MCP integration fulfills all core security and functional requirements:
- Bounded path jail active.
- Server-side confinement verified.
- Consequential mutations gated by single-use cryptographic tokens.
- Dual-layer anti-escape verified under adversarial conditions.
- Zero regressions across all 126 baseline Cortex tests.

Upon applying the 3 minor hygiene adjustments recommended above, the system is fully prepared to proceed to **Phase P2: Playwright MCP Integration**.
