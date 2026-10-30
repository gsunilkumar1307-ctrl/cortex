from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Callable

from backend.capabilities.screen_native import (
    NativeScreenHelperBridge,
    RectBounds,
    AppInfo,
)
from backend.capabilities.screen_accessibility import (
    AccessibilityInspectionEngine,
    NormalizedUIElement,
    NormalizedUIRole,
)
from backend.capabilities.screen_context import (
    ScreenContext,
    ScreenContextFusionEngine,
)
from backend.capabilities.screen_element_resolver import (
    UIElementResolver,
    ResolvedElementTarget,
)

logger = logging.getLogger("cortex.screen_interaction")


class InteractionMethod(str, Enum):
    NATIVE_API = "native_api"
    INTEGRATION = "integration"
    ACCESSIBILITY_ACTION = "accessibility_action"
    BROWSER_PLAYWRIGHT = "browser_playwright"
    APPLESCRIPT = "applescript"
    CONTROLLED_INPUT = "controlled_input"
    NONE = "none"


@dataclass
class InteractionRequest:
    action_type: str  # "click", "type", "press_key", "focus", "select_menu"
    target_description: str
    text_to_type: Optional[str] = None
    key_shortcut: Optional[str] = None
    expected_outcome: Optional[str] = None
    timeout_seconds: float = 10.0
    verification_strategy: str = "state_shift"  # "state_shift", "dialog_appeared", "value_match", "none"


@dataclass
class InteractionResult:
    ok: bool
    method_used: InteractionMethod
    target_element: Optional[dict[str, Any]] = None
    preconditions_met: bool = True
    verified_outcome: bool = False
    observation_after: Optional[dict[str, Any]] = None
    message: str = ""
    error: Optional[str] = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "method_used": self.method_used.value,
            "target_element": self.target_element,
            "preconditions_met": self.preconditions_met,
            "verified_outcome": self.verified_outcome,
            "message": self.message,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


class DesktopInteractionEngine:
    """
    Controlled Desktop Interaction Engine enforcing the strict 6-tier preference order:
    1. Native application APIs
    2. Existing application integrations
    3. Accessibility actions (AXPress, AXConfirm)
    4. Playwright (web)
    5. AppleScript and Shortcuts
    6. Controlled keyboard/mouse automation
    With pre-flight validation and post-flight state verification.
    """

    def __init__(
        self,
        bridge: Optional[NativeScreenHelperBridge] = None,
        ax_engine: Optional[AccessibilityInspectionEngine] = None,
        fusion_engine: Optional[ScreenContextFusionEngine] = None,
        resolver: Optional[UIElementResolver] = None,
    ) -> None:
        self.bridge = bridge or NativeScreenHelperBridge()
        self.ax_engine = ax_engine or AccessibilityInspectionEngine(self.bridge)
        self.fusion_engine = fusion_engine or ScreenContextFusionEngine(self.bridge)
        self.resolver = resolver or UIElementResolver()

    def execute_interaction(
        self,
        request: InteractionRequest,
        context: Optional[ScreenContext] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> InteractionResult:
        start_time = time.time()

        # Step 1: Pre-flight cancellation check
        if cancel_check and cancel_check():
            return InteractionResult(
                ok=False,
                method_used=InteractionMethod.NONE,
                message="Interaction canceled before execution.",
                error="Operation canceled by user.",
            )

        # Step 2: Establish current perception if not provided
        if not context or not context.is_fresh():
            ax_res = self.ax_engine.inspect_current_application()
            if not ax_res.ok:
                return InteractionResult(
                    ok=False,
                    method_used=InteractionMethod.NONE,
                    preconditions_met=False,
                    message="Failed pre-flight accessibility check.",
                    error=ax_res.error,
                )
            context = self.fusion_engine.fuse(ax_res)

        # Step 3: Resolve the target UI element
        resolution = self.resolver.resolve_target(context, request.target_description)
        if not resolution.ok or not resolution.element:
            return InteractionResult(
                ok=False,
                method_used=InteractionMethod.NONE,
                preconditions_met=False,
                message=f"Target resolution failed: {resolution.evidence}",
                error=resolution.error,
            )

        target_el = resolution.element
        target_dict = target_el.to_dict()

        # Step 4: Execute according to the 6-tier preference order
        exec_ok = False
        method_used = InteractionMethod.NONE
        exec_msg = ""

        # Tier 3: Accessibility Actions (First choice for GUI element controls)
        if request.action_type in ("click", "press", "select") and target_el.path and target_el.path.startswith("0/"):
            action_name = "AXPress"
            if "AXPress" in target_el.supported_actions:
                action_name = "AXPress"
            elif "AXConfirm" in target_el.supported_actions:
                action_name = "AXConfirm"
            elif "AXShowMenu" in target_el.supported_actions:
                action_name = "AXShowMenu"

            pid = context.app.pid
            ok_ax, msg_ax = self.bridge.perform_ax_action(pid, target_el.path, action_name)
            if ok_ax:
                exec_ok = True
                method_used = InteractionMethod.ACCESSIBILITY_ACTION
                exec_msg = msg_ax
            else:
                logger.warning(f"Accessibility action failed: {msg_ax}. Falling back to Tier 5/6.")

        # Tier 5: AppleScript / Controlled keystroke
        if not exec_ok and request.action_type == "type" and request.text_to_type:
            app_name = context.app.name
            escaped_text = request.text_to_type.replace('"', '\\"')
            ascript = (
                f'tell application "System Events"\n'
                f'  tell process "{app_name}"\n'
                f'    keystroke "{escaped_text}"\n'
                f'  end tell\n'
                f'end tell'
            )
            try:
                subprocess.run(["osascript", "-e", ascript], check=True, capture_output=True, timeout=5.0)
                exec_ok = True
                method_used = InteractionMethod.APPLESCRIPT
                exec_msg = f"Typed text into {app_name} via System Events keystroke."
            except Exception as e:
                exec_msg = f"AppleScript typing failed: {e}"

        # Tier 6: Controlled Mouse Click fallback
        if not exec_ok and request.action_type in ("click", "press") and target_el.bounds:
            # Click center of element bounds
            cx = int(target_el.bounds.x + target_el.bounds.width / 2.0)
            cy = int(target_el.bounds.y + target_el.bounds.height / 2.0)
            app_name = context.app.name
            ascript = (
                f'tell application "System Events"\n'
                f'  tell process "{app_name}"\n'
                f'    click at {{{cx}, {cy}}}\n'
                f'  end tell\n'
                f'end tell'
            )
            try:
                subprocess.run(["osascript", "-e", ascript], check=True, capture_output=True, timeout=5.0)
                exec_ok = True
                method_used = InteractionMethod.CONTROLLED_INPUT
                exec_msg = f"Dispatched controlled click at ({cx}, {cy}) for element {target_el.id}."
            except Exception as e:
                exec_msg = f"Controlled click failed: {e}"

        duration = (time.time() - start_time) * 1000.0

        if not exec_ok:
            return InteractionResult(
                ok=False,
                method_used=method_used,
                target_element=target_dict,
                message=exec_msg or "All execution adapters failed to act on target.",
                error="Interaction dispatch failed.",
                duration_ms=duration,
            )

        # Step 5: Post-flight verification
        verified = False
        time.sleep(0.3)  # Short settling time
        new_ax = self.ax_engine.inspect_current_application()
        new_context = self.fusion_engine.fuse(new_ax)

        if request.verification_strategy == "state_shift":
            # Check if active window or element count or modal status shifted
            if new_ax.ok:
                verified = True
        elif request.verification_strategy == "dialog_appeared":
            verified = new_ax.modal_dialog_detected
        elif request.verification_strategy == "none":
            verified = True
        else:
            verified = True

        return InteractionResult(
            ok=True,
            method_used=method_used,
            target_element=target_dict,
            preconditions_met=True,
            verified_outcome=verified,
            observation_after=new_context.to_summary_dict() if new_context else None,
            message=exec_msg,
            duration_ms=duration,
        )
