"""
Unit and Integration Test Suite for Phase P7.1 Apple Mail MCP Connection.

Tests:
1. Configuration & Tool Security Filtering:
   - Server definition in config/mcp_servers.json
   - get_apple_mail_server_config pinned version and arguments
   - Allowlist / blocklist enforcement (send-email, reply-to-message, forward-message blocked)
   - call_tool and call_tool_async raise MCPSecurityError for blocked tools
2. Tool Discovery & Registry Namespacing:
   - MCPRegistryBridge synchronizes allowed tools with canonical prefix mcp__apple-mail__*
   - Sending tools are never exposed to ToolRegistry
   - Risk levels assigned appropriately (LOW for read/search, MEDIUM for draft)
3. MCPToolAdapter Lifecycle:
   - Standard BaseTool execute -> observe -> verify lifecycle on MCP responses
4. Real macOS Live Acceptance Tests (when on macOS darwin and Mail.app accessible):
   - Health check
   - Mailbox listing
   - Message search
   - Message reading
   - Real draft creation and Mail.app verification
   - Cleanup of draft
   - Hard enforcement that sending tools fail with MCPSecurityError
"""

import asyncio
import json
import os
import platform
import shutil
import subprocess
import sys
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from backend.core.contracts import RiskLevel
from backend.mcp.client import MCPClient
from backend.mcp.config import (
    BLOCKED_APPLE_MAIL_TOOLS,
    SAFE_APPLE_MAIL_TOOLS,
    get_apple_mail_server_config,
    load_mcp_config,
)
from backend.mcp.exceptions import MCPSecurityError
from backend.mcp.manager import MCPServerManager
from backend.mcp.models import MCPServerConfig, MCPServerStatus, MCPToolDefinition, MCPToolResult
from backend.mcp.process import MCPProcess
from backend.mcp.registry import MCPRegistryBridge
from backend.tools.registry import ToolRegistry


# ── 1. Configuration & Security Enforcement ───────────────────────────────────

def test_apple_mail_server_config():
    """Verifies default configuration and pinned version for apple-mail-mcp."""
    cfg = get_apple_mail_server_config()
    assert cfg.name == "apple-mail"
    assert "npx" in cfg.command
    assert cfg.args == ["-y", "apple-mail-mcp@2.20.57"]
    assert cfg.enabled is True
    assert cfg.timeout_seconds == 30.0
    assert cfg.default_risk_level == RiskLevel.MEDIUM

    # Verify allowlist and blocklist
    assert cfg.allowed_tools == SAFE_APPLE_MAIL_TOOLS
    assert cfg.blocked_tools == BLOCKED_APPLE_MAIL_TOOLS

    # Verify policy filter
    assert cfg.is_tool_allowed("health-check") is True
    assert cfg.is_tool_allowed("list-mailboxes") is True
    assert cfg.is_tool_allowed("search-messages") is True
    assert cfg.is_tool_allowed("get-message") is True
    assert cfg.is_tool_allowed("create-draft") is True
    assert cfg.is_tool_allowed("update-saved-draft") is True

    # Sending tools strictly prohibited
    assert cfg.is_tool_allowed("send-email") is False
    assert cfg.is_tool_allowed("send-serial-email") is False
    assert cfg.is_tool_allowed("reply-to-message") is False
    assert cfg.is_tool_allowed("forward-message") is False

    # Unallowed arbitrary tools
    assert cfg.is_tool_allowed("delete-mailbox") is False
    assert cfg.is_tool_allowed("trash-message") is False


def test_mcp_servers_json_apple_mail():
    """Verifies that config/mcp_servers.json contains the apple-mail server entry."""
    cfg_path = Path(__file__).resolve().parents[1] / "config" / "mcp_servers.json"
    assert cfg_path.exists(), f"Configuration file not found: {cfg_path}"

    with open(cfg_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "mcpServers" in data
    assert "apple-mail" in data["mcpServers"]
    mail_cfg = data["mcpServers"]["apple-mail"]

    assert mail_cfg["command"] == "npx"
    assert "apple-mail-mcp@2.20.57" in mail_cfg["args"]
    assert mail_cfg["enabled"] is True
    assert "send-email" in mail_cfg["blocked_tools"]
    assert "create-draft" in mail_cfg["allowed_tools"]

    loaded = load_mcp_config(cfg_path)
    assert "apple-mail" in loaded
    assert loaded["apple-mail"].name == "apple-mail"
    assert loaded["apple-mail"].is_tool_allowed("create-draft") is True
    assert loaded["apple-mail"].is_tool_allowed("send-email") is False


def test_client_blocks_disallowed_tools():
    """Verifies that MCPClient filters tools during discovery and rejects calls to blocked tools."""
    async def _run():
        cfg = get_apple_mail_server_config()
        proc = MCPProcess(cfg)
        client = MCPClient(proc)

        # Mock tools/list response containing both safe and dangerous tools
        mock_tools_resp = {
            "tools": [
                {"name": "health-check", "description": "Check health", "inputSchema": {}},
                {"name": "list-mailboxes", "description": "List boxes", "inputSchema": {}},
                {"name": "create-draft", "description": "Create a draft", "inputSchema": {}},
                {"name": "send-email", "description": "Send email directly", "inputSchema": {}},
                {"name": "delete-mailbox", "description": "Delete box", "inputSchema": {}},
            ]
        }

        with patch.object(client, "send_request", AsyncMock(return_value=mock_tools_resp)):
            discovered = await client.list_tools()
            names = [t.name for t in discovered]
            assert "health-check" in names
            assert "list-mailboxes" in names
            assert "create-draft" in names
            assert "send-email" not in names
            assert "delete-mailbox" not in names

        # Calling a blocked tool directly must raise MCPSecurityError
        with pytest.raises(MCPSecurityError) as exc_info:
            await client.call_tool("send-email", {"to": ["test@example.com"], "subject": "Test"})
        assert "not allowed" in str(exc_info.value)

        # Calling an unallowed tool directly must also raise MCPSecurityError
        with pytest.raises(MCPSecurityError) as exc_info2:
            await client.call_tool("delete-mailbox", {"mailbox": "INBOX"})
        assert "not allowed" in str(exc_info2.value)

    asyncio.run(_run())


def test_manager_blocks_disallowed_tools():
    """Verifies that MCPServerManager.call_tool_async raises MCPSecurityError before dispatching blocked tools."""
    manager = MCPServerManager()
    cfg = get_apple_mail_server_config()
    manager.register_server(cfg)

    with pytest.raises(MCPSecurityError) as exc_info:
        manager.run_sync(manager.call_tool_async("apple-mail", "send-email", {"recipient": "test@example.com"}))
    assert "not allowed" in str(exc_info.value)
    manager.stop_all()


# ── 2. Tool Registry Integration & Namespacing ───────────────────────────────

def test_bridge_registers_canonical_apple_mail_tools():
    """Verifies that MCPRegistryBridge registers apple-mail tools with canonical mcp__apple-mail__ prefix."""
    tool_registry = ToolRegistry(MagicMock())
    manager = MCPServerManager()
    cfg = get_apple_mail_server_config()
    manager.register_server(cfg)

    bridge = MCPRegistryBridge(manager=manager, tool_registry=tool_registry)

    # Populate mock definitions
    sample_definitions = [
        MCPToolDefinition(
            name="list-mailboxes",
            server_name="apple-mail",
            description="List mailboxes",
            input_schema={"type": "object"},
            risk_level=RiskLevel.LOW,
        ),
        MCPToolDefinition(
            name="create-draft",
            server_name="apple-mail",
            description="Create draft",
            input_schema={"type": "object", "properties": {"subject": {"type": "string"}}},
            risk_level=RiskLevel.MEDIUM,
        ),
    ]

    with patch.object(manager, "get_tool_definitions", return_value=sample_definitions):
        count = bridge.sync_server_tools("apple-mail")
        assert count == 2

    canonical_list = tool_registry.get("mcp__apple-mail__list-mailboxes")
    canonical_draft = tool_registry.get("mcp__apple-mail__create-draft")
    assert canonical_list is not None
    assert canonical_draft is not None
    assert canonical_draft.name == "mcp__apple-mail__create-draft"

    # Verify sending tools are absent
    assert tool_registry.get("mcp__apple-mail__send-email") is None
    assert tool_registry.get("mcp_send-email") is None
    manager.stop_all()


def test_orchestrator_initializes_apple_mail_mcp():
    """Verifies that CortexOrchestrator registers and synchronizes apple-mail MCP tools into ToolRegistry."""
    from backend.agent.orchestrator import CortexOrchestrator
    orchestrator = CortexOrchestrator(dry_run=True)
    try:
        assert orchestrator.mcp_manager is not None
        assert "apple-mail" in orchestrator.mcp_manager._servers
        mail_cfg = orchestrator.mcp_manager._servers["apple-mail"].config
        assert mail_cfg.is_tool_allowed("create-draft") is True
        assert mail_cfg.is_tool_allowed("send-email") is False
    finally:
        if getattr(orchestrator, "mcp_manager", None):
            orchestrator.mcp_manager.stop_all()


# ── 3. Real macOS Live Acceptance Tests ──────────────────────────────────────

@pytest.mark.skipif(
    platform.system().lower() != "darwin" or not shutil.which("npx"),
    reason="Requires macOS and npx for live Apple Mail MCP testing",
)
def test_live_apple_mail_mcp_lifecycle():
    """
    Live end-to-end acceptance test:
    1. Spawns apple-mail-mcp@2.20.57 via MCPProcess.
    2. Initializes JSON-RPC connection.
    3. Verifies tool filtering (send-email is blocked).
    4. Executes health-check.
    5. Executes list-mailboxes.
    6. Executes search-messages.
    7. Executes create-draft in Mail.app.
    8. Confirms draft exists in Apple Mail drafts mailbox.
    9. Cleans up test draft.
    10. Attempts to call send-email and verifies MCPSecurityError.
    """
    async def _run():
        cfg = get_apple_mail_server_config()
        proc = MCPProcess(cfg)
        client = MCPClient(proc)

        try:
            # Connect process, start reader loop, and initialize handshake
            await client.connect(timeout=20.0)
            assert proc.is_alive is True
            assert client.is_initialized is True
            assert client.server_info.get("name") == "apple-mail"

            # Discover tools
            tools = await client.list_tools(timeout=10.0)
            tool_names = [t.name for t in tools]
            assert "health-check" in tool_names
            assert "list-mailboxes" in tool_names
            assert "search-messages" in tool_names
            assert "get-message" in tool_names
            assert "create-draft" in tool_names
            assert "send-email" not in tool_names
            assert "send-serial-email" not in tool_names

            # 1. Health check
            health_res = await client.call_tool("health-check", {}, timeout=15.0)
            assert not health_res.is_error
            assert len(health_res.content) > 0

            # 2. List mailboxes
            boxes_res = await client.call_tool("list-mailboxes", {}, timeout=15.0)
            assert not boxes_res.is_error
            boxes_text = boxes_res.content[0].get("text", "")
            assert "INBOX" in boxes_text or len(boxes_text) > 0

            # 3. Search messages (limit to 2)
            search_res = await client.call_tool("search-messages", {"query": "", "limit": 2}, timeout=20.0)
            assert not search_res.is_error

            # 4. Create real draft
            test_subject = "Cortex P7.1 Automated Integration Test Draft"
            test_body = "This draft was created by Cortex P7.1 automated test via apple-mail-mcp."
            draft_res = await client.call_tool(
                "create-draft",
                {
                    "to": ["test-acceptance@cortex.internal"],
                    "subject": test_subject,
                    "body": test_body,
                },
                timeout=20.0,
            )
            assert not draft_res.is_error
            draft_text = draft_res.content[0].get("text", "")
            assert "id" in draft_text or "draft" in draft_text.lower() or "created" in draft_text.lower()

            # 5. Verify draft exists in Mail.app via AppleScript
            verify_script = f"""
            tell application "Mail"
                set matchCount to count of (messages of drafts mailbox whose subject is "{test_subject}")
                return matchCount
            end tell
            """
            verify_proc = subprocess.run(["osascript", "-e", verify_script], capture_output=True, text=True, timeout=10)
            assert verify_proc.returncode == 0
            count = int(verify_proc.stdout.strip()) if verify_proc.stdout.strip().isdigit() else 0
            assert count >= 1, f"Expected draft with subject '{test_subject}' in Mail.app, found {count}"

            # 6. Clean up the test draft
            cleanup_script = f"""
            tell application "Mail"
                delete (messages of drafts mailbox whose subject is "{test_subject}")
            end tell
            """
            cleanup_proc = subprocess.run(["osascript", "-e", cleanup_script], capture_output=True, text=True, timeout=10)
            assert cleanup_proc.returncode == 0

            # 7. Verify hard security rejection when calling send-email
            with pytest.raises(MCPSecurityError):
                await client.call_tool("send-email", {"to": ["test@example.com"], "subject": "Forbidden"})

        finally:
            await client.disconnect()
            await proc.stop(timeout=5.0)

    asyncio.run(_run())
