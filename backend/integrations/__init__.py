"""Cortex Integrations: Email and Web Services."""
from backend.integrations.email import (
    BaseEmailProvider,
    AppleMailProvider,
    GmailProvider,
    MailProviderManager,
)
from backend.integrations.search import search_web

__all__ = [
    "BaseEmailProvider",
    "AppleMailProvider",
    "GmailProvider",
    "MailProviderManager",
    "search_web",
]
