"""
Tests for Phase P7.3.1: Intelligent Email Search Remediation.
Covers:
1. Real Date Filtering with inclusive boundary checks and out-of-range exclusion.
2. Natural-language date expression interpretation (today, yesterday, this week, last week, weekday ranges, months).
3. Invalid date filter error detection (no silent ignoring).
4. Multi-mailbox traversal across relevant mailboxes (INBOX, Sent, Archive/All Mail).
5. Duplicate suppression across overlapping mailboxes and unified inboxes.
6. MCP-primary routing and result normalization.
7. Explicit AppleScript fallback when MCP is unavailable or fails.
8. Transparent account and mailbox failure reporting (complete vs partial).
9. Honest empty-state reporting without false claims of full coverage.
"""

from __future__ import annotations

import time
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from backend.core.contracts import TaskCommand, TaskStatus, command_from_intent, Task, RiskLevel
from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities.mail_actions import MailAutomation, clear_mail_records, normalize_date_bound, parse_email_date
from backend.mcp.models import MCPToolResult


class TestMailSearchRemediationP731(unittest.TestCase):
    def setUp(self) -> None:
        clear_mail_records()
        self.orchestrator = CortexOrchestrator(dry_run=True)
        self.orchestrator.use_gemini = False
        self.mail = MailAutomation(dry_run=False)

    def tearDown(self) -> None:
        clear_mail_records()

    # ── 1. Real Date Filtering & Boundary Cases ───────────────────────────────

    def test_01_date_parser_handles_diverse_formats(self) -> None:
        ref_now = datetime(2026, 11, 18, 12, 0, 0)
        cases = [
            ("Today, 10:30 AM", datetime(2026, 11, 18, 10, 30, 0)),
            ("Yesterday, 6:00 PM", datetime(2026, 11, 17, 18, 0, 0)),
            ("11/18/2026", datetime(2026, 11, 18, 0, 0, 0)),
            ("Wednesday, 18 November 2026 at 10:00:00 AM", datetime(2026, 11, 18, 10, 0, 0)),
            ("November 17, 2026", datetime(2026, 11, 17, 0, 0, 0)),
            ("2026-11-16T15:30:00", datetime(2026, 11, 16, 15, 30, 0)),
        ]
        for raw, expected in cases:
            parsed = parse_email_date(raw, now=ref_now)
            self.assertIsNotNone(parsed, f"Failed to parse date: {raw}")
            self.assertEqual(parsed, expected, f"Mismatched date for: {raw}")

    def test_02_date_range_filters_out_of_bounds_messages(self) -> None:
        """Proves messages outside requested date boundaries are strictly excluded."""
        emails = [
            {"id": "1", "subject": "Meeting Today", "date": "11/18/2026", "account": "Google", "mailbox": "INBOX", "is_read": True},
            {"id": "2", "subject": "Sync Yesterday", "date": "11/17/2026", "account": "Google", "mailbox": "INBOX", "is_read": True},
            {"id": "3", "subject": "Old Note", "date": "11/10/2026", "account": "Google", "mailbox": "INBOX", "is_read": True},
            {"id": "4", "subject": "Future Email", "date": "11/25/2026", "account": "Google", "mailbox": "INBOX", "is_read": True},
        ]

        with patch.object(self.mail, "read_mail", return_value={"ok": True, "emails": emails}):
            # Search strictly between Nov 16 and Nov 18
            res = self.mail.search_mail(
                date_from="2026-11-16T00:00:00",
                date_to="2026-11-18T23:59:59",
            )
            self.assertTrue(res.get("ok"))
            matched_ids = [e["id"] for e in res.get("emails", [])]
            # Must include 1 and 2, but exclude 3 (too old) and 4 (too new)
            self.assertIn("1", matched_ids)
            self.assertIn("2", matched_ids)
            self.assertNotIn("3", matched_ids)
            self.assertNotIn("4", matched_ids)

    def test_03_invalid_date_filter_detection_not_silently_ignored(self) -> None:
        """Unsupported or invalid date strings must return explicit errors, not silent empty sets."""
        res_from = self.mail.search_mail(date_from="invalid-start-date-xyz")
        self.assertFalse(res_from.get("ok"))
        self.assertIn("Invalid date_from filter", res_from.get("error", ""))

        res_to = self.mail.search_mail(date_to="garbage-end-date-123")
        self.assertFalse(res_to.get("ok"))
        self.assertIn("Invalid date_to filter", res_to.get("error", ""))

    # ── 2. Natural-Language Date Interpretation ───────────────────────────────

    def test_04_date_expression_parsing_weekday_ranges_and_months(self) -> None:
        p1 = "Show me emails received between Monday and Friday."
        params1 = self.orchestrator._extract_mail_search_params(p1)
        self.assertIsNotNone(params1.get("date_from"))
        self.assertIsNotNone(params1.get("date_to"))
        self.assertIn("Monday to Friday", params1.get("date_expression", ""))

        p2 = "Find emails from October."
        params2 = self.orchestrator._extract_mail_search_params(p2)
        self.assertEqual(params2.get("date_expression"), "october")
        self.assertIn("-10-01", params2.get("date_from", ""))
        self.assertIn("-10-31", params2.get("date_to", ""))

        p3 = "Find emails from 2026-10-01 to 2026-10-15."
        params3 = self.orchestrator._extract_mail_search_params(p3)
        self.assertEqual(params3.get("date_from"), "2026-10-01")
        self.assertEqual(params3.get("date_to"), "2026-10-15")

    # ── 3. Multi-Mailbox Traversal & Duplicate Suppression ────────────────────

    def test_05_multi_mailbox_duplicate_suppression(self) -> None:
        """Verifies duplicate messages across overlapping mailboxes (e.g. INBOX vs All Mail) are suppressed."""
        overlapping_emails = [
            {"id": "msg-1", "subject": "Project Status", "sender": "Alice <alice@a.com>", "date": "11/18/2026", "mailbox": "INBOX", "account": "Google"},
            {"id": "msg-1", "subject": "Project Status", "sender": "Alice <alice@a.com>", "date": "11/18/2026", "mailbox": "[Gmail]/All Mail", "account": "Google"},
            {"id": "msg-2", "subject": "Sent Invoice", "sender": "Me <me@google.com>", "date": "11/18/2026", "mailbox": "Sent", "account": "Google"},
        ]

        with patch.object(self.mail, "read_mail", return_value={"ok": True, "emails": overlapping_emails}):
            res = self.mail.search_mail(query="Project Status")
            self.assertTrue(res.get("ok"))
            matched = res.get("emails", [])
            # Must contain msg-1 exactly once
            self.assertEqual(len(matched), 1)
            self.assertEqual(matched[0]["id"], "msg-1")

    # ── 4. MCP-Primary Routing & Result Normalization ─────────────────────────

    def test_06_mcp_primary_search_routing(self) -> None:
        """Verifies that search_mail prefers Apple Mail MCP when mcp_manager is configured."""
        mock_mcp = MagicMock()
        mock_mcp._servers = {"apple-mail": MagicMock()}
        raw_mcp_output = (
            "Found 2 message(s):\n"
            '  - ID: 9001 | 11/18/2026 | Interview Invitation (from: Google <jobs@google.com>) [unread] | in "[Gmail]/Important" (Google)\n'
            '  - ID: 9002 | 11/17/2026 | Next Steps (from: Google <jobs@google.com>) [read] | in "[Gmail]/All Mail" (Google)\n'
        )
        mock_mcp.call_tool.return_value = MCPToolResult(
            content=[{"type": "text", "text": raw_mcp_output}],
            is_error=False
        )

        res = self.mail.search_mail(
            sender="Google",
            unread_only=True,
            mcp_manager=mock_mcp,
        )

        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("execution_engine"), "mcp")
        mock_mcp.call_tool.assert_called_once()
        tool_args = mock_mcp.call_tool.call_args[0][2]
        self.assertEqual(tool_args.get("from"), "Google")
        self.assertEqual(tool_args.get("isRead"), False)

        emails = res.get("emails", [])
        self.assertEqual(len(emails), 1)
        self.assertEqual(emails[0]["id"], "9001")
        self.assertEqual(emails[0]["mailbox"], "[Gmail]/Important")
        self.assertEqual(emails[0]["account"], "Google")

    def test_07_explicit_applescript_fallback_when_mcp_fails(self) -> None:
        """Verifies explicit, observable fallback to native AppleScript when MCP fails."""
        mock_mcp = MagicMock()
        mock_mcp._servers = {"apple-mail": MagicMock()}
        mock_mcp.call_tool.side_effect = Exception("MCP process terminated unexpectedly")

        sample_as_emails = [
            {"id": "as-1", "subject": "Fallback Email", "sender": "Support <support@cortex.internal>", "date": "Today, 10:00 AM", "mailbox": "INBOX", "account": "Apple Mail"}
        ]

        with patch.object(self.mail, "read_mail", return_value={"ok": True, "emails": sample_as_emails}):
            res = self.mail.search_mail(query="Fallback", mcp_manager=mock_mcp)
            self.assertTrue(res.get("ok"))
            self.assertEqual(res.get("execution_engine"), "applescript_fallback")
            self.assertEqual(len(res.get("emails", [])), 1)
            self.assertEqual(res.get("emails")[0]["id"], "as-1")

    # ── 5. Account and Mailbox Failure Transparency ───────────────────────────

    def test_08_transparent_partial_coverage_reporting(self) -> None:
        """Cortex must distinguish partial coverage and report unreachable mailboxes."""
        mock_mcp = MagicMock()
        mock_mcp._servers = {"apple-mail": MagicMock()}
        partial_mcp_output = (
            "Found 1 message(s):\n"
            '  - ID: 101 | 11/18/2026 | Safe Email (from: HR <hr@corp.com>) [read] | in "INBOX" (Google)\n'
            "Warning: partial: true, timedOutMailboxes: ['[Gmail]/Spam', '[Gmail]/Trash']"
        )
        mock_mcp.call_tool.return_value = MCPToolResult(
            content=[{"type": "text", "text": partial_mcp_output}],
            is_error=False
        )

        res = self.mail.search_mail(query="Safe", mcp_manager=mock_mcp)
        self.assertTrue(res.get("ok"))
        cov = res.get("coverage", {})
        self.assertEqual(cov.get("status"), "partial")
        self.assertTrue(len(cov.get("failed_mailboxes", [])) > 0)

    def test_09_orchestrator_honest_empty_state_and_partial_disclosure(self) -> None:
        """Never claim 'I searched all your email' when coverage is partial."""
        partial_result = {
            "ok": True,
            "emails": [],
            "count": 0,
            "execution_engine": "mcp",
            "coverage": {
                "status": "partial",
                "accounts_searched": ["Google"],
                "mailboxes_searched": ["INBOX"],
                "failed_accounts": [],
                "failed_mailboxes": ["[Gmail]/All Mail (timeout)"],
            },
            "message": "No emails found.",
        }

        with patch.object(self.orchestrator.automation, "execute") as mock_exec:
            mock_exec.return_value = MagicMock(data=partial_result, ok=True)
            res = self.orchestrator.chat("Find emails from nonexistent_person_999.")
            msg = res.get("message", "")
            # Must disclose incomplete coverage
            self.assertIn("Note: Search coverage was partial", msg)
            self.assertIn("[Gmail]/All Mail (timeout)", msg)
            self.assertNotIn("across all your email", msg.lower())

    # ── 6. Live Apple Mail Read-Only Verification ─────────────────────────────

    def test_10_live_apple_mail_mcp_search_and_mailboxes(self) -> None:
        """Safe read-only live verification with the real apple-mail-mcp server."""
        from backend.mcp.manager import MCPServerManager
        from backend.mcp.config import get_apple_mail_server_config

        mgr = MCPServerManager()
        try:
            mgr.register_server(get_apple_mail_server_config())
            res = self.mail.search_mail(limit=3, mcp_manager=mgr)
            self.assertTrue(res.get("ok"))
            self.assertEqual(res.get("execution_engine"), "mcp")
            self.assertIsInstance(res.get("emails"), list)
            # Coverage must disclose searched accounts & mailboxes
            cov = res.get("coverage", {})
            self.assertTrue(len(cov.get("accounts_searched", [])) > 0)
        finally:
            mgr.stop_all()


if __name__ == "__main__":
    unittest.main()
