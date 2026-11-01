from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("cortex.screen_native")

NATIVE_DIR = Path(__file__).resolve().parent.parent / "native"
HELPER_SOURCE = NATIVE_DIR / "cortex_screen_helper.swift"
HELPER_BIN = NATIVE_DIR / "cortex_screen_helper"


@dataclass(frozen=True)
class RectBounds:
    x: float
    y: float
    width: float
    height: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class AppInfo:
    name: str
    pid: int
    bundle_id: Optional[str] = None
    is_active: bool = False
    is_hidden: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WindowInfo:
    window_id: int
    pid: int
    app_name: str
    bounds: RectBounds
    title: Optional[str] = None
    is_on_screen: bool = True
    layer: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["bounds"] = self.bounds.to_dict()
        return d


@dataclass(frozen=True)
class AXElementInfo:
    id: str
    role: str
    path: str
    subrole: Optional[str] = None
    title: Optional[str] = None
    value: Optional[str] = None
    description_text: Optional[str] = None
    bounds: Optional[RectBounds] = None
    is_enabled: bool = True
    actions: list[str] = None
    depth: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.bounds:
            d["bounds"] = self.bounds.to_dict()
        return d


@dataclass(frozen=True)
class OCRObservation:
    text: str
    confidence: float
    bounds: RectBounds
    normalized_bounds: RectBounds
    languages: list[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["bounds"] = self.bounds.to_dict()
        d["normalized_bounds"] = self.normalized_bounds.to_dict()
        return d


@dataclass(frozen=True)
class PermissionState:
    accessibility: bool
    screen_recording: bool
    status_message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NativeScreenHelperBridge:
    """
    Python bridge communicating with the compiled native Swift helper.
    Supports single-shot and persistent IPC sessions.
    """

    def __init__(self, use_mock: bool = False) -> None:
        self.system = platform.system().lower()
        self.is_macos = self.system == "darwin"
        self.use_mock = use_mock or (not self.is_macos) or (os.getenv("CORTEX_MOCK_SCREEN_HELPER", "0") == "1")
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._ensure_binary()

    def _ensure_binary(self) -> bool:
        if self.use_mock or not self.is_macos:
            return False
        if HELPER_BIN.exists() and os.access(str(HELPER_BIN), os.X_OK):
            return True
        if HELPER_SOURCE.exists():
            try:
                logger.info("Compiling cortex_screen_helper from Swift source...")
                subprocess.run(
                    ["swiftc", "-O", str(HELPER_SOURCE), "-o", str(HELPER_BIN)],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30.0,
                )
                return HELPER_BIN.exists()
            except Exception as e:
                logger.warning(f"Could not compile Swift helper: {e}. Falling back to mock mode.")
                self.use_mock = True
                return False
        return False

    def _execute_command(self, cmd_line: str, timeout: float = 5.0) -> dict[str, Any]:
        if self.use_mock:
            return self._mock_dispatch(cmd_line)
        self._ensure_binary()
        if not HELPER_BIN.exists():
            return self._mock_dispatch(cmd_line)

        try:
            res = subprocess.run(
                [str(HELPER_BIN)] + cmd_line.split(),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if res.returncode == 0 and res.stdout.strip():
                try:
                    return json.loads(res.stdout.strip())
                except json.JSONDecodeError:
                    return {"ok": False, "error": f"Invalid JSON response: {res.stdout.strip()}"}
            else:
                err = res.stderr.strip() or f"Exited with code {res.returncode}"
                return {"ok": False, "error": err}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"Command '{cmd_line}' timed out after {timeout}s"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _mock_dispatch(self, cmd_line: str) -> dict[str, Any]:
        parts = cmd_line.split()
        sub = parts[0] if parts else ""
        if hasattr(self, "_mock_failure") and self._mock_failure:
            return {"ok": False, "error": getattr(self, "_mock_failure_error", "Mock native helper crash.")}
        if sub == "permissions":
            if hasattr(self, "_mock_permissions") and self._mock_permissions is not None:
                return {"ok": True, "data": self._mock_permissions}
            return {
                "ok": True,
                "data": {
                    "accessibility": True,
                    "screenRecording": True,
                    "statusMessage": "Mock permissions granted.",
                },
            }
        elif sub == "frontmost":
            if hasattr(self, "_mock_frontmost") and self._mock_frontmost is not None:
                return {"ok": True, "data": self._mock_frontmost}
            return {
                "ok": True,
                "data": {
                    "bundleId": "com.apple.mail",
                    "name": "Mail",
                    "pid": 1234,
                    "isActive": True,
                    "isHidden": False,
                },
            }
        elif sub == "apps":
            return {
                "ok": True,
                "data": [
                    {"bundleId": "com.apple.mail", "name": "Mail", "pid": 1234, "isActive": True, "isHidden": False},
                    {"bundleId": "net.whatsapp.WhatsApp", "name": "WhatsApp", "pid": 2345, "isActive": False, "isHidden": False},
                ],
            }
        elif sub == "windows":
            if hasattr(self, "_mock_windows") and self._mock_windows is not None:
                return {"ok": True, "data": self._mock_windows}
            return {
                "ok": True,
                "data": [
                    {
                        "windowId": 101,
                        "pid": 1234,
                        "appName": "Mail",
                        "title": "Inbox (2 messages)",
                        "bounds": {"x": 100, "y": 100, "width": 800, "height": 600},
                        "isOnScreen": True,
                        "layer": 0,
                    }
                ],
            }
        elif sub == "ax-tree":
            if hasattr(self, "_mock_ax_elements") and self._mock_ax_elements is not None:
                return {"ok": True, "data": self._mock_ax_elements}
            return {
                "ok": True,
                "data": [
                    {"id": "AXApplication_0_0", "role": "AXApplication", "title": "Mail", "path": "0", "depth": 0, "actions": [], "isEnabled": True},
                    {"id": "AXWindow_1_1", "role": "AXWindow", "title": "Inbox", "path": "0/0", "depth": 1, "actions": ["AXRaise"], "bounds": {"x": 100, "y": 100, "width": 800, "height": 600}, "isEnabled": True},
                    {"id": "AXButton_2_2", "role": "AXButton", "title": "New Message", "descriptionText": "Compose", "path": "0/0/0", "depth": 2, "actions": ["AXPress"], "bounds": {"x": 120, "y": 120, "width": 80, "height": 30}, "isEnabled": True},
                    {"id": "AXButton_2_3", "role": "AXButton", "title": "Delete Account", "descriptionText": "Delete Account", "path": "0/0/1", "depth": 2, "actions": ["AXPress"], "bounds": {"x": 220, "y": 120, "width": 80, "height": 30}, "isEnabled": True},
                ],
            }
        elif sub == "ocr":
            if hasattr(self, "_mock_ocr") and self._mock_ocr is not None:
                return {"ok": True, "data": self._mock_ocr}
            return {
                "ok": True,
                "data": [
                    {
                        "text": "Compose",
                        "confidence": 0.98,
                        "bounds": {"x": 120, "y": 120, "width": 80, "height": 30},
                        "normalizedBounds": {"x": 0.1, "y": 0.8, "width": 0.1, "height": 0.05},
                        "languages": ["en"],
                    }
                ],
            }
        elif sub == "capture":
            if hasattr(self, "_mock_capture_ok") and not self._mock_capture_ok:
                return {"ok": False, "error": getattr(self, "_mock_capture_error", "Mock screenshot capture failed.")}
            target = parts[1] if len(parts) > 1 else "/tmp/mock_screenshot.png"
            Path(target).touch()
            return {"ok": True, "data": {"path": target, "message": "Mock screenshot generated."}}
        elif sub == "action":
            return {"ok": True, "data": {"message": "Mock action executed."}}
        return {"ok": True, "data": {}}

    def get_permissions(self, request_screen: bool = False) -> PermissionState:
        cmd = "permissions --request" if request_screen else "permissions"
        res = self._execute_command(cmd)
        if res.get("ok") and "data" in res:
            d = res["data"]
            return PermissionState(
                accessibility=bool(d.get("accessibility", False)),
                screen_recording=bool(d.get("screenRecording", False)),
                status_message=str(d.get("statusMessage", "")),
            )
        return PermissionState(False, False, f"Failed to query permissions: {res.get('error')}")

    def get_frontmost_app(self) -> Optional[AppInfo]:
        res = self._execute_command("frontmost")
        if res.get("ok") and res.get("data"):
            d = res["data"]
            return AppInfo(
                name=d.get("name", "Unknown"),
                pid=int(d.get("pid", 0)),
                bundle_id=d.get("bundleId"),
                is_active=bool(d.get("isActive", False)),
                is_hidden=bool(d.get("isHidden", False)),
            )
        return None

    def list_running_apps(self) -> list[AppInfo]:
        res = self._execute_command("apps")
        apps = []
        if res.get("ok") and isinstance(res.get("data"), list):
            for d in res["data"]:
                apps.append(
                    AppInfo(
                        name=d.get("name", "Unknown"),
                        pid=int(d.get("pid", 0)),
                        bundle_id=d.get("bundleId"),
                        is_active=bool(d.get("isActive", False)),
                        is_hidden=bool(d.get("isHidden", False)),
                    )
                )
        return apps

    def list_windows(self) -> list[WindowInfo]:
        res = self._execute_command("windows")
        windows = []
        if res.get("ok") and isinstance(res.get("data"), list):
            for d in res["data"]:
                b = d.get("bounds", {})
                bounds = RectBounds(
                    x=float(b.get("x", 0)),
                    y=float(b.get("y", 0)),
                    width=float(b.get("width", 0)),
                    height=float(b.get("height", 0)),
                )
                windows.append(
                    WindowInfo(
                        window_id=int(d.get("windowId", 0)),
                        pid=int(d.get("pid", 0)),
                        app_name=str(d.get("appName", "")),
                        title=d.get("title"),
                        bounds=bounds,
                        is_on_screen=bool(d.get("isOnScreen", True)),
                        layer=int(d.get("layer", 0)),
                    )
                )
        return windows

    def inspect_ax_tree(self, pid: Optional[int] = None, depth: int = 4, max_elements: int = 150) -> list[AXElementInfo]:
        cmd = f"ax-tree --depth {depth} --max {max_elements}"
        if pid:
            cmd += f" --pid {pid}"
        res = self._execute_command(cmd, timeout=10.0)
        elements = []
        if res.get("ok") and isinstance(res.get("data"), list):
            for d in res["data"]:
                b = d.get("bounds")
                bounds = None
                if b and isinstance(b, dict):
                    bounds = RectBounds(
                        x=float(b.get("x", 0)),
                        y=float(b.get("y", 0)),
                        width=float(b.get("width", 0)),
                        height=float(b.get("height", 0)),
                    )
                elements.append(
                    AXElementInfo(
                        id=str(d.get("id", "")),
                        role=str(d.get("role", "")),
                        path=str(d.get("path", "")),
                        subrole=d.get("subrole"),
                        title=d.get("title"),
                        value=d.get("value"),
                        description_text=d.get("descriptionText"),
                        bounds=bounds,
                        is_enabled=bool(d.get("isEnabled", True)),
                        actions=d.get("actions", []),
                        depth=int(d.get("depth", 0)),
                    )
                )
        return elements

    def run_ocr(self, image_path: str) -> list[OCRObservation]:
        res = self._execute_command(f"ocr {image_path}", timeout=15.0)
        observations = []
        if res.get("ok") and isinstance(res.get("data"), list):
            for d in res["data"]:
                b = d.get("bounds", {})
                nb = d.get("normalizedBounds", {})
                bounds = RectBounds(
                    x=float(b.get("x", 0)),
                    y=float(b.get("y", 0)),
                    width=float(b.get("width", 0)),
                    height=float(b.get("height", 0)),
                )
                norm_bounds = RectBounds(
                    x=float(nb.get("x", 0)),
                    y=float(nb.get("y", 0)),
                    width=float(nb.get("width", 0)),
                    height=float(nb.get("height", 0)),
                )
                observations.append(
                    OCRObservation(
                        text=str(d.get("text", "")),
                        confidence=float(d.get("confidence", 1.0)),
                        bounds=bounds,
                        normalized_bounds=norm_bounds,
                        languages=d.get("languages", []),
                    )
                )
        return observations

    def capture_screenshot(self, target_path: str, bounds: Optional[RectBounds] = None) -> tuple[bool, str]:
        resolved_path = str(Path(target_path).resolve())
        Path(resolved_path).parent.mkdir(parents=True, exist_ok=True)
        cmd = f"capture {resolved_path}"
        res = self._execute_command(cmd, timeout=10.0)
        if res.get("ok"):
            return True, str(res.get("data", {}).get("message", "Captured"))
        return False, str(res.get("error", "Failed"))

    def perform_ax_action(self, pid: int, path: str, action_name: str) -> tuple[bool, str]:
        cmd = f"action {pid} {path} {action_name}"
        res = self._execute_command(cmd, timeout=5.0)
        if res.get("ok"):
            return True, str(res.get("data", {}).get("message", "Success"))
        return False, str(res.get("error", "Action failed"))
