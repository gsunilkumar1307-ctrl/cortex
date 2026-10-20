from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseEmailProvider(ABC):
    """Abstract base class for Cortex email providers (Apple Mail, Gmail, etc.)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the provider (e.g. 'Apple Mail', 'Gmail')."""
        pass

    @abstractmethod
    def is_authenticated(self) -> bool:
        """Check if the provider is currently authenticated and authorized."""
        pass

    @abstractmethod
    def get_accounts(self) -> list[dict[str, str]]:
        """List configured/connected email accounts: [{'name': '...', 'email': '...'}, ...]."""
        pass

    @abstractmethod
    def get_signature(self, account: str = "") -> str:
        """Retrieve user's email signature for the given account if available."""
        pass

    @abstractmethod
    def search_messages(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search messages in mailbox for correspondence or contact discovery."""
        pass

    @abstractmethod
    def search_contacts(self, query: str) -> list[dict[str, Any]]:
        """Search authorized contacts/address book."""
        pass

    @abstractmethod
    def create_draft(
        self,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a real draft in the provider's Drafts folder.
        Returns: {'ok': bool, 'message': str, 'draft_id': str | None, 'data': dict}
        """
        pass

    @abstractmethod
    def send_message(
        self,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
    ) -> dict[str, Any]:
        """Send an approved message through the provider.
        Returns: {'ok': bool, 'message': str, 'message_id': str | None, 'data': dict}
        """
        pass

    @abstractmethod
    def verify_draft_exists(self, recipient: str, subject: str) -> dict[str, Any]:
        """Verify that a draft exists in the provider's drafts folder."""
        pass

    @abstractmethod
    def verify_message_sent(self, recipient: str, subject: str) -> dict[str, Any]:
        """Independently verify that the message appears in the provider's Sent folder."""
        pass

    @abstractmethod
    def delete_draft(self, recipient: str, subject: str = "") -> dict[str, Any]:
        """Remove/discard a draft from the provider's drafts folder upon user cancellation."""
        pass

    def get_thread(self, thread_id: str) -> dict[str, Any]:
        """Fetch conversation thread context for a specific thread identifier."""
        return {"ok": False, "thread_id": thread_id, "messages": []}

    def disconnect(self) -> dict[str, Any]:
        """Disconnect and revoke credentials for this provider."""
        return {"ok": True, "message": "Disconnected"}
