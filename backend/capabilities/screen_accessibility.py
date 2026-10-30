from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from backend.capabilities.screen_native import (
    AXElementInfo,
    RectBounds,
    NativeScreenHelperBridge,
    AppInfo,
    WindowInfo,
    PermissionState,
)

logger = logging.getLogger("cortex.screen_accessibility")


class NormalizedUIRole(str, Enum):
    WINDOW = "window"
    SHEET = "sheet"
    DIALOG = "dialog"
    BUTTON = "button"
    TEXT_FIELD = "text_field"
    LABEL = "label"
    CHECKBOX = "checkbox"
    RADIO_BUTTON = "radio_button"
    MENU = "menu"
    MENU_ITEM = "menu_item"
    SCROLL_AREA = "scroll_area"
    TAB = "tab"
    GROUP = "group"
    UNKNOWN = "unknown"

    @classmethod
    def from_ax_role(cls, ax_role: str, subrole: Optional[str] = None) -> "NormalizedUIRole":
        role_map = {
            "AXWindow": cls.WINDOW,
            "AXSheet": cls.SHEET,
            "AXDialog": cls.DIALOG,
            "AXButton": cls.BUTTON,
            "AXPopUpButton": cls.BUTTON,
            "AXMenuButton": cls.BUTTON,
            "AXTextField": cls.TEXT_FIELD,
            "AXTextArea": cls.TEXT_FIELD,
            "AXSearchField": cls.TEXT_FIELD,
            "AXStaticText": cls.LABEL,
            "AXHeading": cls.LABEL,
            "AXCheckBox": cls.CHECKBOX,
            "AXRadioButton": cls.RADIO_BUTTON,
            "AXRadioGroup": cls.RADIO_BUTTON,
            "AXMenu": cls.MENU,
            "AXMenuBar": cls.MENU,
            "AXMenuItem": cls.MENU_ITEM,
            "AXMenuBarItem": cls.MENU_ITEM,
            "AXScrollArea": cls.SCROLL_AREA,
            "AXScrollBar": cls.SCROLL_AREA,
            "AXTabGroup": cls.TAB,
            "AXGroup": cls.GROUP,
            "AXSplitGroup": cls.GROUP,
        }
        if subrole and "Dialog" in subrole:
            return cls.DIALOG
        return role_map.get(ax_role, cls.UNKNOWN)


@dataclass
class NormalizedUIElement:
    id: str
    role: NormalizedUIRole
    raw_ax_role: str
    path: str
    title: Optional[str] = None
    value: Optional[str] = None
    description: Optional[str] = None
    inferred_label: str = ""
    bounds: Optional[RectBounds] = None
    is_enabled: bool = True
    is_interactive: bool = False
    is_modal: bool = False
    supported_actions: list[str] = field(default_factory=list)
    depth: int = 0
    children_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role.value,
            "raw_ax_role": self.raw_ax_role,
            "path": self.path,
            "title": self.title,
            "value": self.value,
            "description": self.description,
            "inferred_label": self.inferred_label,
            "bounds": self.bounds.to_dict() if self.bounds else None,
            "is_enabled": self.is_enabled,
            "is_interactive": self.is_interactive,
            "is_modal": self.is_modal,
            "supported_actions": self.supported_actions,
            "depth": self.depth,
        }


@dataclass
class AccessibilityPerceptionResult:
    ok: bool
    app: Optional[AppInfo] = None
    window: Optional[WindowInfo] = None
    elements: list[NormalizedUIElement] = field(default_factory=list)
    modal_dialog_detected: bool = False
    error: Optional[str] = None
    freshness_timestamp: str = ""

    def find_by_label(self, label: str, case_sensitive: bool = False) -> list[NormalizedUIElement]:
        query = label.strip() if case_sensitive else label.strip().lower()
        matches = []
        for el in self.elements:
            candidate_texts = [
                el.inferred_label,
                el.title or "",
                el.description or "",
                el.value or "",
            ]
            for t in candidate_texts:
                cmp = t if case_sensitive else t.lower()
                if query and (query == cmp or query in cmp):
                    matches.append(el)
                    break
        return matches

    def find_by_role(self, role: NormalizedUIRole) -> list[NormalizedUIElement]:
        return [el for el in self.elements if el.role == role]

    def get_interactive_elements(self) -> list[NormalizedUIElement]:
        return [el for el in self.elements if el.is_interactive]


class AccessibilityInspectionEngine:
    """
    High-level engine that normalizes raw accessibility hierarchies from
    the native helper into rich, queryable, robust UI representations.
    """

    def __init__(self, bridge: Optional[NativeScreenHelperBridge] = None) -> None:
        self.bridge = bridge or NativeScreenHelperBridge()

    def inspect_current_application(
        self,
        pid: Optional[int] = None,
        max_depth: int = 5,
        max_elements: int = 200,
    ) -> AccessibilityPerceptionResult:
        perms = self.bridge.get_permissions()
        if not perms.accessibility:
            return AccessibilityPerceptionResult(
                ok=False,
                error=f"Accessibility permission denied. {perms.status_message}",
            )

        app = None
        if pid:
            for running in self.bridge.list_running_apps():
                if running.pid == pid:
                    app = running
                    break
        else:
            app = self.bridge.get_frontmost_app()

        if not app or app.pid <= 0:
            return AccessibilityPerceptionResult(
                ok=False,
                error="No active target application found or application terminated.",
            )

        # Retrieve window metadata
        windows = [w for w in self.bridge.list_windows() if w.pid == app.pid]
        front_window = windows[0] if windows else None

        raw_elements = self.bridge.inspect_ax_tree(
            pid=app.pid,
            depth=max_depth,
            max_elements=max_elements,
        )

        if not raw_elements:
            return AccessibilityPerceptionResult(
                ok=True,
                app=app,
                window=front_window,
                elements=[],
                modal_dialog_detected=False,
                error="Application exposes empty accessibility tree or is unresponsive.",
            )

        normalized = self._normalize_elements(raw_elements)
        modal_detected = any(el.is_modal for el in normalized)

        return AccessibilityPerceptionResult(
            ok=True,
            app=app,
            window=front_window,
            elements=normalized,
            modal_dialog_detected=modal_detected,
        )

    def _normalize_elements(self, raw_elements: list[AXElementInfo]) -> list[NormalizedUIElement]:
        result: list[NormalizedUIElement] = []
        for el in raw_elements:
            role = NormalizedUIRole.from_ax_role(el.role, el.subrole)
            is_modal = role in (NormalizedUIRole.SHEET, NormalizedUIRole.DIALOG)

            # Interactive roles or elements with actionable actions
            interactive_roles = {
                NormalizedUIRole.BUTTON,
                NormalizedUIRole.TEXT_FIELD,
                NormalizedUIRole.CHECKBOX,
                NormalizedUIRole.RADIO_BUTTON,
                NormalizedUIRole.MENU_ITEM,
                NormalizedUIRole.TAB,
            }
            has_action = any(act in ("AXPress", "AXConfirm", "AXPick", "AXShowMenu") for act in (el.actions or []))
            is_interactive = (role in interactive_roles) or has_action

            # Label inference heuristic
            inferred = el.title or el.description_text or el.value or ""
            if not inferred:
                # Role + id fallback
                inferred = f"{role.value}_{el.id}"

            norm = NormalizedUIElement(
                id=el.id,
                role=role,
                raw_ax_role=el.role,
                path=el.path,
                title=el.title,
                value=el.value,
                description=el.description_text,
                inferred_label=inferred,
                bounds=el.bounds,
                is_enabled=el.is_enabled,
                is_interactive=is_interactive,
                is_modal=is_modal,
                supported_actions=el.actions or [],
                depth=el.depth,
            )
            result.append(norm)
        return result
