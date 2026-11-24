"""Application Adapters for Cortex Agent.

Provides modular, verifiable drivers for desktop applications adhering to the
ApplicationAdapter contract.
"""

from __future__ import annotations

from .base import (
    ApplicationAdapter,
    ApplicationAdapterRegistry,
    AdapterToolWrapper,
)
from .notes_adapter import NotesAdapter
from .whatsapp_adapter import WhatsAppAdapter

# Default registry with built-in adapters
default_adapter_registry = ApplicationAdapterRegistry()
default_adapter_registry.register(NotesAdapter())
default_adapter_registry.register(WhatsAppAdapter())

__all__ = [
    "ApplicationAdapter",
    "ApplicationAdapterRegistry",
    "AdapterToolWrapper",
    "NotesAdapter",
    "WhatsAppAdapter",
    "default_adapter_registry",
]
