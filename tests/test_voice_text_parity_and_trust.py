import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.persistence.encrypted_store import EncryptedMemoryStore
from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities import DeviceAutomation
from backend.api.server import app, orchestrator


class TestVoiceTextParityAndTrust(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = TestClient(app)

    def test_voice_and_text_parity_in_planning_and_approval(self):
        """Verifies voice and text routes produce identical tasks and approval requirements."""
        # 1. Text request
        res_text = self.client.post("/chat", json={
            "message": "send email to advisor@university.edu saying Meeting tomorrow",
            "source": "text",
        })
        self.assertEqual(res_text.status_code, 200)
        data_text = res_text.json()
        task_text = data_text["task"]

        self.assertEqual(task_text["status"], "waiting_approval")
        self.assertTrue(task_text["requiresApproval"])
        hash_text = task_text["params"]["approval_hash"]
        self.assertTrue(bool(hash_text))

        # 2. Voice request (simulated audio)
        with patch("backend.api.server.transcribe_audio_multilingual") as mock_stt:
            mock_stt.return_value = "send email to advisor@university.edu saying Meeting tomorrow"
            dummy_wav = b"RIFF" + b"\x00" * 40 + b"data" + b"\x00" * 500
            res_voice = self.client.post(
                "/audio_chat",
                content=dummy_wav,
                headers={"Content-Type": "audio/wav"},
            )
            self.assertEqual(res_voice.status_code, 200)
            data_voice = res_voice.json()
            task_voice = data_voice["task"]

            self.assertEqual(task_voice["status"], "waiting_approval")
            self.assertTrue(task_voice["requiresApproval"])
            hash_voice = task_voice["params"]["approval_hash"]
            self.assertTrue(bool(hash_voice))

            # Both text and voice must compute exact same approval hash for same payload
            self.assertEqual(hash_text, hash_voice)

    def test_rejection_halts_execution_without_side_effects(self):
        res = self.client.post("/chat", json={
            "message": "send email to client@corp.com saying Proposal attached",
            "source": "voice",
        })
        task_id = res.json()["task"]["id"]

        # User rejects proposed action
        res_approve = self.client.post(f"/tasks/{task_id}/approve", json={"approved": False})
        self.assertEqual(res_approve.status_code, 200)
        task = res_approve.json()

        self.assertEqual(task["status"], "canceled")
        self.assertIn("rejected", (task.get("result") or "").lower())

    def test_parameter_change_invalidates_prior_hash(self):
        res = self.client.post("/chat", json={
            "message": "send email to ceo@startup.io saying Q3 financial numbers",
            "source": "text",
        })
        task_id = res.json()["task"]["id"]
        initial_hash = res.json()["task"]["params"]["approval_hash"]

        # Edit the draft body
        res_edit = self.client.post(f"/tasks/{task_id}/edit", json={
            "recipient": "ceo@startup.io",
            "subject": "Q3 financial numbers",
            "body": "Updated financial summary: Revenue up 34%",
        })
        self.assertEqual(res_edit.status_code, 200)
        updated_task = res_edit.json()["task"]
        updated_hash = updated_task["params"]["approval_hash"]

        # Prior approval hash MUST be invalidated
        self.assertNotEqual(initial_hash, updated_hash)
        self.assertEqual(updated_task["status"], "waiting_approval")

    def test_missing_or_blank_input_returns_400(self):
        res = self.client.post("/chat", json={"message": "   "})
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
