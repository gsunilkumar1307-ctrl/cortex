import unittest
from unittest.mock import MagicMock, patch
import socket

from backend.mcp.models import MCPToolDefinition, MCPToolResult
from backend.mcp.fetch_policy import FetchSecurityPolicy, PolicyValidationError
from backend.mcp.playwright_policy import PlaywrightSecurityPolicy
from backend.mcp.agent_browser_adapter import MCPAgentBrowserToolAdapter
from backend.core.contracts import ExecutionResult


class TestAgentBrowserDNSClassification(unittest.TestCase):
    """
    Focused tests verifying error classification during URL validation:
    - DNS resolution failures -> DNSResolutionError, never SecurityViolation
    - Loopback, Private, and Metadata IPs -> SecurityViolation
    - Valid public URLs -> Allowed to navigate
    """

    def setUp(self):
        self.fetch_policy = FetchSecurityPolicy()
        self.playwright_policy = PlaywrightSecurityPolicy(fetch_policy=self.fetch_policy)
        self.mock_manager = MagicMock()
        self.definition = MCPToolDefinition(
            name="agent_browser_open",
            server_name="agent-browser",
            description="Open a URL in agent browser",
            input_schema={"type": "object", "properties": {"url": {"type": "string"}}},
        )
        self.adapter = MCPAgentBrowserToolAdapter(
            definition=self.definition,
            manager=self.mock_manager,
            policy=self.playwright_policy,
        )

    def test_dns_lookup_failure_classification(self):
        """A. DNS lookup failure: socket.gaierror -> DNSResolutionError, never SecurityViolation."""
        with patch("socket.getaddrinfo", side_effect=socket.gaierror(8, "nodename nor servname provided, or not known")):
            is_valid, canonical, sec_err = self.playwright_policy.validate_navigation_url("https://nonexistent-domain-test.org/")
            self.assertFalse(is_valid)
            self.assertEqual(getattr(sec_err, "error_type", None), "DNSResolutionError")
            self.assertIn("DNS resolution failed", str(sec_err))
            self.assertNotEqual(getattr(sec_err, "error_type", None), "SecurityViolation")

            # Execute via MCPAgentBrowserToolAdapter
            res: ExecutionResult = self.adapter.execute(
                {"action": "navigate", "url": "https://nonexistent-domain-test.org/"},
                context=None,
            )
            self.assertFalse(res.ok)
            self.assertEqual(res.error, "DNSResolutionError")
            self.assertNotEqual(res.error, "SecurityViolation")
            self.assertIn("Browser navigation failed", res.message)
            self.assertNotIn("SecurityViolation", res.message)

    def test_ssrf_protection_loopback(self):
        """B. SSRF protection: 127.0.0.1 -> SecurityViolation."""
        for loopback_url in ["http://127.0.0.1:80/", "https://127.0.0.1:443/", "http://localhost:80/"]:
            is_valid, canonical, sec_err = self.playwright_policy.validate_navigation_url(loopback_url)
            self.assertFalse(is_valid)
            self.assertEqual(getattr(sec_err, "error_type", None), "SecurityViolation")

            res: ExecutionResult = self.adapter.execute(
                {"action": "navigate", "url": loopback_url},
                context=None,
            )
            self.assertFalse(res.ok)
            self.assertEqual(res.error, "SecurityViolation")
            self.assertIn("Browser navigation blocked", res.message)

    def test_ssrf_protection_private_ip(self):
        """C. Private IP protection: 10.0.0.1 and RFC-1918 -> SecurityViolation."""
        for private_url in ["http://10.0.0.1:80/", "http://192.168.1.1:80/", "http://172.16.0.1:80/"]:
            is_valid, canonical, sec_err = self.playwright_policy.validate_navigation_url(private_url)
            self.assertFalse(is_valid)
            self.assertEqual(getattr(sec_err, "error_type", None), "SecurityViolation")

            res: ExecutionResult = self.adapter.execute(
                {"action": "navigate", "url": private_url},
                context=None,
            )
            self.assertFalse(res.ok)
            self.assertEqual(res.error, "SecurityViolation")
            self.assertIn("Browser navigation blocked", res.message)

    def test_ssrf_protection_metadata_ip(self):
        """D. Metadata IP protection: 169.254.169.254 -> SecurityViolation."""
        for meta_url in ["http://169.254.169.254:80/", "http://instance-data/"]:
            is_valid, canonical, sec_err = self.playwright_policy.validate_navigation_url(meta_url)
            self.assertFalse(is_valid)
            self.assertEqual(getattr(sec_err, "error_type", None), "SecurityViolation")

            res: ExecutionResult = self.adapter.execute(
                {"action": "navigate", "url": meta_url},
                context=None,
            )
            self.assertFalse(res.ok)
            self.assertEqual(res.error, "SecurityViolation")
            self.assertIn("Browser navigation blocked", res.message)

    def test_normal_public_url(self):
        """E. Normal public URL: Valid URL continues to pass existing validation."""
        fake_addr_info = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.215.14", 443))
        ]
        with patch("socket.getaddrinfo", return_value=fake_addr_info):
            is_valid, canonical, sec_err = self.playwright_policy.validate_navigation_url("https://example.com/")
            self.assertTrue(is_valid)
            self.assertEqual(canonical, "https://example.com/")
            self.assertEqual(sec_err, "")

            # Adapter proceeds past validation to tool invocation
            mock_tool_res = MagicMock(spec=MCPToolResult)
            mock_tool_res.is_error = False
            mock_tool_res.get_text_content.return_value = "Page loaded: https://example.com/"
            mock_tool_res.data = {"snapshot": "Example Domain"}
            self.mock_manager.call_tool.return_value = mock_tool_res

            res: ExecutionResult = self.adapter.execute(
                {"action": "navigate", "url": "https://example.com/"},
                context=None,
            )
            self.assertTrue(res.ok)
            self.assertIsNone(res.error)
            self.mock_manager.call_tool.assert_any_call(
                "agent-browser",
                "agent_browser_open",
                {"url": "https://example.com/"},
                timeout=60.0,
            )


if __name__ == "__main__":
    unittest.main()
