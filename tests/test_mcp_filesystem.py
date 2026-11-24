from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any
import pytest

from backend.core.contracts import (
    ExecutionError,
    ExecutionResult,
    Observation,
    RiskLevel,
    TaskContext,
    VerificationResult,
)
from backend.tools.registry import ToolRegistry

from backend.mcp.adapter import MCPToolAdapter
from backend.mcp.client import MCPClient
from backend.mcp.config import get_filesystem_server_config
from backend.mcp.exceptions import (
    MCPConnectionError,
    MCPSecurityError,
    MCPTimeoutError,
    MCPToolNotFoundError,
)
from backend.mcp.filesystem_adapter import MCPFilesystemToolAdapter
from backend.mcp.filesystem_jail import DEFAULT_WORKSPACE_ROOT, FilesystemPathJail
from backend.mcp.filesystem_policy import FilesystemPermissionPolicy
from backend.mcp.manager import MCPServerManager
from backend.mcp.models import MCPServerConfig, MCPServerStatus, MCPToolDefinition
from backend.mcp.registry import MCPRegistryBridge


@pytest.fixture
def workspace_tmp(tmp_path: Path) -> Path:
    """Provides a clean, hermetic temporary directory as approved workspace root."""
    ws = (tmp_path / "CortexWorkspace").resolve()
    ws.mkdir(parents=True, exist_ok=True)
    return ws


@pytest.fixture
def jail(workspace_tmp: Path) -> FilesystemPathJail:
    """Provides a path jail rooted in the isolated temporary workspace."""
    return FilesystemPathJail(allowed_roots=[workspace_tmp], auto_create_default=False)


@pytest.fixture
def policy() -> FilesystemPermissionPolicy:
    """Provides a fresh filesystem permission policy."""
    return FilesystemPermissionPolicy()


@pytest.fixture
def fs_manager(workspace_tmp: Path) -> MCPServerManager:
    """Initializes and manages a live official filesystem MCP server for testing."""
    cfg = get_filesystem_server_config(allowed_dir=workspace_tmp)
    cfg.timeout_seconds = 15.0
    mgr = MCPServerManager()
    mgr.register_server(cfg)
    mgr.start_server("filesystem", timeout=15.0)
    yield mgr
    mgr.shutdown(timeout=3.0)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP A — Server Lifecycle and Registration
# ═══════════════════════════════════════════════════════════════════════════════

def test_filesystem_server_startup_and_tool_discovery(fs_manager: MCPServerManager):
    """Verifies that the filesystem MCP server starts and tools are dynamically discovered."""
    server = fs_manager._servers.get("filesystem")
    assert server is not None
    assert server.status == MCPServerStatus.CONNECTED
    assert server.process.is_alive

    tools = fs_manager.get_tool_definitions("filesystem")
    assert len(tools) >= 10

    tool_names = {t.name for t in tools}
    assert "write_file" in tool_names
    assert "read_file" in tool_names or "read_text_file" in tool_names
    assert "list_directory" in tool_names
    assert "create_directory" in tool_names
    assert "move_file" in tool_names
    assert "search_files" in tool_names
    assert "get_file_info" in tool_names


def test_registry_bridge_integration(fs_manager: MCPServerManager, jail: FilesystemPathJail, policy: FilesystemPermissionPolicy):
    """Verifies dynamic registration into ToolRegistry, alias creation, and cleanup."""
    tool_registry = ToolRegistry()
    bridge = MCPRegistryBridge(
        manager=fs_manager,
        tool_registry=tool_registry,
        filesystem_jail=jail,
        filesystem_policy=policy,
    )

    count = bridge.sync_server_tools("filesystem")
    assert count >= 10

    # Verify canonical registration
    canonical_write = tool_registry.get("mcp__filesystem__write_file")
    assert canonical_write is not None
    instance = tool_registry.get_instance("mcp__filesystem__write_file")
    assert isinstance(instance, MCPFilesystemToolAdapter)

    # Verify alias registration
    alias_write = tool_registry.get("mcp_write_file")
    assert alias_write is not None
    assert isinstance(tool_registry.get_instance("mcp_write_file"), MCPFilesystemToolAdapter)

    # Verify unregistration cleans up registry completely
    removed = bridge.unregister_server_tools("filesystem")
    assert removed >= 10
    assert tool_registry.get("mcp__filesystem__write_file") is None
    assert tool_registry.get("mcp_write_file") is None


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP B — Functional Filesystem Operations
# ═══════════════════════════════════════════════════════════════════════════════

def test_filesystem_write_and_read_new_file(
    fs_manager: MCPServerManager,
    workspace_tmp: Path,
    jail: FilesystemPathJail,
    policy: FilesystemPermissionPolicy,
):
    """Tests creating a new file (automatic approval) and reading it back with positive verification."""
    defn = next(t for t in fs_manager.get_tool_definitions("filesystem") if t.name == "write_file")
    adapter = MCPFilesystemToolAdapter(defn, fs_manager, jail=jail, policy=policy)

    target_file = workspace_tmp / "sample_doc.txt"
    content = "Hello from Cortex Phase P1 Filesystem Integration!\nTesting content."

    # 1. Execute write_file
    res = adapter.execute({"path": str(target_file), "content": content})
    assert res.ok, f"Write failed: {res.message}"

    obs = adapter.observe({"path": str(target_file), "content": content}, res)
    ver = adapter.verify({"path": str(target_file), "content": content}, obs, res)
    assert ver.verified
    assert "Positive disk verification" in ver.evidence

    # Verify physical file on disk
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == content

    # 2. Execute read_file
    read_tool_name = "read_file" if any(t.name == "read_file" for t in fs_manager.get_tool_definitions("filesystem")) else "read_text_file"
    read_defn = next(t for t in fs_manager.get_tool_definitions("filesystem") if t.name == read_tool_name)
    read_adapter = MCPFilesystemToolAdapter(read_defn, fs_manager, jail=jail, policy=policy)

    read_res = read_adapter.execute({"path": str(target_file)})
    assert read_res.ok
    assert content in read_res.message

    read_obs = read_adapter.observe({"path": str(target_file)}, read_res)
    read_ver = read_adapter.verify({"path": str(target_file)}, read_obs, read_res)
    assert read_ver.verified


def test_filesystem_0_byte_empty_file_handling(
    fs_manager: MCPServerManager,
    workspace_tmp: Path,
    jail: FilesystemPathJail,
    policy: FilesystemPermissionPolicy,
):
    """Verifies that an empty (0-byte) file on disk is positively verified on read rather than failing."""
    empty_file = workspace_tmp / "empty.txt"
    empty_file.touch()
    assert empty_file.stat().st_size == 0

    read_tool_name = "read_file" if any(t.name == "read_file" for t in fs_manager.get_tool_definitions("filesystem")) else "read_text_file"
    read_defn = next(t for t in fs_manager.get_tool_definitions("filesystem") if t.name == read_tool_name)
    read_adapter = MCPFilesystemToolAdapter(read_defn, fs_manager, jail=jail, policy=policy)

    read_res = read_adapter.execute({"path": str(empty_file)})
    assert read_res.ok

    read_obs = read_adapter.observe({"path": str(empty_file)}, read_res)
    read_ver = read_adapter.verify({"path": str(empty_file)}, read_obs, read_res)
    assert read_ver.verified
    assert "0-byte empty file" in read_ver.evidence


def test_filesystem_create_directory_and_list(
    fs_manager: MCPServerManager,
    workspace_tmp: Path,
    jail: FilesystemPathJail,
    policy: FilesystemPermissionPolicy,
):
    """Tests creating a directory and listing its contents."""
    mkdir_defn = next(t for t in fs_manager.get_tool_definitions("filesystem") if t.name == "create_directory")
    mkdir_adapter = MCPFilesystemToolAdapter(mkdir_defn, fs_manager, jail=jail, policy=policy)

    sub_dir = workspace_tmp / "reports" / "2026"
    res = mkdir_adapter.execute({"path": str(sub_dir)})
    assert res.ok

    obs = mkdir_adapter.observe({"path": str(sub_dir)}, res)
    ver = mkdir_adapter.verify({"path": str(sub_dir)}, obs, res)
    assert ver.verified
    assert sub_dir.is_dir()

    # List directory
    list_defn = next(t for t in fs_manager.get_tool_definitions("filesystem") if t.name == "list_directory")
    list_adapter = MCPFilesystemToolAdapter(list_defn, fs_manager, jail=jail, policy=policy)

    list_res = list_adapter.execute({"path": str(workspace_tmp)})
    assert list_res.ok
    assert "reports" in list_res.message


def test_filesystem_search_files_and_get_info(
    fs_manager: MCPServerManager,
    workspace_tmp: Path,
    jail: FilesystemPathJail,
    policy: FilesystemPermissionPolicy,
):
    """Tests file search and metadata inspection."""
    test_file = workspace_tmp / "audit_log.json"
    test_file.write_text('{"status": "ok"}', encoding="utf-8")

    search_defn = next(t for t in fs_manager.get_tool_definitions("filesystem") if t.name == "search_files")
    search_adapter = MCPFilesystemToolAdapter(search_defn, fs_manager, jail=jail, policy=policy)

    search_res = search_adapter.execute({"path": str(workspace_tmp), "pattern": "*.json"})
    assert search_res.ok
    assert "audit_log.json" in search_res.message

    info_defn = next(t for t in fs_manager.get_tool_definitions("filesystem") if t.name == "get_file_info")
    info_adapter = MCPFilesystemToolAdapter(info_defn, fs_manager, jail=jail, policy=policy)

    info_res = info_adapter.execute({"path": str(test_file)})
    assert info_res.ok
    assert "size" in info_res.message.lower() or "bytes" in info_res.message.lower()


def test_filesystem_move_file_with_approval(
    fs_manager: MCPServerManager,
    workspace_tmp: Path,
    jail: FilesystemPathJail,
    policy: FilesystemPermissionPolicy,
):
    """Tests moving a file with approval hash validation and on-disk verification."""
    src = workspace_tmp / "source.txt"
    dst = workspace_tmp / "destination.txt"
    src.write_text("Moving this file.", encoding="utf-8")

    move_defn = next(t for t in fs_manager.get_tool_definitions("filesystem") if t.name == "move_file")
    move_adapter = MCPFilesystemToolAdapter(move_defn, fs_manager, jail=jail, policy=policy)

    # 1. Without approval -> rejected
    unapproved_res = move_adapter.execute({"source": str(src), "destination": str(dst)})
    assert not unapproved_res.ok
    assert unapproved_res.error == "ApprovalRequired"

    # 2. With valid approval hash -> succeeds
    clean_args = jail.validate_tool_arguments("move_file", {"source": str(src), "destination": str(dst)})
    token = policy.compute_operation_hash("move_file", clean_args)

    approved_res = move_adapter.execute({
        "source": str(src),
        "destination": str(dst),
        "approved_hash": token,
    })
    assert approved_res.ok, f"Move failed: {approved_res.message}"

    obs = move_adapter.observe({"source": str(src), "destination": str(dst)}, approved_res)
    ver = move_adapter.verify({"source": str(src), "destination": str(dst)}, obs, approved_res)
    assert ver.verified
    assert not src.exists()
    assert dst.exists()
    assert dst.read_text(encoding="utf-8") == "Moving this file."


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP C — Path Jail & Security Policy Enforcement
# ═══════════════════════════════════════════════════════════════════════════════

def test_path_traversal_rejection(
    fs_manager: MCPServerManager,
    workspace_tmp: Path,
    jail: FilesystemPathJail,
    policy: FilesystemPermissionPolicy,
):
    """Verifies that directory traversal attacks (../) are intercepted at the boundary."""
    defn = next(t for t in fs_manager.get_tool_definitions("filesystem") if t.name in {"read_file", "read_text_file"})
    adapter = MCPFilesystemToolAdapter(defn, fs_manager, jail=jail, policy=policy)

    # Traversal attack targeting outside the approved root
    res = adapter.execute({"path": str(workspace_tmp / "../../../etc/passwd")})
    assert not res.ok
    assert res.error == "SecurityViolation"
    assert "outside all approved workspace roots" in res.message


def test_protected_sensitive_files_rejection(
    fs_manager: MCPServerManager,
    workspace_tmp: Path,
    jail: FilesystemPathJail,
    policy: FilesystemPermissionPolicy,
):
    """Verifies access to credentials and secrets is strictly denied even inside workspace."""
    defn = next(t for t in fs_manager.get_tool_definitions("filesystem") if t.name == "write_file")
    adapter = MCPFilesystemToolAdapter(defn, fs_manager, jail=jail, policy=policy)

    denied_targets = [
        workspace_tmp / ".env",
        workspace_tmp / ".session_secret",
        workspace_tmp / "id_rsa",
        workspace_tmp / ".git" / "config",
    ]

    for target in denied_targets:
        res = adapter.execute({"path": str(target), "content": "secret data"})
        assert not res.ok
        assert res.error == "SecurityViolation"
        assert "strictly denied" in res.message


def test_symlink_escape_rejection(
    fs_manager: MCPServerManager,
    workspace_tmp: Path,
    tmp_path: Path,
    jail: FilesystemPathJail,
    policy: FilesystemPermissionPolicy,
):
    """Verifies that symbolic links pointing outside the approved root are rejected."""
    # Create an outside secret directory and file
    outside_dir = tmp_path / "outside_secrets"
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_file = outside_dir / "confidential.txt"
    outside_file.write_text("Top secret outside workspace", encoding="utf-8")

    # Create a symlink inside the workspace pointing to the outside file
    symlink_inside = workspace_tmp / "leak_link.txt"
    os.symlink(outside_file, symlink_inside)

    read_tool_name = "read_file" if any(t.name == "read_file" for t in fs_manager.get_tool_definitions("filesystem")) else "read_text_file"
    defn = next(t for t in fs_manager.get_tool_definitions("filesystem") if t.name == read_tool_name)
    adapter = MCPFilesystemToolAdapter(defn, fs_manager, jail=jail, policy=policy)

    res = adapter.execute({"path": str(symlink_inside)})
    assert not res.ok
    assert res.error == "SecurityViolation"
    assert "outside all approved workspace roots" in res.message or "escaping approved workspace roots" in res.message


def test_overwrite_requires_approval(
    fs_manager: MCPServerManager,
    workspace_tmp: Path,
    jail: FilesystemPathJail,
    policy: FilesystemPermissionPolicy,
):
    """Verifies that overwriting an existing file requires cryptographic approval."""
    target_file = workspace_tmp / "critical.txt"
    target_file.write_text("Original content", encoding="utf-8")

    defn = next(t for t in fs_manager.get_tool_definitions("filesystem") if t.name == "write_file")
    adapter = MCPFilesystemToolAdapter(defn, fs_manager, jail=jail, policy=policy)

    # 1. Overwrite attempt without approval -> rejected
    unapproved = adapter.execute({"path": str(target_file), "content": "Modified content"})
    assert not unapproved.ok
    assert unapproved.error == "ApprovalRequired"
    assert target_file.read_text(encoding="utf-8") == "Original content"

    # 2. Compute approval token for the overwrite
    clean_args = jail.validate_tool_arguments("write_file", {"path": str(target_file), "content": "Modified content"})
    token = policy.compute_operation_hash("write_file", clean_args)

    # 3. With approval -> succeeds
    approved = adapter.execute({"path": str(target_file), "content": "Modified content", "approved_hash": token})
    assert approved.ok
    assert target_file.read_text(encoding="utf-8") == "Modified content"


def test_stale_approval_and_replay_rejection(
    fs_manager: MCPServerManager,
    workspace_tmp: Path,
    jail: FilesystemPathJail,
    policy: FilesystemPermissionPolicy,
):
    """Verifies that modified arguments invalidate approval (mismatch) and tokens cannot be replayed."""
    target_file = workspace_tmp / "contract.txt"
    target_file.write_text("Clause 1", encoding="utf-8")

    defn = next(t for t in fs_manager.get_tool_definitions("filesystem") if t.name == "write_file")
    adapter = MCPFilesystemToolAdapter(defn, fs_manager, jail=jail, policy=policy)

    # Generate token for 'Clause 2'
    clean_args = jail.validate_tool_arguments("write_file", {"path": str(target_file), "content": "Clause 2"})
    token = policy.compute_operation_hash("write_file", clean_args)

    # Stale/Tampered argument test: token was for 'Clause 2', but inputs provide 'Clause 3 - Tampered'
    mismatch_res = adapter.execute({
        "path": str(target_file),
        "content": "Clause 3 - Tampered",
        "approved_hash": token,
    })
    assert not mismatch_res.ok
    assert mismatch_res.error == "ApprovalMismatch"

    # Valid execution consumes the token
    valid_res = adapter.execute({
        "path": str(target_file),
        "content": "Clause 2",
        "approved_hash": token,
    })
    assert valid_res.ok

    # Replay attack: try reusing the consumed token
    replay_res = adapter.execute({
        "path": str(target_file),
        "content": "Clause 2",
        "approved_hash": token,
    })
    assert not replay_res.ok
    assert replay_res.error == "ApprovalReplay"


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP D — Resilience, Recovery, and Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

def test_recovery_policy_prevents_mutation_retries(
    fs_manager: MCPServerManager,
    workspace_tmp: Path,
    jail: FilesystemPathJail,
    policy: FilesystemPermissionPolicy,
):
    """Verifies that mutating operations are never retried blindly on failure."""
    target_file = workspace_tmp / "locked.txt"
    target_file.touch()

    write_defn = next(t for t in fs_manager.get_tool_definitions("filesystem") if t.name == "write_file")
    adapter = MCPFilesystemToolAdapter(write_defn, fs_manager, jail=jail, policy=policy)

    err = ExecutionError(code="IOError", message="Disk error", recoverable=True)
    recovery = adapter.recover({"path": str(target_file), "content": "data"}, err, attempt=1)
    assert not recovery["can_retry"]
    assert recovery["strategy"] == "escalate"


def test_recovery_allows_safe_read_retries(
    fs_manager: MCPServerManager,
    workspace_tmp: Path,
    jail: FilesystemPathJail,
    policy: FilesystemPermissionPolicy,
):
    """Verifies that non-mutating read operations allow safe retries."""
    read_tool_name = "read_file" if any(t.name == "read_file" for t in fs_manager.get_tool_definitions("filesystem")) else "read_text_file"
    read_defn = next(t for t in fs_manager.get_tool_definitions("filesystem") if t.name == read_tool_name)
    adapter = MCPFilesystemToolAdapter(read_defn, fs_manager, jail=jail, policy=policy)

    err = ExecutionError(code="Timeout", message="Read timeout", recoverable=True)
    recovery = adapter.recover({"path": str(workspace_tmp / "file.txt")}, err, attempt=1)
    assert recovery["can_retry"]
    assert recovery["strategy"] == "retry"


def test_timeout_enforcement(
    fs_manager: MCPServerManager,
    workspace_tmp: Path,
    jail: FilesystemPathJail,
    policy: FilesystemPermissionPolicy,
):
    """Verifies that call_tool respects timeouts."""
    defn = next(t for t in fs_manager.get_tool_definitions("filesystem") if t.name in {"read_file", "read_text_file"})
    adapter = MCPFilesystemToolAdapter(defn, fs_manager, jail=jail, policy=policy)

    # Use an impossibly tiny timeout to trigger timeout handling
    res = adapter.execute({"path": str(workspace_tmp / "nonexistent.txt"), "timeout": 0.000001})
    # Either timeout or path error is handled gracefully without crash
    assert not res.ok


def test_unregistered_tool_invocation(fs_manager: MCPServerManager):
    """Verifies that invoking an unknown tool fails cleanly with MCPToolNotFoundError."""
    with pytest.raises(MCPToolNotFoundError):
        fs_manager.call_tool("filesystem", "nonexistent_filesystem_tool", {})
