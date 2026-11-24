"""
Phase P1.2 / Natural Language Execution Acceptance Test Suite for Cortex Filesystem MCP.

Tests Acceptance Scenarios A through J:
  Test A: Folder creation ('Create a new folder named CortexDemo on my Desktop.')
  Test B: File creation ('Create example.txt on my Desktop containing This is an example file.')
  Test C: Multi-turn creation ('Create a new file' -> 'notes.txt' -> 'Desktop' -> 'Hello Cortex.')
  Test D: Empty file ('Create an empty file called empty.txt on Desktop.')
  Test E: Read file ('Read example.txt from my Desktop.')
  Test F: Open file in application ('Open example.txt from my Desktop in TextEdit.')
  Test G: Search and ambiguity ('Find my project report.')
  Test H: Existing file overwrite approval ('Create example.txt again with new content.')
  Test I: Unauthorized directory prompt and grant ('Create a file in unauthorized directory')
  Test J: Regression and security verification
"""

import os
from pathlib import Path
import shutil
import pytest

from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities.device_actions import DeviceAutomation
from backend.core.contracts import RiskLevel, TaskCommand, TaskStatus
from backend.mcp.filesystem_jail import DEFAULT_WORKSPACE_ROOT, FilesystemPathJail
from backend.mcp.filesystem_policy import FilesystemPermissionPolicy
from backend.tools.file_tool import FileTool


@pytest.fixture(scope="module")
def desktop_path() -> Path:
    p = Path.home() / "Desktop"
    p.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture
def clean_desktop_artifacts(desktop_path: Path):
    """Ensures test artifacts on Desktop are cleaned up before and after tests."""
    targets = [
        desktop_path / "CortexDemo",
        desktop_path / "test_auto_xyz",
        desktop_path / "example.txt",
        desktop_path / "notes.txt",
        desktop_path / "empty.txt",
        desktop_path / "project report final.txt",
        Path.home() / "Documents" / "project report v1.txt",
        Path("/tmp/cortex_unauthorized_test"),
    ]
    for t in targets:
        if t.is_dir():
            shutil.rmtree(t, ignore_errors=True)
        elif t.exists():
            try:
                t.unlink()
            except Exception:
                pass

    yield targets

    for t in targets:
        if t.is_dir():
            shutil.rmtree(t, ignore_errors=True)
        elif t.exists():
            try:
                t.unlink()
            except Exception:
                pass


@pytest.fixture
def orchestrator() -> CortexOrchestrator:
    """Instantiates a live CortexOrchestrator with initialized MCP components."""
    auto = DeviceAutomation(dry_run=True)
    orch = CortexOrchestrator(automation=auto, use_gemini=False)
    orch.ensure_mcp_tools()
    return orch


# ═══════════════════════════════════════════════════════════════════════════════
# ACCEPTANCE TEST A: Folder creation
# ═══════════════════════════════════════════════════════════════════════════════

def test_a_folder_creation_explicit_location(orchestrator: CortexOrchestrator, desktop_path: Path, clean_desktop_artifacts):
    """Verifies: 'Create a new folder named CortexDemo on my Desktop.' creates folder on Desktop."""
    target = desktop_path / "CortexDemo"
    assert not target.exists()

    res = orchestrator.chat("Create a new folder named CortexDemo on my Desktop.")

    assert target.exists() and target.is_dir()
    assert "CortexDemo" in res["message"]
    assert res["task"]["status"] in (TaskStatus.COMPLETED.value, "completed")
    assert "terminal" not in res["message"].lower()


def test_a_folder_creation_default_location(orchestrator: CortexOrchestrator, desktop_path: Path, clean_desktop_artifacts):
    """Verifies: 'Create new folder name it test_auto_xyz' defaults to Desktop and informs user."""
    target = desktop_path / "test_auto_xyz"
    assert not target.exists()

    res = orchestrator.chat("Create new folder name it test_auto_xyz")

    assert target.exists() and target.is_dir()
    assert "test_auto_xyz" in res["message"]
    assert "desktop" in res["message"].lower()
    assert res["task"]["status"] in (TaskStatus.COMPLETED.value, "completed")


# ═══════════════════════════════════════════════════════════════════════════════
# ACCEPTANCE TEST B: File creation with content
# ═══════════════════════════════════════════════════════════════════════════════

def test_b_file_creation_with_content(orchestrator: CortexOrchestrator, desktop_path: Path, clean_desktop_artifacts):
    """Verifies: 'Create example.txt on my Desktop containing This is an example file.'"""
    target = desktop_path / "example.txt"
    assert not target.exists()

    res = orchestrator.chat("Create example.txt on my Desktop containing This is an example file.")

    assert target.exists() and target.is_file()
    assert target.read_text(encoding="utf-8").strip() == "This is an example file"
    assert "example.txt" in res["message"]
    assert res["task"]["status"] in (TaskStatus.COMPLETED.value, "completed")
    # Verify no bash/terminal instructions given
    assert "touch" not in res["message"]
    assert "mkdir" not in res["message"]


# ═══════════════════════════════════════════════════════════════════════════════
# ACCEPTANCE TEST C: Multi-turn slot filling
# ═══════════════════════════════════════════════════════════════════════════════

def test_c_multi_turn_file_creation(orchestrator: CortexOrchestrator, desktop_path: Path, clean_desktop_artifacts):
    """Verifies: 'Create a new file' -> 'notes.txt' -> 'Desktop' -> 'Hello Cortex.' retains state."""
    target = desktop_path / "notes.txt"
    assert not target.exists()

    # Turn 1: Initiation
    res1 = orchestrator.chat("Create a new file.")
    assert "name" in res1["message"].lower()
    assert orchestrator.pending_action is not None
    assert orchestrator.pending_action.get("step") == "ask_filename"

    # Turn 2: Provide filename
    res2 = orchestrator.chat("notes.txt")
    assert "where" in res2["message"].lower() or "desktop" in res2["message"].lower()
    assert orchestrator.pending_action.get("step") == "ask_destination"
    assert orchestrator.pending_action.get("filename") == "notes.txt"

    # Turn 3: Provide location
    res3 = orchestrator.chat("Desktop")
    assert "content" in res3["message"].lower()
    assert orchestrator.pending_action.get("step") == "ask_content"
    assert orchestrator.pending_action.get("destination") == "Desktop"

    # Turn 4: Provide content
    res4 = orchestrator.chat("Hello Cortex.")
    assert target.exists() and target.is_file()
    assert target.read_text(encoding="utf-8").strip() == "Hello Cortex."
    assert "notes.txt" in res4["message"]
    assert res4["task"]["status"] in (TaskStatus.COMPLETED.value, "completed")
    assert orchestrator.pending_action is None


# ═══════════════════════════════════════════════════════════════════════════════
# ACCEPTANCE TEST D: Empty file creation
# ═══════════════════════════════════════════════════════════════════════════════

def test_d_empty_file_creation(orchestrator: CortexOrchestrator, desktop_path: Path, clean_desktop_artifacts):
    """Verifies: 'Create an empty file called empty.txt on Desktop.' produces valid 0-byte file."""
    target = desktop_path / "empty.txt"
    assert not target.exists()

    res = orchestrator.chat("Create an empty file called empty.txt on Desktop.")

    assert target.exists() and target.is_file()
    assert target.stat().st_size == 0
    assert "empty.txt" in res["message"]
    assert res["task"]["status"] in (TaskStatus.COMPLETED.value, "completed")


# ═══════════════════════════════════════════════════════════════════════════════
# ACCEPTANCE TEST E: Read file
# ═══════════════════════════════════════════════════════════════════════════════

def test_e_read_file(orchestrator: CortexOrchestrator, desktop_path: Path, clean_desktop_artifacts):
    """Verifies: 'Read example.txt from my Desktop.' returns actual file contents."""
    target = desktop_path / "example.txt"
    target.write_text("Unique Cortex Knowledge String 42", encoding="utf-8")

    res = orchestrator.chat("Read example.txt from my Desktop.")

    assert "Unique Cortex Knowledge String 42" in res["message"]
    assert res["task"]["status"] in (TaskStatus.COMPLETED.value, "completed")


# ═══════════════════════════════════════════════════════════════════════════════
# ACCEPTANCE TEST F: Open file in application
# ═══════════════════════════════════════════════════════════════════════════════

def test_f_open_file_in_application(orchestrator: CortexOrchestrator, desktop_path: Path, clean_desktop_artifacts):
    """Verifies: 'Open example.txt from my Desktop in TextEdit.' invokes app action."""
    target = desktop_path / "example.txt"
    target.write_text("Editable content", encoding="utf-8")

    res = orchestrator.chat("Open example.txt from my Desktop in TextEdit.")

    assert "TextEdit" in res["message"] or "example.txt" in res["message"]
    assert res["task"]["command"] == TaskCommand.OPEN_APP.value
    assert res["task"]["params"].get("file_path") == str(target.resolve())


# ═══════════════════════════════════════════════════════════════════════════════
# ACCEPTANCE TEST G: Search and ambiguity
# ═══════════════════════════════════════════════════════════════════════════════

def test_g_search_and_ambiguity(orchestrator: CortexOrchestrator, desktop_path: Path, clean_desktop_artifacts):
    """Verifies: 'Find my project report.' surfaces candidates and asks user to choose."""
    file1 = desktop_path / "project report final.txt"
    file2 = Path.home() / "Documents" / "project report v1.txt"
    file1.write_text("Final Report", encoding="utf-8")
    file2.parent.mkdir(parents=True, exist_ok=True)
    file2.write_text("Draft v1 Report", encoding="utf-8")

    res = orchestrator.chat("Find my project report.")

    assert "project report final.txt" in res["message"]
    assert "project report v1.txt" in res["message"]
    assert "which" in res["message"].lower() or "choose" in res["message"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# ACCEPTANCE TEST H: Existing file overwrite approval
# ═══════════════════════════════════════════════════════════════════════════════

def test_h_overwrite_protection_and_approval(orchestrator: CortexOrchestrator, desktop_path: Path, clean_desktop_artifacts):
    """Verifies: overwriting existing file pauses for approval and does not mutate before confirmation."""
    target = desktop_path / "example.txt"
    target.write_text("Initial Unmodified Content", encoding="utf-8")

    # Turn 1: Attempt to overwrite
    res1 = orchestrator.chat("Create example.txt on my Desktop containing Overwritten Value.")
    assert "already exists" in res1["message"].lower() or "overwrite" in res1["message"].lower()
    # Disk MUST NOT be modified yet
    assert target.read_text(encoding="utf-8") == "Initial Unmodified Content"
    assert orchestrator.pending_action is not None
    assert orchestrator.pending_action.get("step") == "confirm_overwrite"

    # Turn 2: User confirms
    res2 = orchestrator.chat("yes")
    assert target.read_text(encoding="utf-8").strip() == "Overwritten Value"
    assert "example.txt" in res2["message"]
    assert orchestrator.pending_action is None


# ═══════════════════════════════════════════════════════════════════════════════
# ACCEPTANCE TEST I: Unauthorized directory prompt & dynamic grant
# ═══════════════════════════════════════════════════════════════════════════════

def test_i_unauthorized_directory_prompt_and_grant(orchestrator: CortexOrchestrator, clean_desktop_artifacts):
    """Verifies: attempting access to unapproved path prompts for authorization and continues once approved."""
    unauthorized_dir = Path("/tmp/cortex_unauthorized_test")
    unauthorized_dir.mkdir(parents=True, exist_ok=True)
    target = unauthorized_dir / "target.txt"

    # Turn 1: Request in unauthorized folder
    res1 = orchestrator.chat(f"Create a file in {target} containing AuthorizedData")
    assert "not authorized" in res1["message"].lower() or "grant" in res1["message"].lower()
    assert not target.exists()
    assert orchestrator.pending_action is not None
    assert orchestrator.pending_action.get("step") == "confirm_grant_root"

    # Turn 2: User grants access
    res2 = orchestrator.chat("yes")
    assert target.exists()
    assert target.read_text(encoding="utf-8").strip() == "AuthorizedData"
    assert orchestrator.pending_action is None


# ═══════════════════════════════════════════════════════════════════════════════
# ACCEPTANCE TEST J: Regression and security boundaries
# ═══════════════════════════════════════════════════════════════════════════════

def test_j_regression_native_file_tool():
    """Verifies that native FileTool continues to operate independently without regression."""
    auto = DeviceAutomation(dry_run=True)
    ft = FileTool(automation=auto)
    res = ft.execute({"action": "search_files", "directory": str(Path.home() / "Documents"), "pattern": "*"})
    assert res.ok is True


def test_j_path_jail_traversal_blocked():
    """Verifies that path jail blocks traversal tricks and symlink escapes."""
    jail = FilesystemPathJail()
    from backend.mcp.exceptions import MCPSecurityError
    with pytest.raises(MCPSecurityError):
        jail.canonicalize("~/Desktop/../../../etc/passwd")


def test_j_consequential_approval_hash_enforcement():
    """Verifies that FilesystemPermissionPolicy generates and strictly verifies approval hashes."""
    policy = FilesystemPermissionPolicy()
    args = {"path": "/Users/test/Desktop/file.txt", "content": "data"}
    h = policy.generate_approval_hash("write_file", args)
    assert len(h) == 64
    ok, _, _ = policy.validate_approval("write_file", args, h)
    assert ok is True

    # Replay of the already consumed token must fail with ApprovalReplay
    ok2, err_code2, _ = policy.validate_approval("write_file", args, h)
    assert ok2 is False
    assert err_code2 == "ApprovalReplay"

    # Mismatched/tampered arguments with an unconsumed hash must fail with ApprovalMismatch
    tampered_args = {"path": "/Users/test/Desktop/file.txt", "content": "tampered"}
    fake_hash = "0" * 64
    ok3, err_code3, _ = policy.validate_approval("write_file", tampered_args, fake_hash)
    assert ok3 is False
    assert err_code3 == "ApprovalMismatch"
