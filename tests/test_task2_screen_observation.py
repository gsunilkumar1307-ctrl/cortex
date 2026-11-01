"""Tests for Cortex Agent Task 2: Live macOS Screen Observation.

Covers:
- Valid screen-observation structured results
- Missing active window handling (no inference from app name)
- Accessibility permission denied (fails closed)
- Screen capture permission denied (honest limitation reporting)
- OCR returning no text
- Native helper failure handling
- Partial observations (honest count, no padding)
- Sensitive value redaction
- Multilingual and varied phrasing intent routing
- Real macOS empirical live execution
"""

from __future__ import annotations

import platform
import unittest
from unittest.mock import MagicMock, patch

from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities import DeviceAutomation
from backend.core.contracts import TaskCommand, TaskStatus
from tests.test_unified_dual_intelligence import create_orchestrator


class TestTask2ScreenObservation(unittest.TestCase):
    """Screen observation regression and validation test suite."""

    # 1. Valid screen-observation results [MOCKED]
    def test_01_mock_valid_screen_observation_returns_structured_result(self) -> None:
        orch = create_orchestrator(dry_run=True)
        res = orch.chat("Observe my screen and tell me the active application, active window, and five visible elements.")
        self.assertEqual(res["task"]["command"], "observe_screen")
        self.assertEqual(res["task"]["status"], "completed")

        msg = res["message"]
        self.assertIn("- **Active application:**", msg)
        self.assertIn("- **Active window:**", msg)
        self.assertIn("- **Visible elements:**", msg)
        self.assertIn("- **Limitations:**", msg)

        # Grounded in mock helper values (Mail, Inbox, New Message, etc.)
        self.assertIn("Mail", msg)
        self.assertIn("Inbox (2 messages)", msg)
        self.assertIn("New Message", msg)
        self.assertIn("Delete Account", msg)
        self.assertIn("Compose", msg)
        self.assertIn("Limitations:** None", msg)

    # 2. Missing active window [MOCKED]
    def test_02_mock_missing_active_window_reports_unavailable_without_inference(self) -> None:
        orch = create_orchestrator(dry_run=True)
        # Inject empty window list and untitled AX tree into mock bridge
        bridge = orch.automation.screen_bridge
        bridge._mock_windows = []
        bridge._mock_ax_elements = [
            {"id": "AXApplication_0_0", "role": "AXApplication", "title": "Mail", "path": "0", "depth": 0, "actions": [], "isEnabled": True},
            {"id": "AXButton_1_1", "role": "AXButton", "title": "Check Mail", "path": "0/0", "depth": 1, "actions": ["AXPress"], "isEnabled": True},
        ]

        res = orch.chat("Observe my screen and tell me the active application, active window, and five visible elements.")
        msg = res["message"]

        self.assertIn("- **Active application:** Mail", msg)
        # Must report Unavailable and NEVER infer window title from application name
        self.assertIn("- **Active window:** Unavailable", msg)
        self.assertNotIn("- **Active window:** Mail", msg)
        self.assertIn("Limitations:**", msg)
        self.assertIn("No active window title found", msg)

    # 3. Accessibility permission denied [MOCKED]
    def test_03_mock_accessibility_permission_denied_fails_closed(self) -> None:
        orch = create_orchestrator(dry_run=True)
        bridge = orch.automation.screen_bridge
        bridge._mock_permissions = {
            "accessibility": False,
            "screenRecording": True,
            "statusMessage": "Accessibility: DENIED",
        }

        res = orch.chat("Observe my screen and tell me the active application, active window, and five visible elements.")
        task = res["task"]

        self.assertEqual(task["status"], TaskStatus.FAILED.value)
        msg = res["message"]
        self.assertIn("- **Active window:** Unavailable", msg)
        self.assertIn("- **Visible elements:** None", msg)
        self.assertIn("Accessibility permission denied", msg)

    # 4. Screen capture permission denied [MOCKED]
    def test_04_mock_screen_capture_permission_denied_preserves_ax_elements_reports_limitation(self) -> None:
        orch = create_orchestrator(dry_run=True)
        bridge = orch.automation.screen_bridge
        bridge._mock_permissions = {
            "accessibility": True,
            "screenRecording": False,
            "statusMessage": "Screen Recording: DENIED",
        }

        res = orch.chat("Observe my screen and tell me the active application, active window, and five visible elements.")
        msg = res["message"]

        self.assertEqual(res["task"]["status"], "completed")
        self.assertIn("- **Active application:** Mail", msg)
        self.assertIn("- **Active window:** Inbox (2 messages)", msg)
        self.assertIn("Screen recording permission denied", msg)

    # 5. OCR returning no text [MOCKED]
    def test_05_mock_ocr_returning_no_text(self) -> None:
        orch = create_orchestrator(dry_run=True)
        bridge = orch.automation.screen_bridge
        bridge._mock_ocr = []

        res = orch.chat("Observe my screen and tell me the active application, active window, and five visible elements.")
        self.assertEqual(res["task"]["status"], "completed")
        msg = res["message"]
        self.assertIn("- **Active application:** Mail", msg)
        # Semantic AX elements are still present
        self.assertIn("New Message", msg)

    # 6. Capture or native helper failure [MOCKED]
    def test_06_mock_native_helper_failure_fails_closed(self) -> None:
        orch = create_orchestrator(dry_run=True)
        bridge = orch.automation.screen_bridge
        bridge._mock_failure = True
        bridge._mock_failure_error = "Process terminated unexpectedly."

        res = orch.chat("Observe my screen and tell me the active application, active window, and five visible elements.")
        task = res["task"]
        self.assertEqual(task["status"], TaskStatus.FAILED.value)
        msg = res["message"]
        self.assertIn("Unavailable", msg)
        self.assertIn("Process terminated unexpectedly", msg)

    # 7. Partial observations (honest count, no fabricated padding) [MOCKED]
    def test_07_mock_partial_observations_caps_at_available_elements(self) -> None:
        orch = create_orchestrator(dry_run=True)
        bridge = orch.automation.screen_bridge
        # Inject only 2 elements in AX tree and empty OCR
        bridge._mock_ax_elements = [
            {"id": "AXApplication_0_0", "role": "AXApplication", "title": "Notes", "path": "0", "depth": 0, "actions": [], "isEnabled": True},
            {"id": "AXButton_1_1", "role": "AXButton", "title": "New Note", "descriptionText": "Create note", "path": "0/0", "depth": 1, "actions": ["AXPress"], "bounds": {"x": 10, "y": 10, "width": 50, "height": 30}, "isEnabled": True},
        ]
        bridge._mock_ocr = []

        res = orch.chat("Observe my screen and tell me the active application, active window, and five visible elements.")
        msg = res["message"]

        self.assertIn("[Application] Notes", msg)
        self.assertIn("[Button] New Note", msg)
        # Must not contain 3rd, 4th, or 5th fabricated elements
        self.assertNotIn("3.", msg)
        self.assertIn("Only 2 visible elements could be identified", msg)

    # 8. Prevention of returning sensitive content [MOCKED]
    def test_08_mock_sensitive_information_redacted(self) -> None:
        orch = create_orchestrator(dry_run=True)
        bridge = orch.automation.screen_bridge
        bridge._mock_ax_elements = [
            {"id": "AXApplication_0_0", "role": "AXApplication", "title": "App", "path": "0", "depth": 0, "actions": [], "isEnabled": True},
            {"id": "AXTextField_1_1", "role": "AXTextField", "title": "User password: secret_12345", "path": "0/0", "depth": 1, "actions": [], "isEnabled": True},
            {"id": "AXButton_1_2", "role": "AXButton", "title": "Submit", "path": "0/1", "depth": 1, "actions": ["AXPress"], "isEnabled": True},
        ]
        bridge._mock_ocr = []

        res = orch.chat("Observe my screen and tell me the active application, active window, and five visible elements.")
        msg = res["message"]

        self.assertNotIn("secret_12345", msg)
        self.assertIn("[Button] Submit", msg)

    # 9. Multilingual and varied phrasing intent routing [MOCKED]
    def test_09_multilingual_and_varied_intent_routing(self) -> None:
        orch = create_orchestrator(dry_run=True)

        phrases = [
            "observe screen",
            "inspect my screen",
            "scan the screen",
            "tell me the active application, active window, and five visible elements",
            "ನನ್ನ ಸ್ಕ್ರೀನ್ ನೋಡು",
            "मेरी स्क्रीन देखो",
        ]

        for p in phrases:
            res = orch.chat(p)
            self.assertEqual(
                res["task"]["command"],
                TaskCommand.OBSERVE_SCREEN.value,
                f"Failed to route '{p}' to OBSERVE_SCREEN",
            )

    # 10. Real macOS empirical live execution [LIVE]
    @unittest.skipUnless(platform.system().lower() == "darwin", "Requires macOS for live test")
    def test_10_live_macos_screen_observation_empirical_verification(self) -> None:
        orch = create_orchestrator(dry_run=False)
        res = orch.chat("Observe my screen and tell me the active application, active window, and five visible elements.")

        self.assertEqual(res["task"]["command"], "observe_screen")
        self.assertEqual(res["task"]["status"], "completed")

        msg = res["message"]
        self.assertIn("- **Active application:**", msg)
        self.assertIn("- **Active window:**", msg)
        self.assertIn("- **Visible elements:**", msg)
        self.assertIn("- **Limitations:**", msg)

        # Confirm that observation was empirically grounded, not hardcoded
        obs_data = res["task"]["params"].get("app")
        self.assertIsNotNone(obs_data)
        self.assertIsInstance(obs_data.get("name"), str)
        self.assertGreater(len(obs_data.get("name")), 0)


if __name__ == "__main__":
    unittest.main()
