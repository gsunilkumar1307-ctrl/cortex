"""Cortex Capabilities: OS, Browser, Mail, and Vision Automation."""
from backend.capabilities.device_actions import DeviceAutomation, DeviceActionResult
from backend.capabilities.safety import classify_command
from backend.capabilities.browser_actions import BrowserAutomation, BrowserResult
from backend.capabilities.vision import analyze_screen
from backend.capabilities.mail_actions import MailAutomation

__all__ = [
    "DeviceAutomation",
    "DeviceActionResult",
    "classify_command",
    "BrowserAutomation",
    "BrowserResult",
    "analyze_screen",
    "MailAutomation",
]
