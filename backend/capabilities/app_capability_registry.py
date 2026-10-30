from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from backend.capabilities.screen_context import ScreenContext
from backend.capabilities.screen_accessibility import NormalizedUIRole

logger = logging.getLogger("cortex.app_registry")


class SupportedInterfaceMode(str, Enum):
    NATIVE_API = "native_api"
    APPLE_EVENTS = "apple_events"
    ACCESSIBILITY_AX = "accessibility_ax"
    URL_SCHEME = "url_scheme"
    OCR_VISION = "ocr_vision"


@dataclass
class AppProfile:
    name: str
    bundle_id: Optional[str]
    preferred_mode: SupportedInterfaceMode
    supported_modes: list[SupportedInterfaceMode]
    action_aliases: dict[str, str] = field(default_factory=dict)
    known_roles: dict[str, str] = field(default_factory=dict)


class ApplicationCapabilityRegistry:
    """
    Universal Application Capability Registry.
    Provides tailored profiles for core macOS applications (Mail, WhatsApp, Finder, Safari, Notes)
    while dynamically supporting ANY third-party application via AXUIElement accessibility
    hierarchy auto-discovery and OCR-vision perception.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, AppProfile] = {}
        self._register_default_profiles()

    def _register_default_profiles(self) -> None:
        # Apple Mail
        self.register_profile(
            AppProfile(
                name="Mail",
                bundle_id="com.apple.mail",
                preferred_mode=SupportedInterfaceMode.APPLE_EVENTS,
                supported_modes=[
                    SupportedInterfaceMode.APPLE_EVENTS,
                    SupportedInterfaceMode.ACCESSIBILITY_AX,
                    SupportedInterfaceMode.OCR_VISION,
                ],
                action_aliases={"compose": "New Message", "search": "Search", "send": "Send"},
            )
        )
        # WhatsApp Desktop
        self.register_profile(
            AppProfile(
                name="WhatsApp",
                bundle_id="net.whatsapp.WhatsApp",
                preferred_mode=SupportedInterfaceMode.URL_SCHEME,
                supported_modes=[
                    SupportedInterfaceMode.URL_SCHEME,
                    SupportedInterfaceMode.ACCESSIBILITY_AX,
                    SupportedInterfaceMode.OCR_VISION,
                ],
                action_aliases={"compose": "New chat", "search": "Search or start new chat", "send": "Send"},
            )
        )
        # Finder
        self.register_profile(
            AppProfile(
                name="Finder",
                bundle_id="com.apple.finder",
                preferred_mode=SupportedInterfaceMode.APPLE_EVENTS,
                supported_modes=[
                    SupportedInterfaceMode.APPLE_EVENTS,
                    SupportedInterfaceMode.ACCESSIBILITY_AX,
                ],
                action_aliases={"new_window": "New Finder Window", "goto": "Go to Folder..."},
            )
        )
        # Safari
        self.register_profile(
            AppProfile(
                name="Safari",
                bundle_id="com.apple.Safari",
                preferred_mode=SupportedInterfaceMode.APPLE_EVENTS,
                supported_modes=[
                    SupportedInterfaceMode.APPLE_EVENTS,
                    SupportedInterfaceMode.ACCESSIBILITY_AX,
                    SupportedInterfaceMode.OCR_VISION,
                ],
                action_aliases={"new_tab": "New Tab", "address_bar": "Address and Search"},
            )
        )

    def register_profile(self, profile: AppProfile) -> None:
        key = profile.name.lower()
        self._profiles[key] = profile
        if profile.bundle_id:
            self._profiles[profile.bundle_id.lower()] = profile

    def get_profile(self, app_name_or_bundle: str) -> AppProfile:
        key = app_name_or_bundle.lower().strip()
        if key in self._profiles:
            return self._profiles[key]

        # Dynamic fallback profile for any third-party macOS app
        return AppProfile(
            name=app_name_or_bundle,
            bundle_id=None,
            preferred_mode=SupportedInterfaceMode.ACCESSIBILITY_AX,
            supported_modes=[
                SupportedInterfaceMode.ACCESSIBILITY_AX,
                SupportedInterfaceMode.OCR_VISION,
            ],
            action_aliases={},
        )

    def inspect_app_capabilities(self, app_name: str, context: Optional[ScreenContext] = None) -> dict[str, Any]:
        profile = self.get_profile(app_name)
        discovered_actions = list(profile.action_aliases.keys())
        interactive_buttons = []

        if context and context.elements:
            for el in context.elements:
                if el.is_interactive:
                    lbl = el.inferred_label or el.title
                    if lbl and lbl not in interactive_buttons:
                        interactive_buttons.append(lbl)

        return {
            "appName": profile.name,
            "bundleId": profile.bundle_id,
            "preferredMode": profile.preferred_mode.value,
            "supportedModes": [m.value for m in profile.supported_modes],
            "knownActions": discovered_actions,
            "discoveredInteractiveElements": interactive_buttons[:20],
        }
