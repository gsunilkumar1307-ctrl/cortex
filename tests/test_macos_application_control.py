"""Automated regression and unit test suite for Cortex Day 2: Hybrid macOS Application Control.

Covers:
1. Application discovery & alias resolution
2. Distinguishing installed vs running applications
3. Ambiguous target resolution & clarification prompt
4. Unavailable / non-installed application rejection
5. Launch, process verification & duplicate launch prevention
6. Focus & foreground state verification
7. Safe close & unsaved document handling
8. Application status inspection (running, active, background)
9. Screen observation (active app, active window, visible elements with source)
10. Natural-language intent routing for all Day 2 operations
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities.device_actions import (
    APP_ALIASES,
    ApplicationDiscovery,
    DeviceActionResult,
    DeviceAutomation,
)
from backend.capabilities.screen_native import AppInfo, PermissionState, WindowInfo
from backend.core.contracts import (
    RiskLevel,
    TaskCommand,
    TaskStatus,
    command_from_intent,
)
from backend.persistence.encrypted_store import EncryptedMemoryStore


class TestMacOSApplicationControl(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db_path = str(Path(self.tmp.name) / "memory.sqlite3")
        self.memory = EncryptedMemoryStore(db_path)
        self.device = DeviceAutomation(dry_run=True)
        self.orch = CortexOrchestrator(self.device, self.memory, use_gemini=False)

    # ── 1. App Discovery & Resolution ──────────────────────────────

    def test_01_app_discovery_alias_and_canonical_resolution(self) -> None:
        """Recognizes common aliases and canonical application titles."""
        self.assertEqual(self.device.resolve_app_name("calc"), "Calculator")
        self.assertEqual(self.device.resolve_app_name("calculator"), "Calculator")
        self.assertEqual(self.device.resolve_app_name("safari"), "Safari")
        self.assertEqual(self.device.resolve_app_name("notes"), "Notes")
        self.assertEqual(self.device.resolve_app_name("apple mail"), "Mail")
        self.assertEqual(self.device.resolve_app_name("finder"), "Finder")

    def test_02_app_discovery_distinguishes_installed_from_running(self) -> None:
        """Correctly differentiates an application that is installed vs one that is running."""
        discovery = ApplicationDiscovery()
        # Mock installed apps
        mock_installed = {
            "calculator": {"name": "Calculator", "bundle_id": "com.apple.calculator", "path": "/System/Applications/Calculator.app", "is_installed": True},
            "safari": {"name": "Safari", "bundle_id": "com.apple.Safari", "path": "/Applications/Safari.app", "is_installed": True},
        }
        discovery._installed_cache = mock_installed
        discovery._cache_time = 9999999999.0

        # Only Safari is running
        running_apps = [AppInfo(name="Safari", pid=1234, bundle_id="com.apple.Safari", is_active=True)]

        res_safari = discovery.resolve("safari", running_apps=running_apps)
        self.assertEqual(res_safari["status"], "resolved")
        self.assertTrue(res_safari["is_installed"])
        self.assertTrue(res_safari["is_running"])

        res_calc = discovery.resolve("calculator", running_apps=running_apps)
        self.assertEqual(res_calc["status"], "resolved")
        self.assertTrue(res_calc["is_installed"])
        self.assertFalse(res_calc["is_running"])

    def test_03_app_discovery_ambiguous_matches_ask_clarification(self) -> None:
        """When multiple installed applications match a partial name, flags as ambiguous and asks for clarification."""
        discovery = ApplicationDiscovery()
        discovery._installed_cache = {
            "cortex editor": {"name": "Cortex Editor", "bundle_id": "com.cortex.editor", "path": "/Applications/Cortex Editor.app", "is_installed": True},
            "cortex viewer": {"name": "Cortex Viewer", "bundle_id": "com.cortex.viewer", "path": "/Applications/Cortex Viewer.app", "is_installed": True},
        }
        discovery._cache_time = 9999999999.0

        res = discovery.resolve("cortex")
        self.assertEqual(res["status"], "ambiguous")
        self.assertIn("Cortex Editor", res["candidates"])
        self.assertIn("Cortex Viewer", res["candidates"])
        self.assertIn("Multiple applications match", res["message"])

    def test_04_app_discovery_non_installed_app_rejected_honestly(self) -> None:
        """Attempting to open an application not installed reports failure honestly."""
        discovery = ApplicationDiscovery()
        discovery._installed_cache = {}
        discovery._cache_time = 9999999999.0

        res = discovery.resolve("CompletelyFakeAppXYZ")
        self.assertEqual(res["status"], "not_installed")
        self.assertFalse(res["is_installed"])

    # ── 2. Launch & Duplicate Prevention ──────────────────────────

    def test_05_launch_app_fresh_launch(self) -> None:
        """Launching an application when not running returns successful launch."""
        self.device._mock_running_apps = []
        res = self.device.execute(TaskCommand.OPEN_APP, {"appName": "Calculator"})
        self.assertTrue(res.ok)
        self.assertEqual(res.data.get("appName"), "Calculator")
        self.assertFalse(res.data.get("wasRunning", True))

    def test_06_launch_already_running_app_focuses_without_duplication(self) -> None:
        """Launching an application that is already running focuses it instead of duplicating instances."""
        self.device._mock_running_apps = ["Calculator"]
        res = self.device.execute(TaskCommand.OPEN_APP, {"appName": "Calculator"})
        self.assertTrue(res.ok)
        self.assertEqual(res.data.get("appName"), "Calculator")
        self.assertTrue(res.data.get("wasRunning"))
        self.assertIn("Focused already running", res.message)

    # ── 3. Focus Application ──────────────────────────────────────

    def test_07_focus_app_running_brings_to_foreground(self) -> None:
        """Focusing an already running application brings it to front and verifies active state."""
        self.device._mock_running_apps = ["Notes"]
        res = self.device.execute(TaskCommand.FOCUS_APP, {"appName": "Notes"})
        self.assertTrue(res.ok)
        self.assertEqual(res.data.get("appName"), "Notes")
        self.assertTrue(res.data.get("isActive"))

    def test_08_focus_app_not_running_fails_gracefully(self) -> None:
        """Focusing an application that is not running fails honestly without launching a new instance."""
        # Using live simulation in dry_run=False mock mode
        live_device = DeviceAutomation(dry_run=False)
        live_device.screen_bridge.use_mock = True
        live_device.screen_bridge._mock_dispatch = lambda cmd: {
            "ok": True,
            "data": [] if cmd == "apps" else None,
        }
        res = live_device.execute(TaskCommand.FOCUS_APP, {"appName": "Calculator"})
        self.assertFalse(res.ok)
        self.assertIn("not currently running", res.message)

    # ── 4. Safe Close & Unsaved Changes ───────────────────────────

    def test_09_close_app_not_running_is_graceful_noop(self) -> None:
        """Closing an application that is not running succeeds and confirms it was not running."""
        live_device = DeviceAutomation(dry_run=False)
        live_device.screen_bridge.use_mock = True
        live_device.screen_bridge._mock_dispatch = lambda cmd: {
            "ok": True,
            "data": [] if cmd == "apps" else None,
        }
        res = live_device.execute(TaskCommand.CLOSE_APP, {"appName": "Calculator"})
        self.assertTrue(res.ok)
        self.assertIn("not running", res.message)

    def test_10_close_app_with_unsaved_changes_refuses_without_force(self) -> None:
        """Closing an application with unsaved changes refuses to terminate without force."""
        self.device._mock_running_apps = ["TextEdit"]
        self.device._mock_unsaved_changes = ["TextEdit"]
        # In live mode simulation with unsaved changes:
        live_device = DeviceAutomation(dry_run=False)
        live_device.screen_bridge.use_mock = True
        live_device.screen_bridge._mock_dispatch = lambda cmd: {
            "ok": True,
            "data": [{"name": "TextEdit", "pid": 5555, "isActive": True, "isHidden": False}],
        }
        live_device.has_unsaved_changes = lambda app: True
        res = live_device.execute(TaskCommand.CLOSE_APP, {"appName": "TextEdit", "force": False})
        self.assertFalse(res.ok)
        self.assertTrue(res.data.get("hasUnsavedChanges"))
        self.assertIn("unsaved changes", res.message)

    # ── 5. Status Inspection ──────────────────────────────────────

    def test_11_inspect_app_running_status(self) -> None:
        """INSPECT_APP accurately reports whether application is active, background, or not running."""
        self.device._mock_running_apps = ["Mail"]
        res = self.device.execute(TaskCommand.INSPECT_APP, {"appName": "mail"})
        self.assertTrue(res.ok)
        self.assertEqual(res.data.get("appName"), "Mail")
        self.assertTrue(res.data.get("isRunning"))

    # ── 6. Screen Observation ─────────────────────────────────────

    def test_12_screen_observation_includes_sources_and_limitations(self) -> None:
        """Screen observation specifies whether Accessibility or OCR supplied each element."""
        res = self.device.execute(TaskCommand.OBSERVE_SCREEN, {})
        self.assertTrue(res.ok)
        msg = res.message
        self.assertIn("- **Active application:**", msg)
        self.assertIn("- **Active window:**", msg)
        self.assertIn("- **Visible elements:**", msg)
        self.assertIn("- **Limitations:**", msg)

        # Check structured elements in data
        elems = res.data.get("elements", [])
        self.assertGreater(len(elems), 0)
        for el in elems:
            self.assertIn(el.get("source"), ("accessibility", "vision_ocr"))

    # ── 7. Natural-Language Routing ───────────────────────────────

    def test_13_natural_language_intent_routing_coverage(self) -> None:
        """Verifies all Day 2 required phrases map strictly to desktop automation without web search."""
        phrases = [
            ("Open Calculator.", TaskCommand.OPEN_APP),
            ("Launch Safari.", TaskCommand.OPEN_APP),
            ("Bring Finder to the front.", TaskCommand.FOCUS_APP),
            ("Switch to Notes.", TaskCommand.FOCUS_APP),
            ("Is Apple Mail running?", TaskCommand.INSPECT_APP),
            ("Check whether Calculator is running.", TaskCommand.INSPECT_APP),
            ("Close Calculator.", TaskCommand.CLOSE_APP),
            ("What application am I currently using?", TaskCommand.OBSERVE_SCREEN),
            ("Determine which application is active.", TaskCommand.OBSERVE_SCREEN),
            ("Report the active window title.", TaskCommand.OBSERVE_SCREEN),
            ("Observe my screen and describe five visible elements.", TaskCommand.OBSERVE_SCREEN),
        ]
        for phrase, expected_cmd in phrases:
            cmd = command_from_intent(phrase)
            self.assertEqual(
                cmd,
                expected_cmd,
                f"Failed routing '{phrase}': expected {expected_cmd.value}, got {cmd.value}",
            )

    def test_14_orchestrator_chat_e2e_for_inspect_and_focus(self) -> None:
        """End-to-end chat orchestration for inspect and focus commands."""
        # 1. Bring Finder to the front
        res_focus = self.orch.chat("Bring Finder to the front.")
        self.assertEqual(res_focus["task"]["command"], TaskCommand.FOCUS_APP.value)
        self.assertEqual(res_focus["task"]["status"], TaskStatus.COMPLETED.value)
        self.assertEqual(res_focus["task"]["params"]["appName"], "Finder")

        # 2. Is Apple Mail running?
        res_inspect = self.orch.chat("Is Apple Mail running?")
        self.assertEqual(res_inspect["task"]["command"], TaskCommand.INSPECT_APP.value)
        self.assertEqual(res_inspect["task"]["status"], TaskStatus.COMPLETED.value)
        self.assertEqual(res_inspect["task"]["params"]["appName"], "Mail")

    def test_15_screen_observation_filters_unknown_and_negative_one_nodes(self) -> None:
        """Never report [Unknown], -1, empty or invalid accessibility nodes as observed elements."""
        from backend.capabilities.screen_accessibility import AccessibilityPerceptionResult, NormalizedUIElement, NormalizedUIRole
        from backend.capabilities.screen_native import AppInfo, WindowInfo, RectBounds

        mock_app = AppInfo(name="Calculator", pid=9999, bundle_id="com.apple.calculator", is_active=True)
        mock_win = WindowInfo(window_id=1, pid=9999, app_name="Calculator", bounds=RectBounds(0, 0, 400, 600), title="Calculator", is_on_screen=True)

        # Create elements including invalid -1 and unknown role nodes
        valid_el = NormalizedUIElement(
            id="btn_1",
            role=NormalizedUIRole.BUTTON,
            raw_ax_role="AXButton",
            path="AXApplication/AXWindow/AXButton",
            title="Mode",
            bounds=RectBounds(10, 10, 50, 30),
            is_interactive=True,
        )
        invalid_role_el = NormalizedUIElement(
            id="bad_role",
            role=NormalizedUIRole.UNKNOWN,
            raw_ax_role="AXUnknown",
            path="AXApplication/AXWindow/AXUnknown",
            title="Random",
        )
        invalid_val_el = NormalizedUIElement(
            id="bad_val",
            role=NormalizedUIRole.BUTTON,
            raw_ax_role="AXButton",
            path="AXApplication/AXWindow/AXButton",
            title="-1",
        )

        mock_ax_res = AccessibilityPerceptionResult(
            ok=True,
            app=mock_app,
            window=mock_win,
            elements=[valid_el, invalid_role_el, invalid_val_el],
        )

        with patch.object(self.device.ax_engine, "inspect_current_application", return_value=mock_ax_res), \
             patch.object(self.device.screen_bridge, "get_permissions", return_value=PermissionState(accessibility=True, screen_recording=True, status_message="Granted")):
            obs = self.device._observe_screen(capture=False, run_ocr=False)
            self.assertTrue(obs.ok)
            vis = obs.data.get("visible_elements", [])
            # Must contain Mode
            self.assertTrue(any("Mode" in item for item in vis))
            # Must NOT contain [Unknown] or -1
            self.assertFalse(any("[Unknown]" in item for item in vis))
            self.assertFalse(any(" -1 " in item or item.endswith("-1") for item in vis))


if __name__ == "__main__":
    unittest.main()

