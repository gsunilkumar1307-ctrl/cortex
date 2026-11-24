from __future__ import annotations

import logging
import os
import platform
from typing import Any
from .base_provider import BaseEmailProvider
from .apple_mail_provider import AppleMailProvider
from .gmail_provider import GmailProvider

logger = logging.getLogger(__name__)

try:
    from backend.core.contracts import MailDeliveryStatus
except ImportError:
    from core.contracts import MailDeliveryStatus

try:
    from backend.capabilities.safety import is_real_email_send_allowed
except ImportError:
    try:
        from capabilities.safety import is_real_email_send_allowed
    except ImportError:
        def is_real_email_send_allowed() -> bool:
            return os.getenv("CORTEX_ALLOW_REAL_EMAIL_SEND", "").strip() == "1"



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
        return accounts or [{"name": "Default Account", "email": "user@mac.local"}]

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
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict[str, Any]:
        provider = self.get_provider_for_account(account)
        return provider.create_draft(recipient, subject, body, account, attachments, cc=cc, bcc=bcc)

    def update_draft(
        self,
        draft_id: str,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        old_subject: str = "",
    ) -> dict[str, Any]:
        provider = self.get_provider_for_account(account)
        if hasattr(provider, "update_draft"):
            return provider.update_draft(
                draft_id=draft_id,
                recipient=recipient,
                subject=subject,
                body=body,
                account=account,
                attachments=attachments,
                cc=cc,
                bcc=bcc,
                old_subject=old_subject,
            )
        provider.delete_draft(recipient, old_subject or subject)
        return provider.create_draft(recipient, subject, body, account, attachments, cc=cc, bcc=bcc)

    def send_message(
        self,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict[str, Any]:
        # Mandatory P7.5.3 Safety Gate: Real email transmission is permitted ONLY when
        # CORTEX_ALLOW_REAL_EMAIL_SEND is explicitly set to '1'. All other values (unset,
        # empty, '0', 'false', 'no', 'off', etc.) strictly block outbound transmission.
        if not is_real_email_send_allowed():
            logger.warning("MailProviderManager: Outbound email sending blocked by safety policy. CORTEX_ALLOW_REAL_EMAIL_SEND is not '1'.")
            return {
                "ok": False,
                "status": MailDeliveryStatus.BLOCKED.value,
                "delivery_status": MailDeliveryStatus.BLOCKED.value,
                "message": f"Email sending to {recipient} is blocked by safety policy. Real email transmission is disabled in Phase P7.2.",
                "error": "SEND_BLOCKED_BY_POLICY",
                "data": {"recipient": recipient, "subject": subject, "account": account},
            }

        provider = self.get_provider_for_account(account)
        return provider.send_message(recipient, subject, body, account, attachments, cc=cc, bcc=bcc)

    def verify_draft_exists(self, recipient: str, subject: str, account: str = "") -> dict[str, Any]:
        provider = self.get_provider_for_account(account)
        return provider.verify_draft_exists(recipient, subject)

    def verify_message_sent(self, recipient: str, subject: str, account: str = "") -> dict[str, Any]:
        provider = self.get_provider_for_account(account)
        return provider.verify_message_sent(recipient, subject)

    def delete_draft(self, recipient: str, subject: str = "", account: str = "") -> dict[str, Any]:
        provider = self.get_provider_for_account(account)
        return provider.delete_draft(recipient, subject)
