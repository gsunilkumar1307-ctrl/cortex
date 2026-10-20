import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared-sdk" / "python"))
sys.path.insert(0, str(ROOT / "automation-engine"))
sys.path.insert(0, str(ROOT / "memory-service"))
sys.path.insert(0, str(ROOT / "cloud-brain" / "app"))

from cortex_automation import DeviceAutomation
from cortex_automation.device_actions import _is_safe_path
from cortex_automation.mail_actions import MailAutomation
from cortex_memory import EncryptedMemoryStore
from cortex_sdk import RiskLevel, TaskCommand, TaskStatus, command_from_intent
from orchestrator import CortexOrchestrator
from planner import AutonomousPlanner, Plan, PlanStep
from tools.registry import ToolRegistry


class TestMasterBuildFiles(unittest.TestCase):
    """System 4: Computer Agent / File Intelligence Tests."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work_dir = Path(self.tmp.name)
        memory = EncryptedMemoryStore(str(self.work_dir / "memory.sqlite3"))
        self.orch = CortexOrchestrator(DeviceAutomation(dry_run=False), memory, use_gemini=False)

    def test_path_safety_prevents_directory_traversal(self):
        """Path traversal outside allowed user root should be rejected."""
        safe, _ = _is_safe_path("../../etc/passwd")
        self.assertFalse(safe, "Traversal using ../ should be blocked")

        safe, _ = _is_safe_path("/etc/shadow")
        self.assertFalse(safe, "Sensitive system paths should be blocked")

        safe, _ = _is_safe_path("~/.ssh/id_rsa")
        self.assertFalse(safe, "SSH key files should be blocked")

    def test_write_file_and_verification(self):
        """Writing a file inside user sandbox must succeed and pass verification."""
        test_file = str(self.work_dir / "notes.txt")
        content = "Cortex autonomous execution test"

        # Execute write via automation
        res = self.orch.automation.execute(TaskCommand.WRITE_FILE, {"path": test_file, "content": content})
        self.assertTrue(res.ok)
        self.assertTrue(Path(test_file).exists())
        self.assertEqual(Path(test_file).read_text(encoding="utf-8"), content)

        # Verify state
        verified = self.orch.automation.verify_file_written(test_file, content)
        self.assertTrue(verified)

    def test_read_file_and_verification(self):
        """Reading an existing file must return contents."""
        test_file = self.work_dir / "sample.log"
        test_file.write_text("Hello from file system", encoding="utf-8")

        res = self.orch.automation.execute(TaskCommand.READ_FILE, {"path": str(test_file)})
        self.assertTrue(res.ok)
        self.assertIn("Hello from file system", res.data["content"])

        verified = self.orch.automation.verify_file_exists(str(test_file))
        self.assertTrue(verified)

    def test_search_files(self):
        """Searching directory for pattern must find matching files."""
        sub = self.work_dir / "project"
        sub.mkdir()
        (sub / "report.md").write_text("# Report", encoding="utf-8")
        (sub / "data.csv").write_text("1,2,3", encoding="utf-8")

        res = self.orch.automation.execute(
            TaskCommand.SEARCH_FILES,
            {"pattern": "report", "directory": str(self.work_dir)},
        )
        self.assertTrue(res.ok)
        self.assertEqual(len(res.data["files"]), 1)
        self.assertIn("report.md", res.data["files"][0])


class TestMasterBuildMailIntelligence(unittest.TestCase):
    """System 2: Mail Intelligence (Search, Briefing, Action Extraction)."""

    def setUp(self):
        self.mail = MailAutomation()

    def test_search_mail_filters_query(self):
        mock_emails = [
            {"sender": "boss@company.com", "subject": "Q3 Budget Review", "snippet": "Please review the budget sheet"},
            {"sender": "newsletter@tech.com", "subject": "Daily Tech News", "snippet": "Latest AI models released"},
        ]
        with patch.object(self.mail, "read_mail", return_value={"ok": True, "emails": mock_emails}):
            res = self.mail.search_mail("Budget")
            self.assertTrue(res["ok"])
            self.assertEqual(len(res["emails"]), 1)
            self.assertEqual(res["emails"][0]["sender"], "boss@company.com")

    def test_email_briefing_categorization(self):
        mock_emails = [
            {"sender": "lead@company.com", "subject": "URGENT: Server outage", "snippet": "Database is down"},
            {"sender": "store@shop.com", "subject": "20% off shoes", "snippet": "Exclusive promo code"},
            {"sender": "news@medium.com", "subject": "Digest for today", "snippet": "Here are top stories"},
        ]
        with patch.object(self.mail, "read_mail", return_value={"ok": True, "emails": mock_emails}):
            res = self.mail.email_briefing(limit=10)
            self.assertTrue(res["ok"])
            briefing = res["message"].lower()
            self.assertIn("briefing", briefing)
            self.assertIn("priority", briefing)
            self.assertEqual(res["data"]["important_count"], 1)

    def test_extract_actions(self):
        mock_emails = [
            {"sender": "client@acme.com", "subject": "Project Proposal", "snippet": "Please send the finalized contract by Friday."},
            {"sender": "hr@company.com", "subject": "Benefits update", "snippet": "Annual enrollment starts next month."},
        ]
        with patch.object(self.mail, "read_mail", return_value={"ok": True, "emails": mock_emails}):
            res = self.mail.extract_actions(limit=5)
            self.assertTrue(res["ok"])
            self.assertTrue(len(res["actions"]) >= 1)
            self.assertIn("client@acme.com", res["actions"][0]["sender"])


class TestMasterBuildPersonalAssistant(unittest.TestCase):
    """System 5: Personal Assistant (Tasks, Calendar, Daily Briefing)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        memory = EncryptedMemoryStore(str(Path(self.tmp.name) / "memory.sqlite3"))
        self.orch = CortexOrchestrator(DeviceAutomation(dry_run=False), memory, use_gemini=False)
        self.task_file = Path(self.tmp.name) / "personal_tasks.json"

    def test_personal_task_lifecycle(self):
        with patch.object(self.orch.automation, "_get_task_store_path", return_value=self.task_file):
            # Create a task
            res = self.orch.automation.execute(
                TaskCommand.PERSONAL_TASK_CREATE,
                {"title": "Review PR #42", "due": "Today"},
            )
            self.assertTrue(res.ok)
            self.assertIn("Review PR #42", res.message)

            # Verify task exists
            verified = self.orch.automation.verify_task_created("Review PR #42")
            self.assertTrue(verified)

            # List tasks
            list_res = self.orch.automation.execute(TaskCommand.PERSONAL_TASK_LIST, {})
            self.assertTrue(list_res.ok)
            self.assertEqual(len(list_res.data["tasks"]), 1)
            self.assertEqual(list_res.data["tasks"][0]["title"], "Review PR #42")

    def test_calendar_read(self):
        res = self.orch.automation.execute(TaskCommand.CALENDAR_READ, {"day": "today"})
        self.assertTrue(res.ok)
        self.assertIn("events", res.data)
        self.assertTrue(len(res.data["events"]) > 0)

    def test_daily_briefing(self):
        with patch.object(self.orch.automation, "_get_task_store_path", return_value=self.task_file):
            # Add a pending task
            self.orch.automation.execute(
                TaskCommand.PERSONAL_TASK_CREATE,
                {"title": "Ship Cortex master build", "due": "Today"},
            )
            res = self.orch.automation.execute(TaskCommand.DAILY_BRIEFING, {})
            self.assertTrue(res.ok)
            self.assertIn("briefing", res.data["briefing"].lower())
            self.assertIn("Ship Cortex master build", res.data["briefing"])


class TestMasterBuildUnifiedToolRegistry(unittest.TestCase):
    """System 1: Tool Registry Completeness and Parameters."""

    def test_tool_registry_contains_required_capabilities(self):
        registry = ToolRegistry()
        tools = {t.name: t for t in registry.list_all()}

        expected_tools = [
            "open_application",
            "close_application",
            "web_search",
            "search_files",
            "read_file",
            "write_file",
            "search_mail",
            "email_briefing",
            "calendar_read",
            "calendar_create",
            "personal_task_create",
            "personal_task_list",
            "daily_briefing",
            "calculate_math",
        ]
        for tool_name in expected_tools:
            self.assertIn(tool_name, tools, f"Expected tool '{tool_name}' in ToolRegistry")
            t = tools[tool_name]
            self.assertTrue(bool(t.description))
            self.assertTrue(bool(t.expected_state_desc))


class TestMasterBuildOrchestratorIntegration(unittest.TestCase):
    """End-to-End Orchestrator Chat and Command Routing."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        memory = EncryptedMemoryStore(str(Path(self.tmp.name) / "memory.sqlite3"))
        self.orch = CortexOrchestrator(DeviceAutomation(dry_run=True), memory, use_gemini=False)

    def test_routing_find_file(self):
        cmd = command_from_intent("find file report.pdf in documents")
        self.assertEqual(cmd, TaskCommand.SEARCH_FILES)

    def test_routing_read_file(self):
        cmd = command_from_intent("read file /tmp/notes.txt")
        self.assertEqual(cmd, TaskCommand.READ_FILE)

    def test_routing_email_briefing(self):
        cmd = command_from_intent("give me an email briefing")
        self.assertEqual(cmd, TaskCommand.EMAIL_BRIEFING)

    def test_routing_daily_briefing(self):
        cmd = command_from_intent("what's my day looking like")
        self.assertEqual(cmd, TaskCommand.DAILY_BRIEFING)

    def test_routing_create_task(self):
        cmd = command_from_intent("add task call accountant tomorrow")
        self.assertEqual(cmd, TaskCommand.PERSONAL_TASK_CREATE)

    def test_routing_check_calendar(self):
        cmd = command_from_intent("what meetings do i have today")
        self.assertEqual(cmd, TaskCommand.CALENDAR_READ)
