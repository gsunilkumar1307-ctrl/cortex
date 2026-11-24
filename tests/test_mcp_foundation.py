from __future__ import annotations

import os
import sys
import time
from pathlib import Path
import pytest

from backend.core.contracts import (
    ExecutionError,
    ExecutionResult,
    Plan,
    PlanStep,
    RiskLevel,
    Task,
    TaskCommand,
    TaskStatus,
)
from backend.agent.execution_engine import ExecutionEngine
from backend.agent.policy import PolicyEngine
from backend.tools.registry import ToolRegistry
from backend.persistence import TaskStore

from backend.mcp.adapter import MCPToolAdapter
from backend.mcp.client import MCPClient
from backend.mcp.config import sanitize_environment, validate_server_config
from backend.mcp.exceptions import (
    MCPConfigurationError,
    MCPConnectionError,
    MCPProcessError,
    MCPSecurityError,
    MCPTimeoutError,
    MCPValidationError,
)
from backend.mcp.manager import MCPServerManager
from backend.mcp.models import MCPServerConfig, MCPServerStatus, MCPToolDefinition
from backend.mcp.process import MCPProcess
from backend.mcp.registry import MCPRegistryBridge

MOCK_SERVER_SCRIPT = str(Path(__file__).parent / "mock_mcp_server.py")


def create_mock_server_config(
    name: str = "mock_server",
    allowed_tools: list[str] | None = None,
    blocked_tools: list[str] | None = None,
    requires_approval: bool = False,
    timeout_seconds: float = 5.0,
) -> MCPServerConfig:
    return MCPServerConfig(
        name=name,
        command=sys.executable,
        args=[MOCK_SERVER_SCRIPT],
        env={"TEST_MODE": "1"},
        timeout_seconds=timeout_seconds,
        auto_restart=True,
        allowed_tools=allowed_tools,
        blocked_tools=blocked_tools or [],
        requires_approval=requires_approval,
    )


# ── 1. Server Startup ─────────────────────────────────────────────────────────

def test_mcp_server_startup():
    config = create_mock_server_config()
    manager = MCPServerManager()
    manager.register_server(config)
    try:
        manager.start_server("mock_server", timeout=5.0)
        status = manager.get_server_status("mock_server")
        server = manager._servers["mock_server"]
        assert status == MCPServerStatus.CONNECTED
        assert server.process.is_alive
    finally:
        manager.shutdown()


# ── 2. Server Shutdown ────────────────────────────────────────────────────────

def test_mcp_server_shutdown():
    config = create_mock_server_config()
    manager = MCPServerManager()
    manager.register_server(config)
    try:
        manager.start_server("mock_server", timeout=5.0)
        server = manager._servers["mock_server"]
        assert server.process.is_alive
        manager.stop_server("mock_server", timeout=3.0)
        assert not server.process.is_alive
        assert manager.get_server_status("mock_server") == MCPServerStatus.STOPPED
    finally:
        manager.shutdown()


# ── 3. Session Initialization ─────────────────────────────────────────────────

def test_mcp_session_initialization():
    config = create_mock_server_config()
    manager = MCPServerManager()
    manager.register_server(config)
    try:
        manager.start_server("mock_server", timeout=5.0)
        server = manager._servers["mock_server"]
        assert server.client.is_initialized
        assert server.client.server_info.get("name") == "mock-mcp-server"
        assert server.client.server_info.get("version") == "1.0.0"

        # Verify ping
        pings = manager.ping_all(timeout=3.0)
        assert pings.get("mock_server") is True
    finally:
        manager.shutdown()


# ── 4. Tool Discovery ─────────────────────────────────────────────────────────

def test_mcp_tool_discovery():
    config = create_mock_server_config()
    manager = MCPServerManager()
    manager.register_server(config)
    try:
        manager.start_server("mock_server")
        tools = manager.get_tool_definitions("mock_server")
        tool_names = {t.name for t in tools}
        assert "echo" in tool_names
        assert "calculate_sum" in tool_names
        assert "fail_action" in tool_names
        assert "empty_action" in tool_names
    finally:
        manager.shutdown()


# ── 5. Dynamic Registration ───────────────────────────────────────────────────

def test_mcp_dynamic_registration():
    config = create_mock_server_config()
    manager = MCPServerManager()
    manager.register_server(config)
    tool_registry = ToolRegistry()
    bridge = MCPRegistryBridge(manager, tool_registry)

    try:
        manager.start_server("mock_server")
        count = bridge.sync_all_tools()
        assert count > 0

        # Check registered tool instances
        canonical = "mcp__mock_server__echo"
        alias = "mcp_echo"
        assert tool_registry.get_instance(canonical) is not None
        assert tool_registry.get_instance(alias) is not None

        # Check tool definitions
        defn = tool_registry.get(canonical)
        assert defn is not None
        assert "Echoes back" in defn.description
    finally:
        manager.shutdown()


# ── 6. Tool Invocation ────────────────────────────────────────────────────────

def test_mcp_tool_invocation():
    config = create_mock_server_config()
    manager = MCPServerManager()
    manager.register_server(config)
    tool_registry = ToolRegistry()
    bridge = MCPRegistryBridge(manager, tool_registry)

    try:
        manager.start_server("mock_server")
        bridge.sync_all_tools()

        tool_inst = tool_registry.get_instance("mcp__mock_server__echo")
        assert tool_inst is not None

        # Execute echo tool
        res: ExecutionResult = tool_inst.execute({"message": "Alpha Protocol"})
        assert res.ok is True
        assert "Echo: Alpha Protocol" in res.message

        # Execute calculate_sum tool
        calc_inst = tool_registry.get_instance("mcp__mock_server__calculate_sum")
        res_calc: ExecutionResult = calc_inst.execute({"a": 15, "b": 27})
        assert res_calc.ok is True
        assert "42" in res_calc.message
    finally:
        manager.shutdown()


# ── 7. Invalid Arguments ──────────────────────────────────────────────────────

def test_mcp_invalid_arguments():
    config = create_mock_server_config()
    manager = MCPServerManager()
    manager.register_server(config)
    tool_registry = ToolRegistry()
    bridge = MCPRegistryBridge(manager, tool_registry)

    try:
        manager.start_server("mock_server")
        bridge.sync_all_tools()

        calc_inst = tool_registry.get_instance("mcp__mock_server__calculate_sum")
        # Missing required parameter "b"
        res: ExecutionResult = calc_inst.execute({"a": 10})
        assert res.ok is False
        assert "ValidationError" in (res.error or "")
        assert "Missing required parameter" in res.message

        # Invalid type for parameter "a"
        res_type: ExecutionResult = calc_inst.execute({"a": "not_a_number", "b": 5})
        assert res_type.ok is False
        assert "ValidationError" in (res_type.error or "")
    finally:
        manager.shutdown()


# ── 8. Invalid Responses ──────────────────────────────────────────────────────

def test_mcp_invalid_responses():
    config = create_mock_server_config()
    manager = MCPServerManager()
    manager.register_server(config)
    tool_registry = ToolRegistry()
    bridge = MCPRegistryBridge(manager, tool_registry)

    try:
        manager.start_server("mock_server")
        bridge.sync_all_tools()

        fail_inst = tool_registry.get_instance("mcp__mock_server__fail_action")
        res: ExecutionResult = fail_inst.execute({})
        assert res.ok is False
        assert "MCPExecutionError" in (res.error or "")
        assert "failed on remote mock tool" in res.message
    finally:
        manager.shutdown()


# ── 9. Connection Failure ─────────────────────────────────────────────────────

def test_mcp_connection_failure():
    # Configure server with non-existent executable
    config = MCPServerConfig(
        name="bad_server",
        command="/non/existent/binary_path",
        args=[],
    )
    manager = MCPServerManager()
    manager.register_server(config)

    try:
        with pytest.raises(Exception):
            manager.start_server("bad_server")
        assert manager.get_server_status("bad_server") == MCPServerStatus.ERROR

        # Invoking a tool on a non-connected server fails with MCPConnectionError, MCPConfigurationError, or MCPProcessError
        with pytest.raises((MCPConnectionError, MCPConfigurationError, MCPProcessError)):
            manager.call_tool("bad_server", "some_tool", {})
    finally:
        manager.shutdown()


# ── 10. Process Termination ───────────────────────────────────────────────────

def test_mcp_process_termination():
    config = create_mock_server_config()
    config.auto_restart = False  # Disable auto-restart to observe termination
    manager = MCPServerManager()
    manager.register_server(config)

    try:
        manager.start_server("mock_server")
        server = manager._servers["mock_server"]
        assert server.process.is_alive

        # Calling crash_process aborts the child process with exit code 42
        try:
            manager.call_tool("mock_server", "crash_process", {})
        except Exception:
            pass

        time.sleep(0.5)
        assert not server.process.is_alive
        assert server.process.returncode == 42
    finally:
        manager.shutdown()


# ── 11. Timeout Handling ──────────────────────────────────────────────────────

def test_mcp_timeout_handling():
    config = create_mock_server_config(timeout_seconds=0.3)
    manager = MCPServerManager()
    manager.register_server(config)
    tool_registry = ToolRegistry()
    bridge = MCPRegistryBridge(manager, tool_registry)

    try:
        manager.start_server("mock_server")
        bridge.sync_all_tools()

        sleep_inst = tool_registry.get_instance("mcp__mock_server__sleep_delay")
        # Tool sleeps for 1.5s but timeout is 0.3s
        res: ExecutionResult = sleep_inst.execute({"seconds": 1.5, "timeout": 0.3})
        assert res.ok is False
        assert "TimeoutError" in (res.error or "")
    finally:
        manager.shutdown()


# ── 12. Reconnection ──────────────────────────────────────────────────────────

def test_mcp_reconnection():
    config = create_mock_server_config()
    manager = MCPServerManager()
    manager.register_server(config)
    tool_registry = ToolRegistry()
    bridge = MCPRegistryBridge(manager, tool_registry)

    try:
        manager.start_server("mock_server")
        bridge.sync_all_tools()

        tool_inst = tool_registry.get_instance("mcp__mock_server__echo")
        res1 = tool_inst.execute({"message": "First session"})
        assert res1.ok is True

        # Restart server
        manager.restart_server("mock_server")
        assert manager.get_server_status("mock_server") == MCPServerStatus.CONNECTED

        # Execute again on reconnected server
        res2 = tool_inst.execute({"message": "Second session"})
        assert res2.ok is True
        assert "Echo: Second session" in res2.message
    finally:
        manager.shutdown()


# ── 13. Duplicate Registration Prevention ─────────────────────────────────────

def test_mcp_duplicate_registration_prevention():
    config = create_mock_server_config()
    manager = MCPServerManager()
    manager.register_server(config)
    tool_registry = ToolRegistry()
    bridge = MCPRegistryBridge(manager, tool_registry)

    try:
        manager.start_server("mock_server")

        # Sync multiple times
        bridge.sync_all_tools()
        initial_instances = len(tool_registry.list_instances())
        initial_defs = len(tool_registry.list_all())

        bridge.sync_all_tools()
        bridge.sync_all_tools()

        # Counts must remain identical
        assert len(tool_registry.list_instances()) == initial_instances
        assert len(tool_registry.list_all()) == initial_defs
    finally:
        manager.shutdown()


# ── 14. Approval Enforcement ──────────────────────────────────────────────────

def test_mcp_approval_enforcement():
    # Configure server with requires_approval=True and HIGH risk
    config = create_mock_server_config(requires_approval=True)
    config.default_risk_level = RiskLevel.HIGH

    manager = MCPServerManager()
    manager.register_server(config)
    tool_registry = ToolRegistry()
    bridge = MCPRegistryBridge(manager, tool_registry)

    try:
        manager.start_server("mock_server")
        bridge.sync_all_tools()

        tool_inst = tool_registry.get_instance("mcp__mock_server__echo")
        assert tool_inst is not None
        assert tool_inst.risk_level == RiskLevel.HIGH
        assert tool_inst.requires_approval is True
    finally:
        manager.shutdown()


# ── 15. Verification Failure ──────────────────────────────────────────────────

def test_mcp_verification_failure():
    config = create_mock_server_config()
    manager = MCPServerManager()
    manager.register_server(config)
    tool_registry = ToolRegistry()
    bridge = MCPRegistryBridge(manager, tool_registry)

    try:
        manager.start_server("mock_server")
        bridge.sync_all_tools()

        empty_inst = tool_registry.get_instance("mcp__mock_server__empty_action")
        exec_res: ExecutionResult = empty_inst.execute({})
        # Empty action returns empty content
        obs = empty_inst.observe({}, exec_res)
        ver = empty_inst.verify({}, obs, exec_res)

        # Verification must fail because empty output has no verifiable proof
        assert ver.verified is False
        assert ver.uncertainty_reason == "EmptyOutput"
    finally:
        manager.shutdown()


# ── 16. Cancellation ──────────────────────────────────────────────────────────

def test_mcp_cancellation():
    config = create_mock_server_config()
    manager = MCPServerManager()
    manager.register_server(config)
    tool_registry = ToolRegistry()
    bridge = MCPRegistryBridge(manager, tool_registry)
    policy = PolicyEngine()
    engine = ExecutionEngine(tool_registry, policy)

    try:
        manager.start_server("mock_server")
        bridge.sync_all_tools()

        # Build plan with sleep step and mark task as cancelled
        step = PlanStep(
            action="Sleep Delay",
            tool="mcp__mock_server__sleep_delay",
            inputs={"seconds": 5.0},
        )
        plan = Plan(goal="Test Cancellation", steps=[step])
        task = Task(intent="Test Cancellation", plan=plan)
        task.cancellation_requested = True

        res = engine.execute_plan(task)
        assert task.status in (TaskStatus.CANCELLED, TaskStatus.CANCELED)
    finally:
        manager.shutdown()


# ── 17. Recovery ──────────────────────────────────────────────────────────────

def test_mcp_recovery():
    defn = MCPToolDefinition(
        name="retry_tool",
        server_name="mock_server",
        description="Tool for recovery test",
        irreversible=False,
    )
    adapter = MCPToolAdapter(defn, manager=None)

    # Attempt 1 should suggest retry
    rec1 = adapter.recover({}, ExecutionError(code="Err", message="Temporary network failure", recoverable=True), attempt=1)
    assert rec1["can_retry"] is True
    assert rec1["strategy"] == "retry"

    # Attempt 3 should escalate
    rec3 = adapter.recover({}, ExecutionError(code="Err", message="Persistent network failure", recoverable=True), attempt=3)
    assert rec3["can_retry"] is False
    assert rec3["strategy"] == "escalate"

    # Irreversible tool should never retry
    defn_irrev = MCPToolDefinition(
        name="irreversible_tool",
        server_name="mock_server",
        description="Irreversible tool",
        irreversible=True,
    )
    adapter_irrev = MCPToolAdapter(defn_irrev, manager=None)
    rec_irrev = adapter_irrev.recover({}, ExecutionError(code="Err", message="Failed", recoverable=True), attempt=1)
    assert rec_irrev["can_retry"] is False


# ── 18. Audit Logging & Security Sanitization ─────────────────────────────────

def test_mcp_audit_logging_and_sanitization(tmp_path):
    db_file = str(tmp_path / "test_cortex.sqlite3")
    store = TaskStore(db_file)

    config = create_mock_server_config()
    manager = MCPServerManager()
    manager.register_server(config)
    tool_registry = ToolRegistry()
    bridge = MCPRegistryBridge(manager, tool_registry)
    policy = PolicyEngine()
    engine = ExecutionEngine(tool_registry, policy)

    try:
        manager.start_server("mock_server")
        bridge.sync_all_tools()

        # Step containing sensitive token that should be redacted in audit
        step = PlanStep(
            action="Echo Secret",
            tool="mcp__mock_server__echo",
            inputs={"message": "Safe text", "api_key": "SUPER_SECRET_TOKEN_123"},
        )
        plan = Plan(goal="Audit Plan", steps=[step])
        task = Task(intent="Audit Task", plan=plan)

        final_res = engine.execute_plan(task)
        assert final_res.status == TaskStatus.COMPLETED

        # Record events to store
        store.save_task(task)
        events = task.events
        assert len(events) > 0

        # Verify environment variable sanitizer strips secrets
        dirty_env = {
            "PATH": "/bin:/usr/bin",
            "GEMINI_API_KEY": "AIzaSySecretKey",
            "CORTEX_SESSION_SECRET": "SessionSecret999",
            "CUSTOM_SAFE_VAR": "ValidValue",
        }
        clean_env = sanitize_environment(dirty_env)
        assert "GEMINI_API_KEY" not in clean_env
        assert "CORTEX_SESSION_SECRET" not in clean_env
        assert clean_env.get("CUSTOM_SAFE_VAR") == "ValidValue"

        # Verify dangerous shell command rejection
        bad_config = MCPServerConfig(
            name="evil_server",
            command="python3; rm -rf /",
            args=[],
        )
        with pytest.raises(MCPSecurityError):
            validate_server_config(bad_config)
    finally:
        manager.shutdown()
