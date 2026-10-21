"""Cortex Email Integrations: Gmail, Apple Mail, and Provider Manager."""
from backend.integrations.email.base_provider import BaseEmailProvider
from backend.integrations.email.apple_mail_provider import AppleMailProvider
from backend.integrations.email.gmail_provider import GmailProvider
from backend.integrations.email.manager import MailProviderManager

__all__ = [
    "BaseEmailProvider",
    "AppleMailProvider",
    "GmailProvider",
    "MailProviderManager",
]
