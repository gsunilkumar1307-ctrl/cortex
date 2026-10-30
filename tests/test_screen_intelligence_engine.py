from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from backend.capabilities.screen_native import (
    NativeScreenHelperBridge,
    RectBounds,
    AppInfo,
    WindowInfo,
    AXElementInfo,
    OCRObservation,
    PermissionState,
)
from backend.capabilities.screen_accessibility import (
    AccessibilityInspectionEngine,
    NormalizedUIElement,
    NormalizedUIRole,
    AccessibilityPerceptionResult,
)
from backend.capabilities.screen_context import (
    ScreenContextFusionEngine,
    ScreenContext,
    OCRBlock,
    PerceptionSource,
)
from backend.capabilities.screen_vision_intelligence import (
    MultimodalVisualIntelligenceEngine,
    VisualInterpretationResult,
)
from backend.capabilities.screen_element_resolver import (
    UIElementResolver,
    ResolvedElementTarget,
)
from backend.capabilities.screen_interaction_engine import (
    DesktopInteractionEngine,
    InteractionRequest,
    InteractionMethod,
)
from backend.capabilities.app_capability_registry import (
    ApplicationCapabilityRegistry,
    SupportedInterfaceMode,
)
from backend.persistence.task_store import TaskStore
from backend.core.contracts import Task, TaskCommand, RiskLevel, TaskStatus
from backend.agent.orchestrator import CortexOrchestrator


class TestScreenIntelligenceEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.bridge = NativeScreenHelperBridge(use_mock=True)
        self.ax_engine = AccessibilityInspectionEngine(self.bridge)
        self.fusion = ScreenContextFusionEngine(self.bridge)
        self.resolver = UIElementResolver()
        self.interaction = DesktopInteractionEngine(
            bridge=self.bridge,
            ax_engine=self.ax_engine,
            fusion_engine=self.fusion,
            resolver=self.resolver,
        )

    def test_01_native_bridge_mock_dispatch(self) -> None:
        perms = self.bridge.get_permissions()
        self.assertTrue(perms.accessibility)
        self.assertTrue(perms.screen_recording)

        app = self.bridge.get_frontmost_app()
        self.assertIsNotNone(app)
        self.assertEqual(app.name, "Mail")

        windows = self.bridge.list_windows()
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].app_name, "Mail")

        elements = self.bridge.inspect_ax_tree()
        self.assertEqual(len(elements), 4)
        self.assertEqual(elements[0].role, "AXApplication")

        ocr_obs = self.bridge.run_ocr("/tmp/fake.png")
        self.assertEqual(len(ocr_obs), 1)
        self.assertEqual(ocr_obs[0].text, "Compose")

    def test_02_accessibility_normalization_and_roles(self) -> None:
        res = self.ax_engine.inspect_current_application()
        self.assertTrue(res.ok)
        self.assertEqual(len(res.elements), 4)

        btn = res.elements[2]
        self.assertEqual(btn.role, NormalizedUIRole.BUTTON)
        self.assertTrue(btn.is_interactive)
        self.assertEqual(btn.inferred_label, "New Message")
        self.assertIn("AXPress", btn.supported_actions)

        found = res.find_by_label("Compose")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].id, "AXButton_2_2")

    def test_03_context_fusion_and_freshness(self) -> None:
        ax_res = self.ax_engine.inspect_current_application()
        ctx = self.fusion.fuse(ax_res, task_context={"goal": "send email"})

        self.assertTrue(ctx.is_fresh(max_age_seconds=5.0))
        dist = ctx.distinguish_facts_and_inferences()
        self.assertGreater(len(dist["observed_facts"]), 0)
        self.assertGreater(len(dist["model_inferences"]), 0)

        # Invalidation test
        ctx.invalidate()
        self.assertFalse(ctx.is_fresh())

    def test_04_ui_element_resolver_exact_and_inferred(self) -> None:
        ax_res = self.ax_engine.inspect_current_application()
        ctx = self.fusion.fuse(ax_res)

        # Exact match
        r1 = self.resolver.resolve_target(ctx, "New Message")
        self.assertTrue(r1.ok)
        self.assertEqual(r1.resolution_method, "accessibility_exact")
        self.assertEqual(r1.element.id, "AXButton_2_2")

        # Inferred / description match
        r2 = self.resolver.resolve_target(ctx, "Compose button")
        self.assertTrue(r2.ok)
        self.assertIn("accessibility", r2.resolution_method)

        # Missing element fails closed
        r3 = self.resolver.resolve_target(ctx, "Random Nonexistent Button 999")
        self.assertFalse(r3.ok)
        self.assertEqual(r3.resolution_method, "no_match")

    def test_05_ocr_spatial_correlation_fallback(self) -> None:
        # Create element with generic uninformative title
        generic_el = NormalizedUIElement(
            id="btn_generic",
            role=NormalizedUIRole.BUTTON,
            raw_ax_role="AXButton",
            path="0/0/9",
            title=None,
            inferred_label="button_AXButton_0_9",
            bounds=RectBounds(x=100.0, y=100.0, width=80.0, height=30.0),
            is_enabled=True,
            is_interactive=True,
            supported_actions=["AXPress"],
        )
        # Create OCR block inside the element bounds
        ocr_block = OCRBlock(
            text="Send Draft",
            confidence=0.98,
            bounds=RectBounds(x=110.0, y=105.0, width=60.0, height=20.0),
            normalized_bounds=RectBounds(x=0.1, y=0.1, width=0.1, height=0.05),
        )
        ctx = ScreenContext(
            context_id="test_ctx",
            app=AppInfo(name="Mail", pid=1234),
            window=WindowInfo(101, 1234, "Mail", RectBounds(0, 0, 800, 600)),
            elements=[generic_el],
            ocr_blocks=[ocr_block],
            screenshot_path=None,
            facts=[],
            created_at_epoch=1000.0,
            created_at_iso="2026-10-30T00:00:00Z",
        )

        res = self.resolver.resolve_target(ctx, "Send Draft")
        self.assertTrue(res.ok)
        self.assertEqual(res.resolution_method, "ocr_spatial_correlation")
        self.assertEqual(res.element.id, "btn_generic")

    def test_06_desktop_interaction_engine_execution_and_cancellation(self) -> None:
        ax_res = self.ax_engine.inspect_current_application()
        ctx = self.fusion.fuse(ax_res)

        # Normal execution
        req = InteractionRequest(action_type="click", target_description="New Message")
        res = self.interaction.execute_interaction(req, context=ctx)
        self.assertTrue(res.ok)
        self.assertEqual(res.method_used, InteractionMethod.ACCESSIBILITY_ACTION)
        self.assertTrue(res.verified_outcome)

        # Pre-flight cancellation check
        canceled_req = InteractionRequest(action_type="click", target_description="New Message")
        cancel_res = self.interaction.execute_interaction(
            canceled_req,
            context=ctx,
            cancel_check=lambda: True,
        )
        self.assertFalse(cancel_res.ok)
        self.assertIn("canceled", cancel_res.message.lower())

    def test_07_sqlite_persistence_screen_observations_and_checkpoints(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as f:
            db_path = f.name

        store = TaskStore(db_path)
        task = Task(
            id="screen_task_001",
            intent="Inspect screen and click compose",
            command=TaskCommand.OBSERVE_SCREEN,
            risk_level=RiskLevel.LOW,
            status=TaskStatus.RUNNING,
        )
        store.save_task(task)

        # Record observation
        store.record_screen_observation(
            context_id="ctx_001",
            task_id="screen_task_001",
            app_name="Mail",
            window_title="Inbox",
            elements_count=25,
            modal_dialog=False,
            screenshot_path="/tmp/screen.png",
            facts=[{"category": "test", "detail": "parsed"}],
        )

        obs = store.get_screen_observation("ctx_001")
        self.assertIsNotNone(obs)
        self.assertEqual(obs["appName"], "Mail")
        self.assertEqual(obs["elementsCount"], 25)

        # Record recovery checkpoint
        cp_id = store.record_recovery_checkpoint(
            task_id="screen_task_001",
            step_index=1,
            state_hash="hash_step_1",
            context_id="ctx_001",
            status="completed",
            metadata={"target": "New Message"},
        )
        self.assertIsNotNone(cp_id)

        latest_cp = store.get_latest_checkpoint("screen_task_001")
        self.assertIsNotNone(latest_cp)
        self.assertEqual(latest_cp["stepIndex"], 1)
        self.assertEqual(latest_cp["stateHash"], "hash_step_1")

        # Cleanup
        try:
            os.unlink(db_path)
        except OSError:
            pass

    def test_08_app_capability_registry(self) -> None:
        reg = ApplicationCapabilityRegistry()
        mail_prof = reg.get_profile("Mail")
        self.assertEqual(mail_prof.preferred_mode, SupportedInterfaceMode.APPLE_EVENTS)
        self.assertIn("compose", mail_prof.action_aliases)

        wa_prof = reg.get_profile("WhatsApp")
        self.assertEqual(wa_prof.preferred_mode, SupportedInterfaceMode.URL_SCHEME)

        # Dynamic profile for third party app
        slack_prof = reg.get_profile("Slack")
        self.assertEqual(slack_prof.name, "Slack")
        self.assertEqual(slack_prof.preferred_mode, SupportedInterfaceMode.ACCESSIBILITY_AX)

    def test_09_orchestrator_planning_and_routing(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as f:
            db_path = f.name

        orch = CortexOrchestrator()
        orch.task_store = TaskStore(db_path)
        orch.automation.dry_run = True

        # Test routing for observe screen
        res = orch.chat("observe screen")
        self.assertIn("task", res)
        task_id = res["task"]["id"]
        task = orch.tasks[task_id]
        self.assertEqual(task.command, TaskCommand.OBSERVE_SCREEN)
        self.assertEqual(task.status, TaskStatus.COMPLETED)

        # Test planner decomposition for observe screen
        plan_obs = orch.planner.plan("observe screen", TaskCommand.OBSERVE_SCREEN)
        self.assertEqual(len(plan_obs.steps), 1)
        self.assertEqual(plan_obs.steps[0].command, TaskCommand.OBSERVE_SCREEN)

        # Test routing for click element
        res_click = orch.chat("click the Compose button")
        self.assertIn("task", res_click)
        click_task = orch.tasks[res_click["task"]["id"]]
        self.assertEqual(click_task.command, TaskCommand.CLICK_ELEMENT)

        # Test planner decomposition for click element (resolve -> click)
        plan_click = orch.planner.plan("click the Compose button", TaskCommand.CLICK_ELEMENT, {"target": "Compose"})
        self.assertEqual(len(plan_click.steps), 2)
        self.assertEqual(plan_click.steps[0].command, TaskCommand.RESOLVE_UI_ELEMENT)
        self.assertEqual(plan_click.steps[1].command, TaskCommand.CLICK_ELEMENT)

        try:
            os.unlink(db_path)
        except OSError:
            pass


if __name__ == "__main__":
    unittest.main()
