from __future__ import annotations

import platform
from typing import Any
from .base_provider import BaseEmailProvider
from .apple_mail_provider import AppleMailProvider
from .gmail_provider import GmailProvider


class MailProviderManager:
    """Coordinates email providers (Apple Mail, Gmail) and account selection for Cortex."""

    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self.system = platform.system().lower()
        self.providers: dict[str, BaseEmailProvider] = {}
        self._init_providers()

    def _init_providers(self) -> None:
        self.apple_mail = AppleMailProvider(dry_run=self.dry_run)
        self.gmail = GmailProvider(sandbox=self.dry_run)
        self.providers["apple_mail"] = self.apple_mail
        self.providers["gmail"] = self.gmail

    def get_provider_for_account(self, account_identifier: str = "") -> BaseEmailProvider:
        acc_lower = account_identifier.lower()
        if "gmail" in acc_lower or "@gmail.com" in acc_lower:
            return self.gmail
        if "apple" in acc_lower or "mail.app" in acc_lower or "college" in acc_lower:
            return self.apple_mail
        # Default based on OS and availability
        if self.system == "darwin" or self.dry_run:
            return self.apple_mail
        if self.gmail.is_authenticated():
            return self.gmail
        return self.apple_mail

    def list_accounts(self) -> list[dict[str, str]]:
        accounts = []
        for p in self.providers.values():
            try:
                accs = p.get_accounts()
                accounts.extend(accs)
            except Exception:
                pass
        return accounts or [{"name": "Primary Account", "email": "me@cortex.internal"}]

    def get_signature(self, account: str = "") -> str:
        provider = self.get_provider_for_account(account)
        return provider.get_signature(account)

    def search_all_mailboxes(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        results = []
        for p in self.providers.values():
            try:
                res = p.search_messages(query, limit=limit)
                results.extend(res)
            except Exception:
                pass
        return results[:limit]

    def search_all_contacts(self, query: str) -> list[dict[str, Any]]:
        contacts = []
        seen = set()
        for p in self.providers.values():
            try:
                res = p.search_contacts(query)
                for c in res:
                    em = c.get("email", "").lower()
                    if em and em not in seen:
                        seen.add(em)
                        contacts.append(c)
            except Exception:
                pass
        return contacts

    def create_draft(
        self,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
    ) -> dict[str, Any]:
        provider = self.get_provider_for_account(account)
        return provider.create_draft(recipient, subject, body, account, attachments)

    def send_message(
        self,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
    ) -> dict[str, Any]:
        provider = self.get_provider_for_account(account)
        return provider.send_message(recipient, subject, body, account, attachments)

    def verify_draft_exists(self, recipient: str, subject: str, account: str = "") -> dict[str, Any]:
        provider = self.get_provider_for_account(account)
        return provider.verify_draft_exists(recipient, subject)

    def verify_message_sent(self, recipient: str, subject: str, account: str = "") -> dict[str, Any]:
        provider = self.get_provider_for_account(account)
        return provider.verify_message_sent(recipient, subject)

    def delete_draft(self, recipient: str, subject: str = "", account: str = "") -> dict[str, Any]:
        provider = self.get_provider_for_account(account)
        return provider.delete_draft(recipient, subject)
