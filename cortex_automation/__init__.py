"""Compatibility shim for cortex_automation."""
from backend.capabilities import (
    DeviceAutomation,
    DeviceActionResult,
    classify_command,
    BrowserAutomation,
    BrowserResult,
    analyze_screen,
    MailAutomation,
)
from backend.capabilities.device_actions import _is_safe_path

__all__ = [
    "DeviceAutomation",
    "DeviceActionResult",
    "classify_command",
    "BrowserAutomation",
    "BrowserResult",
    "analyze_screen",
    "MailAutomation",
    "_is_safe_path",
]
