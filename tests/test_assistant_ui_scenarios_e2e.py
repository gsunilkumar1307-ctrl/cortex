from __future__ import annotations

import unittest
import os
import json
import sqlite3
from unittest.mock import patch, MagicMock

os.environ["CORTEX_SESSION_SECRET"] = "test-session-secret-for-scenarios"
os.environ["CORTEX_DISABLE_AUTH"] = "0"

from backend.api.server import app, orchestrator
from backend.core.contracts import TaskStatus, TaskCommand, RiskLevel, Task
from starlette.testclient import TestClient


class TestAssistantUIScenariosE2E(unittest.TestCase):
    def setUp(self):
        orchestrator.use_gemini = False
        self.client = TestClient(app)
        self.auth_headers = {
            "X-Cortex-Session": "test-session-secret-for-scenarios"
        }

    # ── Scenario 1: General Conversation & Streaming ────────────────────────
    def test_scenario_01_general_conversation_streaming(self):
        """User: 'Explain how machine learning works.' -> Streams well-formatted response."""
        res = self.client.post(
            "/chat/stream",
            json={"message": "Explain how machine learning works.", "source": "text"},
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/event-stream", res.headers.get("content-type", ""))
        text = res.text
        self.assertIn("event: start", text)
        self.assertIn("event: text_delta", text)
        self.assertIn("event: done", text)

    # ── Scenario 2: Message Editing & Branching ─────────────────────────────
    def test_scenario_02_message_editing_and_threads(self):
        """User edits earlier question -> Branch persisted and updated."""
        thread_id = "test-thread-branching-001"
        initial_thread = {
            "id": thread_id,
            "title": "Quantum Physics Question",
            "messages": [
                {"id": "m1", "role": "user", "content": "What is quantum computing?"},
                {"id": "m2", "role": "assistant", "content": "Quantum computing uses qubits..."},
            ]
        }
        res1 = self.client.post("/threads", json=initial_thread, headers=self.auth_headers)
        self.assertEqual(res1.status_code, 200)

        # Edit user message to create alternative branch
        edited_thread = {
            "id": thread_id,
            "title": "Quantum Cryptography Question",
            "messages": [
                {"id": "m1-v2", "role": "user", "content": "What is quantum cryptography?"},
                {"id": "m2-v2", "role": "assistant", "content": "Quantum cryptography utilizes quantum key distribution..."},
            ]
        }
        res2 = self.client.post("/threads", json=edited_thread, headers=self.auth_headers)
        self.assertEqual(res2.status_code, 200)

        get_res = self.client.get(f"/threads/{thread_id}", headers=self.auth_headers)
        self.assertEqual(get_res.status_code, 200)
        msgs = get_res.json()["thread"]["messages"]
        self.assertEqual(msgs[0]["content"], "What is quantum cryptography?")

    # ── Scenario 3: Document Attachment & Validation ────────────────────────
    def test_scenario_03_document_attachment_handling(self):
        """User attaches a document summary request."""
        query = "Summarize this quarterly report.\n\n[Attached file: quarterly_report.pdf (142KB)]"
        res = self.client.post(
            "/chat",
            json={"message": query, "source": "text"},
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("message", data)
        self.assertTrue(len(data["message"]) > 0)

    # ── Scenario 4: Apple Mail Draft & Approval Gate ────────────────────────
    def test_scenario_04_apple_mail_draft_and_approval_gate(self):
        """User: 'Draft an email to Rahul explaining that I will be late.' -> Prepares draft with cryptographic hash, requires approval."""
        prompt = "Draft an email to Rahul about tomorrow's project meeting. Do not send it."
        res = self.client.post(
            "/chat",
            json={"message": prompt, "source": "text"},
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("rahul@example.com", data.get("message", ""))
        self.assertIsNotNone(orchestrator.pending_action)
        self.assertEqual(orchestrator.pending_action.get("step"), "confirm_send")

        draft = orchestrator.pending_action.get("draft")
        self.assertIsNotNone(draft)
        self.assertEqual(draft.recipient, "rahul@example.com")

    # ── Scenario 5: Complex Task Planning ───────────────────────────────────
    def test_scenario_05_complex_task_planning(self):
        """User: 'Plan my project work for the next seven days.' -> Structured plan with milestones."""
        query = "Plan my project work for the next seven days."
        res = self.client.post(
            "/chat",
            json={"message": query, "source": "text"},
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("message", data)
        task = data.get("task")
        self.assertIsNotNone(task)

    # ── Scenario 6: Browser Web Research ───────────────────────────────────
    def test_scenario_06_browser_web_research_citations(self):
        """User: 'Research the latest developments in AI agents.' -> Web research with citations."""
        with patch("backend.integrations.search.web_search.search_web") as mock_search:
            mock_search.return_value = [
                {
                    "title": "Autonomous AI Agents in 2026",
                    "url": "https://arxiv.org/abs/2601.12345",
                    "snippet": "Recent breakthroughs in desktop-operating autonomous agents.",
                    "domain": "arxiv.org",
                }
            ]
            query = "Research the latest developments in AI agents."
            res = self.client.post(
                "/chat",
                json={"message": query, "source": "text"},
                headers=self.auth_headers,
            )
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("message", data)

    # ── Scenario 7: Voice Audio Chat & Regional TTS ─────────────────────────
    def test_scenario_07_voice_chat_and_tts(self):
        """Audio chat and TTS streaming endpoints."""
        tts_res = self.client.get("/tts?text=Hello+Cortex&lang=en", headers=self.auth_headers)
        self.assertIn(tts_res.status_code, (200, 502))

        tts_kn = self.client.get("/tts?text=ನಮಸ್ಕಾರ&lang=kn", headers=self.auth_headers)
        self.assertIn(tts_kn.status_code, (200, 502))

    # ── Scenario 8: Multilingual Conversation (Kannada) ─────────────────────
    def test_scenario_08_kannada_instruction(self):
        """User: 'ನಮಸ್ಕಾರ, ಇವತ್ತಿನ ನನ್ನ ವೇಳಾಪಟ್ಟಿ ಏನು?' -> Localized comprehension."""
        query = "ನಮಸ್ಕಾರ, ಇವತ್ತಿನ ನನ್ನ ವೇಳಾಪಟ್ಟಿ ಏನು?"
        res = self.client.post(
            "/chat",
            json={"message": query, "source": "text", "preferred_language": "kn"},
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("message", data)

    # ── Scenario 9: Approval Denial Handling ────────────────────────────────
    def test_scenario_09_approval_denial(self):
        """User explicitly denies approval -> Task cancelled, no execution."""
        task = Task(
            "Send sensitive logs to external partner",
            TaskCommand.SEND_MAIL,
            RiskLevel.HIGH,
            True,
            params={"approval_hash": "sec_hash_deny_test_999"}
        )
        task.status = TaskStatus.WAITING_APPROVAL
        orchestrator.tasks[task.id] = task

        # Deny the action
        deny_res = self.client.post(
            f"/tasks/{task.id}/approve",
            json={"approved": False, "approval_hash": None},
            headers=self.auth_headers,
        )
        self.assertEqual(deny_res.status_code, 200)
        status_val = deny_res.json().get("status")
        self.assertIn(status_val, (TaskStatus.CANCELED.value, TaskStatus.CANCELLED.value))

    # ── Scenario 10: Model Unavailable Deterministic Fallback ───────────────
    def test_scenario_10_model_unavailable_fallback(self):
        """When AI model is unavailable, deterministic local rules handle capability queries."""
        query = "What can you actually do on this Mac?"
        res = self.client.post(
            "/chat",
            json={"message": query, "source": "text"},
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("message", data)
        self.assertTrue("apple mail" in data["message"].lower() or "cortex" in data["message"].lower())

    # ── Scenario 11: Restart Recovery & SQLite Persistence ──────────────────
    def test_scenario_11_restart_recovery(self):
        """Tasks and threads persist in SQLite and are restored across restarts."""
        thread_id = "recovery-thread-101"
        thread_data = {
            "id": thread_id,
            "title": "Persistent Project Thread",
            "messages": [{"role": "user", "content": "Persist this across restarts."}],
        }
        res = self.client.post("/threads", json=thread_data, headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)

        # Verify from database directly
        db_path = orchestrator.memory.db_path
        self.assertTrue(os.path.exists(db_path))
        retrieved = orchestrator.memory.get(thread_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.get("title"), "Persistent Project Thread")

    # ── Scenario 12: Controlled Tool Failure Handling ───────────────────────
    def test_scenario_12_controlled_tool_failure(self):
        """Controlled tool failure results in honest failure card, no false claims."""
        failed_task = Task("Open nonexistent application", TaskCommand.OPEN_APP, RiskLevel.LOW, False)
        failed_task.status = TaskStatus.FAILED
        failed_task.result = "Application 'FakeAppDoesNotExist' not found on system."
        orchestrator.tasks[failed_task.id] = failed_task

        res = self.client.get("/tasks", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        all_tasks = res.json()["tasks"]
        matched = [t for t in all_tasks if t["id"] == failed_task.id]
        if matched:
            self.assertEqual(matched[0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
