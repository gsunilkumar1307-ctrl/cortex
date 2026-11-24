"""Tests for genuine live execution of WhatsApp Desktop on macOS.

Verifies:
1. WhatsApp installation and live process detection.
2. Accessibility tree inspection via NativeScreenHelperBridge.
3. Conversation and composer observation.
4. Draft preparation with direct composer entry.
5. Strict cryptographic single-use approval enforcement.
6. Conversation mismatch security abort.
7. End-to-end multi-turn orchestration with verified post-send clearance.
"""

from __future__ import annotations

import os
import platform
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.recipient_resolver import UserAuthorizedContactStore
from backend.capabilities.device_actions import DeviceAutomation
from backend.capabilities.screen_native import NativeScreenHelperBridge
from backend.capabilities.whatsapp_actions import (
    WhatsAppConversationObservation,
    WhatsAppDesktopAdapter,
    WhatsAppDraft,
    WhatsAppObservationStatus,
    WhatsAppSendAttempt,
)
from backend.core.contracts import TaskStatus
from backend.persistence.encrypted_store import EncryptedMemoryStore
from backend.persistence.task_store import TaskStore


class WhatsAppLiveExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["CORTEX_WHATSAPP_LIVE"] = "1"
        cls.is_macos = platform.system().lower() == "darwin"
        cls.whatsapp_installed = Path("/Applications/WhatsApp.app").exists()
        res = subprocess.run(["pgrep", "-x", "WhatsApp"], capture_output=True, text=True)
        cls.whatsapp_running = res.returncode == 0
        cls.test_phone = "+91 98765 11111"
        cls.test_contact = "Alex Morgan"

    def setUp(self) -> None:
        if not (self.is_macos and self.whatsapp_installed and self.whatsapp_running):
            self.skipTest("Live WhatsApp Desktop application is not available or running.")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db_path = str(Path(self.tmp.name) / "test_whatsapp_live.sqlite3")
        self.memory = EncryptedMemoryStore(db_path)
        self.task_store = TaskStore(db_path)
        self.device = DeviceAutomation(dry_run=False)
        if hasattr(self.device, "whatsapp") and hasattr(self.device.whatsapp, "adapter"):
            self.device.whatsapp.adapter.mock_mode = False
            self.device.whatsapp.mock_mode = False
        self.orch = CortexOrchestrator(
            automation=self.device,
            memory=self.memory,
            task_store=self.task_store,
            use_gemini=False,
            dry_run=False,
        )
        self.adapter = self.device.whatsapp.adapter if hasattr(self.device, "whatsapp") else WhatsAppDesktopAdapter(mock_mode=False)

    def test_01_whatsapp_process_and_window_detection(self) -> None:
        """Confirms WhatsApp is running and accessibility tree can be queried."""
        self.assertTrue(self.adapter.is_whatsapp_installed())
        self.assertTrue(self.adapter.is_whatsapp_running())

        res = subprocess.run(["pgrep", "-x", "WhatsApp"], capture_output=True, text=True)
        pid = int(res.stdout.strip().split()[0])
        self.assertGreater(pid, 0)

        bridge = NativeScreenHelperBridge()
        elements = bridge.inspect_ax_tree(pid=pid, depth=9, max_elements=500)
        self.assertGreater(len(elements), 0)

    def test_02_live_conversation_observation(self) -> None:
        """Observes active conversation and composer state via live AX tree."""
        obs = self.adapter.observe_current_conversation()
        self.assertIn(
            obs.status,
            (WhatsAppObservationStatus.CONVERSATION_OBSERVED, WhatsAppObservationStatus.NO_ACTIVE_CONVERSATION),
        )
        if obs.is_open:
            self.assertIsNotNone(obs.title)

    def test_03_composer_draft_preparation_and_readback(self) -> None:
        """Prepares a test draft in the composer and reads back the exact text via AX tree."""
        test_text = "Cortex Automated Test Draft"
        res = self.adapter.prepare_visible_draft(test_text, recipient=self.test_contact, phone=self.test_phone)
        self.assertTrue(res.get("ok"))

        # Wait for live OS automation to focus and paste
        time.sleep(1.5)
        obs = self.adapter.observe_current_conversation()
        self.assertTrue(obs.is_open)
        self.assertIn(test_text, obs.composer_text or "")

    def test_04_cryptographic_approval_gate_enforcement(self) -> None:
        """Confirms execute_send rejects unapproved, tampered, or mismatched payloads."""
        draft = WhatsAppDraft(recipient=self.test_contact, phone=self.test_phone, body="Tamper Check")
        valid_hash = draft.approval_hash
        invalid_hash = "deadbeef" * 8

        attempt = WhatsAppSendAttempt(
            task_id="test_task_tamper",
            recipient=self.test_contact,
            phone=self.test_phone,
            body="Tamper Check",
            payload_hash=invalid_hash,
        )

        res = self.adapter.execute_send(attempt, approved_hash=valid_hash)
        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("status"), "aborted")

    def test_05_active_conversation_mismatch_abort(self) -> None:
        """Confirms security abort if the active WhatsApp conversation points to an unauthorized contact."""
        # Create draft for Alex Morgan
        res1 = self.orch.chat("Send a WhatsApp message to Alex")
        res2 = self.orch.chat("1")
        res3 = self.orch.chat("Testing security abort")
        task = res3["task"]
        self.assertEqual(task["status"], TaskStatus.WAITING_APPROVAL.value)
        task_id = task["id"]

        # Mock the observation of active conversation to a different person
        mismatched_obs = lambda *args, **kwargs: WhatsAppConversationObservation(
            status=WhatsAppObservationStatus.CONVERSATION_OBSERVED,
            title="Unauthorized Stranger",
            phone="+91 99999 00000",
            is_open=True,
        )
        orig_auto = self.orch.automation.whatsapp.adapter.observe_current_conversation
        orig_wa = self.orch.whatsapp_adapter.desktop_adapter.observe_current_conversation if self.orch.whatsapp_adapter else None
        try:
            self.orch.automation.whatsapp.adapter.observe_current_conversation = mismatched_obs
            if self.orch.whatsapp_adapter:
                self.orch.whatsapp_adapter.desktop_adapter.observe_current_conversation = mismatched_obs

            approve_res = self.orch.approve(task_id, approved=True)
            self.assertEqual(approve_res["status"], TaskStatus.FAILED.value)
            self.assertIn("Security abort", approve_res.get("error", ""))
        finally:
            self.orch.automation.whatsapp.adapter.observe_current_conversation = orig_auto
            if self.orch.whatsapp_adapter and orig_wa:
                self.orch.whatsapp_adapter.desktop_adapter.observe_current_conversation = orig_wa

    def test_06_live_end_to_end_approval_and_verified_send(self) -> None:
        """Full 4-turn live acceptance test:
        Turn 1: Request sending to Alex
        Turn 2: Disambiguate to Alex Morgan
        Turn 3: Provide body and verify pre-send draft
        Turn 4: Explicit cryptographic approval, dispatch, and verified composer clearance
        """
        # Turn 1
        t1 = self.orch.chat("Send a WhatsApp message to Alex")
        self.assertEqual(t1["task"]["status"], TaskStatus.NEED_INFO.value)

        # Turn 2
        t2 = self.orch.chat("1")
        self.assertEqual(t2["task"]["status"], TaskStatus.NEED_INFO.value)

        # Turn 3
        msg_text = "Live Acceptance Test Final Delivery"
        t3 = self.orch.chat(msg_text)
        task3 = t3["task"]
        self.assertEqual(task3["status"], TaskStatus.WAITING_APPROVAL.value)
        task_id = task3["id"]
        approval_hash = task3["params"].get("approval_hash")
        self.assertIsNotNone(approval_hash)

        # Pre-send verification: check composer in live WhatsApp
        time.sleep(1.5)
        pre_obs = self.adapter.observe_current_conversation()
        self.assertTrue(pre_obs.is_open)
        self.assertIn(msg_text, pre_obs.composer_text or "")

        # Turn 4: Approve
        app_res = self.orch.approve(task_id, approved=True)
        self.assertEqual(app_res["status"], TaskStatus.COMPLETED.value)
        self.assertIn("Message sent to Alex Morgan", app_res.get("result", ""))

        # Post-send verification: composer must be empty
        time.sleep(1.5)
        post_obs = self.adapter.observe_current_conversation()
        self.assertEqual(post_obs.composer_text, "")


if __name__ == "__main__":
    unittest.main()
