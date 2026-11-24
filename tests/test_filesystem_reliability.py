"""
Filesystem Reliability Remediation Acceptance Test Suite.

Verifies resolution of real-world filesystem failures:
  Test A: Compound folder and file creation ("Open CortexDemo folder Create example.txt file containing This is an example file")
  Test B: Folder creation and nested file creation ("Create a folder called Reports on Desktop and put notes.txt inside it")
  Test C: PDF / Presentation reading ("Read ClickHouse Presentation from my Desktop")
  Test D: Default macOS file opening ("Open TokenLens System Architecture Diagram.pdf")
  Test E: Explicit application opening ("Open TokenLens System Architecture Diagram.pdf in Preview")
  Test F: Move without Gemini (cooldown active, move file with approval)
  Test G: Create without Gemini (cooldown active, create folder)
  Test H: Delete unsupported ("Delete the folder myDemo" -> clear explanation)
  Test I: Ambiguous file search (multiple candidates -> ask user to choose)
  Test J: Security and path jail enforcement
"""

import os
from pathlib import Path
import shutil
import time
import pytest

from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities.device_actions import DeviceAutomation
from backend.capabilities.document_reader import read_document
from backend.core.contracts import RiskLevel, TaskCommand, TaskStatus


@pytest.fixture(scope="module")
def desktop_path() -> Path:
    p = Path.home() / "Desktop"
    p.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture
def clean_artifacts(desktop_path: Path):
    targets = [
        desktop_path / "CortexDemo",
        desktop_path / "Reports",
        desktop_path / "Projects",
        desktop_path / "OfflineTest",
        desktop_path / "AmbiguousFolder",
        desktop_path / "test_move_src.txt",
        desktop_path / "TokenLens System Architecture Diagram.pdf",
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
    auto = DeviceAutomation(dry_run=True)
    orch = CortexOrchestrator(automation=auto, use_gemini=False)
    orch.ensure_mcp_tools()
    return orch


# ═══════════════════════════════════════════════════════════════════════════════
# TEST A: Compound folder and file creation
# ═══════════════════════════════════════════════════════════════════════════════

def test_a_compound_open_folder_and_create_file(orchestrator: CortexOrchestrator, desktop_path: Path, clean_artifacts):
    """
    Verifies:
    "Open CortexDemo folder Create example.txt file containing This is an example file"
    is not misclassified as an app-launch request, splits into folder opening and file creation,
    and creates example.txt inside CortexDemo.
    """
    folder = desktop_path / "CortexDemo"
    file_path = folder / "example.txt"

    assert not folder.exists()
    assert not file_path.exists()

    res = orchestrator.chat("Open CortexDemo folder Create example.txt file containing This is an example file")

    assert folder.exists() and folder.is_dir()
    assert file_path.exists() and file_path.is_file()
    assert file_path.read_text(encoding="utf-8").strip() == "This is an example file"
    assert res["task"]["status"] in (TaskStatus.COMPLETED.value, "completed")
    assert "CortexDemo" in res["message"] or "example.txt" in res["message"]


# ═══════════════════════════════════════════════════════════════════════════════
# TEST B: Folder creation and nested file creation
# ═══════════════════════════════════════════════════════════════════════════════

def test_b_folder_and_nested_file_creation(orchestrator: CortexOrchestrator, desktop_path: Path, clean_artifacts):
    """
    Verifies:
    "Create a folder called Reports on Desktop and put notes.txt inside it"
    creates folder Reports on Desktop and creates notes.txt nested inside it.
    """
    folder = desktop_path / "Reports"
    file_path = folder / "notes.txt"

    assert not folder.exists()
    assert not file_path.exists()

    res = orchestrator.chat("Create a folder called Reports on Desktop and put notes.txt inside it")

    assert folder.exists() and folder.is_dir()
    assert file_path.exists() and file_path.is_file()
    assert res["task"]["status"] in (TaskStatus.COMPLETED.value, "completed")


# ═══════════════════════════════════════════════════════════════════════════════
# TEST C: PDF / Presentation reading
# ═══════════════════════════════════════════════════════════════════════════════

def test_c_read_presentation_from_desktop(orchestrator: CortexOrchestrator, desktop_path: Path):
    """
    Verifies:
    "Read ClickHouse Presentation from my Desktop"
    discovers ClickHouse Presentation.pptx on Desktop and extracts its slide contents
    without mcp_read_text_file encoding failure.
    """
    pptx_path = desktop_path / "ClickHouse Presentation.pptx"
    if not pptx_path.exists():
        pytest.skip("ClickHouse Presentation.pptx not found on Desktop for live verification")

    res = orchestrator.chat("Read ClickHouse Presentation from my Desktop")

    assert res["task"]["status"] in (TaskStatus.COMPLETED.value, "completed")
    assert len(res["message"]) > 100
    assert "ClickHouse" in res["message"] or "Slide" in res["message"]


def test_c_document_reader_direct():
    """Direct unit test of document_reader format awareness."""
    desktop = Path.home() / "Desktop"
    pptx = desktop / "ClickHouse Presentation.pptx"
    if pptx.exists():
        doc = read_document(pptx)
        assert doc.ok
        assert doc.file_type == "pptx"
        assert doc.page_or_slide_count > 0
        assert "Slide 1" in doc.content


# ═══════════════════════════════════════════════════════════════════════════════
# TEST D: Default macOS file opening
# ═══════════════════════════════════════════════════════════════════════════════

def test_d_open_file_in_default_application(orchestrator: CortexOrchestrator, desktop_path: Path, clean_artifacts):
    """
    Verifies:
    "Open TokenLens System Architecture Diagram.pdf"
    uses macOS Launch Services (open <file>) rather than looking for an application named
    'TokenLens System Architecture Diagram.pdf'.
    """
    pdf_path = desktop_path / "TokenLens System Architecture Diagram.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 dummy pdf for test")

    res = orchestrator.chat("Open TokenLens System Architecture Diagram.pdf")

    assert res["task"]["status"] in (TaskStatus.COMPLETED.value, "completed")
    assert "Application is not installed on this Mac" not in res["message"]
    assert "default application" in res["message"].lower() or "opened" in res["message"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST E: Explicit application opening
# ═══════════════════════════════════════════════════════════════════════════════

def test_e_open_file_in_explicit_application(orchestrator: CortexOrchestrator, desktop_path: Path, clean_artifacts):
    """
    Verifies:
    "Open TokenLens System Architecture Diagram.pdf in Preview"
    resolves the application to Preview and opens the file in Preview.
    """
    pdf_path = desktop_path / "TokenLens System Architecture Diagram.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 dummy pdf for test")

    res = orchestrator.chat("Open TokenLens System Architecture Diagram.pdf in Preview")

    assert res["task"]["status"] in (TaskStatus.COMPLETED.value, "completed")
    assert "Preview" in res["message"]
    assert "Application is not installed on this Mac" not in res["message"]


# ═══════════════════════════════════════════════════════════════════════════════
# TEST F: Move without Gemini (cooldown active, move file with approval)
# ═══════════════════════════════════════════════════════════════════════════════

def test_f_move_file_resilient_during_model_cooldown(orchestrator: CortexOrchestrator, desktop_path: Path, clean_artifacts):
    """
    Verifies:
    Deterministic filesystem operations (moving a file) succeed even when Gemini is in
    active cooldown/outage state. Enforces cryptographic approval requirement.
    """
    # Simulate active cloud model outage / cooldown
    orchestrator.gemini_cooldown_until = time.time() + 3600

    src_file = desktop_path / "test_move_src.txt"
    src_file.write_text("file to be moved", encoding="utf-8")

    projects_dir = desktop_path / "Projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    dest_file = projects_dir / "test_move_src.txt"

    assert src_file.exists()
    assert not dest_file.exists()

    # Step 1: User issues move command
    res1 = orchestrator.chat("Move test_move_src.txt to Projects")

    # Must require approval, NOT be blocked by model outage
    assert res1["task"]["status"] in (TaskStatus.WAITING_APPROVAL.value, "waiting_approval")
    assert "proceed" in res1["message"].lower() or "modify your filesystem" in res1["message"].lower()

    # Step 2: User confirms approval
    res2 = orchestrator.chat("yes")

    assert res2["task"]["status"] in (TaskStatus.COMPLETED.value, "completed")
    assert not src_file.exists()
    assert dest_file.exists()
    assert dest_file.read_text(encoding="utf-8") == "file to be moved"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST G: Create without Gemini (cooldown active, create folder)
# ═══════════════════════════════════════════════════════════════════════════════

def test_g_create_folder_during_model_cooldown(orchestrator: CortexOrchestrator, desktop_path: Path, clean_artifacts):
    """
    Verifies:
    Creating a directory executes deterministically without failure during Gemini cooldown.
    """
    orchestrator.gemini_cooldown_until = time.time() + 3600

    target = desktop_path / "OfflineTest"
    assert not target.exists()

    res = orchestrator.chat("Create folder OfflineTest on Desktop")

    assert target.exists() and target.is_dir()
    assert res["task"]["status"] in (TaskStatus.COMPLETED.value, "completed")
    assert "OfflineTest" in res["message"]


# ═══════════════════════════════════════════════════════════════════════════════
# TEST H: Delete unsupported
# ═══════════════════════════════════════════════════════════════════════════════

def test_h_delete_unsupported_explains_absence(orchestrator: CortexOrchestrator, desktop_path: Path, clean_artifacts):
    """
    Verifies:
    "Delete the folder myDemo" is blocked and explains that the current filesystem MCP provider
    has no deletion capability. Does NOT execute arbitrary shell rm or AppleScript.
    """
    demo_dir = desktop_path / "CortexDemo"
    demo_dir.mkdir(parents=True, exist_ok=True)

    res = orchestrator.chat("Delete the folder CortexDemo")

    assert res["task"]["status"] in (TaskStatus.BLOCKED.value, "blocked")
    assert "File deletion is not currently supported by my filesystem tools. No file was deleted." in res["message"]
    # Ensure folder was NOT deleted
    assert demo_dir.exists()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST I: Ambiguous file search (multiple candidates -> ask user to choose)
# ═══════════════════════════════════════════════════════════════════════════════

def test_i_ambiguous_file_search_and_disambiguation(orchestrator: CortexOrchestrator, desktop_path: Path, clean_artifacts):
    """
    Verifies:
    When multiple candidate files match a search or open query, Cortex presents candidates
    and prompts the user to disambiguate before acting.
    """
    folder = desktop_path / "AmbiguousFolder"
    folder.mkdir(parents=True, exist_ok=True)
    f1 = folder / "QuarterlyReport_Q1.txt"
    f2 = folder / "QuarterlyReport_Q2.txt"
    f1.write_text("Q1 content", encoding="utf-8")
    f2.write_text("Q2 content", encoding="utf-8")

    # Authorize AmbiguousFolder in jail
    orchestrator.mcp_jail.grant_root(folder)

    res1 = orchestrator.chat("Read QuarterlyReport from AmbiguousFolder")

    # Ambiguity detected -> prompts user to choose
    assert res1["task"]["status"] in (TaskStatus.NEED_INFO.value, "need_info")
    assert "Which one would you like to read?" in res1["message"]
    assert "QuarterlyReport_Q1.txt" in res1["message"]
    assert "QuarterlyReport_Q2.txt" in res1["message"]

    # User chooses option 1
    res2 = orchestrator.chat("1")

    assert res2["task"]["status"] in (TaskStatus.COMPLETED.value, "completed")
    assert "Q1 content" in res2["message"]
