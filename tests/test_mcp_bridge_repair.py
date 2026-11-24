import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

from backend.mcp.manager import MCPServerManager
from backend.mcp.registry import MCPRegistryBridge
from backend.tools.registry import ToolRegistry
from backend.mcp.models import MCPServerConfig, MCPServerStatus, MCPToolDefinition, RiskLevel
from backend.agent.policy import PolicyEngine
from backend.agent.langgraph_engine import LangGraphExecutionEngine
from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities.device_actions import DeviceAutomation


class TestMCPBridgeRepair(unittest.TestCase):
    """Tests verifying Sprint Step 1 MCP Bridge Repair and Tool Discovery."""

    def setUp(self):
        self.tool_registry = ToolRegistry()
        self.manager = MCPServerManager()
        self.bridge = MCPRegistryBridge(manager=self.manager, tool_registry=self.tool_registry)

    def tearDown(self):
        if hasattr(self, "manager") and self.manager:
            self.manager.shutdown()

    def test_01_bridge_exposes_both_sync_methods(self):
        """Verifies that both sync_tools() and sync_all_tools() exist and return integer count."""
        self.assertTrue(hasattr(self.bridge, "sync_all_tools"))
        self.assertTrue(hasattr(self.bridge, "sync_tools"))
        c1 = self.bridge.sync_all_tools()
        c2 = self.bridge.sync_tools()
        self.assertEqual(c1, 0)
        self.assertEqual(c2, 0)

    def test_02_discovery_registers_canonical_and_alias_in_tool_registry(self):
        """Verifies that tool definitions are registered into active Cortex ToolRegistry."""
        sample_defn = MCPToolDefinition(
            name="read_file",
            server_name="filesystem",
            description="Read file contents",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        )
        # Mock managed server with discovered tools
        mock_server = MagicMock()
        mock_server.tools = {"read_file": sample_defn}
        self.manager._servers["filesystem"] = mock_server

        count = self.bridge.sync_all_tools()
        self.assertEqual(count, 1)

        # Canonical name
        canonical = self.tool_registry.get("mcp__filesystem__read_file")
        self.assertIsNotNone(canonical)
        self.assertEqual(canonical.name, "mcp__filesystem__read_file")

        # Alias name
        alias = self.tool_registry.get("mcp_read_file")
        self.assertIsNotNone(alias)
        self.assertEqual(alias.name, "mcp_read_file")

        # Instance in registry
        inst = self.tool_registry.get_instance("mcp_read_file")
        self.assertIsNotNone(inst)

    def test_03_langgraph_resolves_mcp_tools(self):
        """Verifies that LangGraphExecutionEngine resolves discovered MCP tools."""
        sample_fetch = MCPToolDefinition(
            name="fetch",
            server_name="fetch",
            description="Fetch web content",
            input_schema={"type": "object", "properties": {"url": {"type": "string"}}},
        )
        mock_server = MagicMock()
        mock_server.tools = {"fetch": sample_fetch}
        self.manager._servers["fetch"] = mock_server

        self.bridge.sync_all_tools()

        engine = LangGraphExecutionEngine(registry=self.tool_registry, policy_engine=PolicyEngine())
        resolved = engine._get_tool_for_name("mcp_fetch")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.original_tool_name, "fetch")
        self.assertEqual(resolved.server_name, "fetch")

    def test_04_repeated_synchronization_does_not_duplicate_tools(self):
        """Verifies idempotency: calling sync repeatedly does not inflate registry tools."""
        sample_tool = MCPToolDefinition(
            name="navigate",
            server_name="browser",
            description="Navigate URL",
            input_schema={"type": "object"},
        )
        mock_server = MagicMock()
        mock_server.tools = {"navigate": sample_tool}
        self.manager._servers["browser"] = mock_server

        c1 = self.bridge.sync_all_tools()
        total_tools_1 = len(self.tool_registry.list_all())
        total_inst_1 = len(self.tool_registry._instances)

        c2 = self.bridge.sync_all_tools()
        total_tools_2 = len(self.tool_registry.list_all())
        total_inst_2 = len(self.tool_registry._instances)

        self.assertEqual(c1, 1)
        self.assertEqual(c2, 1)
        self.assertEqual(total_tools_1, total_tools_2)
        self.assertEqual(total_inst_1, total_inst_2)

    def test_05_server_startup_failure_handled_safely_without_crashing(self):
        """Verifies that individual MCP server failure is logged and does not crash orchestrator."""
        orch = CortexOrchestrator(automation=DeviceAutomation(dry_run=True), use_gemini=False)
        # Register a failing server
        failing_cfg = MCPServerConfig(
            name="broken_server",
            command="nonexistent_binary_xyz_123",
            args=[],
            enabled=True,
            timeout_seconds=1.0,
        )
        orch.mcp_manager.register_server(failing_cfg)

        # ensure_mcp_tools must handle the error cleanly and return an int
        count = orch.ensure_mcp_tools()
        self.assertIsInstance(count, int)
        # Verify server status marked ERROR without crashing
        srv = orch.mcp_manager._servers.get("broken_server")
        self.assertIn(srv.status, [MCPServerStatus.ERROR, MCPServerStatus.STOPPED])

    def test_06_existing_native_tools_remain_functional(self):
        """Verifies that native tools (desktop_tool, browser_tool, file_tool, mail_tool) exist."""
        for native in ["desktop_tool", "browser_tool", "file_tool", "mail_tool", "web_search"]:
            self.assertIsNotNone(
                self.tool_registry.get(native) or self.tool_registry.get_instance(native),
                f"Native tool {native} must remain functional",
            )


if __name__ == "__main__":
    unittest.main()
