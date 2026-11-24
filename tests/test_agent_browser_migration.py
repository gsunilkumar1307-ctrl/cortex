"""
Tests for Official Vercel Agent Browser Migration into Cortex.
Verifies MCP bridge registration, LangGraph tool selection, BaseTool lifecycle,
and absence of silent fallback to native Playwright.
"""

import pytest
from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.planner import AutonomousPlanner
from backend.core.contracts import TaskCommand, RiskLevel
from backend.mcp.agent_browser_adapter import MCPAgentBrowserToolAdapter


@pytest.fixture(scope="module")
def orchestrator():
    orch = CortexOrchestrator()
    orch.ensure_mcp_tools()
    yield orch
    close_tool = orch.tool_registry.get_instance("agent_browser_close")
    if close_tool:
        close_tool.execute({}, None)


def test_agent_browser_server_configured_and_connected(orchestrator):
    """Verifies agent-browser MCP server is registered, connected, and discovered."""
    manager = orchestrator.mcp_manager
    assert "agent-browser" in manager._servers
    server = manager._servers["agent-browser"]
    assert len(server.tools) >= 30
    assert "agent_browser_open" in server.tools
    assert "agent_browser_snapshot" in server.tools
    assert "agent_browser_click" in server.tools
    assert "agent_browser_fill" in server.tools


def test_agent_browser_tools_registered_in_tool_registry(orchestrator):
    """Verifies official agent_browser tools and canonical names exist in ToolRegistry."""
    registry = orchestrator.tool_registry
    
    # Direct names
    assert registry.get_instance("agent_browser_open") is not None
    assert registry.get_instance("agent_browser_snapshot") is not None
    assert registry.get_instance("agent_browser_click") is not None
    assert registry.get_instance("agent_browser_fill") is not None
    assert registry.get_instance("agent_browser_close") is not None

    # Canonical names
    assert registry.get_instance("mcp__agent-browser__agent_browser_open") is not None
    assert registry.get_instance("mcp__agent-browser__agent_browser_snapshot") is not None

    # Verify adapter class
    adapter = registry.get_instance("agent_browser_open")
    assert isinstance(adapter, MCPAgentBrowserToolAdapter)


def test_browser_tool_and_aliases_bound_to_agent_browser(orchestrator):
    """Verifies that generic browser_tool and mcp_browser_* aliases route to Agent Browser."""
    registry = orchestrator.tool_registry
    
    browser_tool = registry.get_instance("browser_tool")
    assert isinstance(browser_tool, MCPAgentBrowserToolAdapter)
    
    mcp_nav = registry.get_instance("mcp_browser_navigate")
    assert isinstance(mcp_nav, MCPAgentBrowserToolAdapter)
    
    mcp_snap = registry.get_instance("mcp_browser_snapshot")
    assert isinstance(mcp_snap, MCPAgentBrowserToolAdapter)
    
    mcp_click = registry.get_instance("mcp_browser_click")
    assert isinstance(mcp_click, MCPAgentBrowserToolAdapter)


def test_autonomous_planner_prioritizes_agent_browser(orchestrator):
    """Verifies AutonomousPlanner selects official agent_browser_* tools for OPEN_URL."""
    planner = AutonomousPlanner(orchestrator.tool_registry)
    plan = planner.plan(
        goal="Open https://example.com using Agent Browser and tell me the page title.",
        command=TaskCommand.OPEN_URL,
        params={"url": "https://example.com"},
    )
    assert len(plan.steps) >= 2
    assert plan.steps[0].tool == "agent_browser_open"
    assert plan.steps[1].tool == "agent_browser_snapshot"


def test_agent_browser_navigation_execution(orchestrator):
    """Test A: Verifies live navigation and title retrieval via Agent Browser."""
    nav_tool = orchestrator.tool_registry.get_instance("agent_browser_open")
    res = nav_tool.execute({"url": "https://example.com"}, None)
    assert res.ok is True
    assert "Example Domain" in res.message or "example.com" in res.data.get("url", "")
    assert res.data.get("title") == "Example Domain"


def test_agent_browser_snapshot_and_interaction(orchestrator):
    """Test B: Verifies accessibility tree snapshot and element clicking."""
    nav_tool = orchestrator.tool_registry.get_instance("agent_browser_open")
    nav_tool.execute({"url": "https://example.com"}, None)
    snap_tool = orchestrator.tool_registry.get_instance("agent_browser_snapshot")
    res_snap = snap_tool.execute({}, None)
    assert res_snap.ok is True
    assert "Learn more" in res_snap.data.get("snapshot", "")

    # Click @e1 or resolved link ref
    import re
    m = re.search(r'\[ref=([a-zA-Z0-9]+)\]', res_snap.data.get("snapshot", ""))
    ref = f"@{m.group(1)}" if m else "@e1"
    click_tool = orchestrator.tool_registry.get_instance("agent_browser_click")
    res_click = click_tool.execute({"selector": ref}, None)
    assert res_click.ok is True

    # Check that URL updated
    url_tool = orchestrator.tool_registry.get_instance("agent_browser_get_url")
    res_url = url_tool.execute({}, None)
    assert "iana.org" in res_url.data.get("url", "")


def test_agent_browser_error_handling_no_silent_fallback(orchestrator):
    """Test E: Verifies safety violation and failed domain do not switch engines."""
    nav_tool = orchestrator.tool_registry.get_instance("agent_browser_open")
    
    # 1. Blocked private IP
    res_sec = nav_tool.execute({"url": "http://169.254.169.254/metadata"}, None)
    assert res_sec.ok is False
    assert res_sec.error == "SecurityViolation"

    # 2. Non-existent domain
    res_fail = nav_tool.execute({"url": "https://non-existent-site-9876543210.org"}, None)
    assert res_fail.ok is False
    assert res_fail.error in ("SecurityViolation", "NavigationError", "DNSResolutionError")

    # 3. Confirm engine remains Agent Browser
    current_browser_tool = orchestrator.tool_registry.get_instance("browser_tool")
    assert isinstance(current_browser_tool, MCPAgentBrowserToolAdapter)


def test_native_tools_remain_functional(orchestrator):
    """Verifies that native tools are still present and functional."""
    registry = orchestrator.tool_registry
    assert registry.get_instance("desktop_tool") is not None
    assert registry.get_instance("file_tool") is not None
    assert registry.get_instance("mail_tool") is not None


def test_generic_passthrough_extract_structured_data_unit(orchestrator):
    """Unit test verifying _extract_structured_data handles all MCPToolResult variants without AttributeError."""
    from backend.mcp.models import MCPToolResult
    
    adapter = orchestrator.tool_registry.get_instance("agent_browser_eval")
    assert adapter is not None

    # 1. Nested structuredContent -> response -> data
    r1 = MCPToolResult(
        content=[{"type": "text", "text": "result text"}],
        is_error=False,
        raw_response={"structuredContent": {"response": {"data": {"val": 42}}}},
    )
    d1 = adapter._extract_structured_data(r1)
    assert d1 == {"val": 42}

    # 2. Nested structuredContent -> response (dict without data)
    r2 = MCPToolResult(
        content="res",
        is_error=False,
        raw_response={"structuredContent": {"response": {"outcome": "success"}}},
    )
    d2 = adapter._extract_structured_data(r2)
    assert d2 == {"outcome": "success"}

    # 3. Direct dictionary raw_response
    r3 = MCPToolResult(
        content=[],
        is_error=False,
        raw_response={"custom_field": "test"},
    )
    d3 = adapter._extract_structured_data(r3)
    assert d3 == {"custom_field": "test"}

    # 4. JSON formatted text fallback
    r4 = MCPToolResult(
        content='{"data": {"tabs": ["t1", "t2"]}}',
        is_error=False,
        raw_response=None,
    )
    d4 = adapter._extract_structured_data(r4)
    assert d4 == {"tabs": ["t1", "t2"]}

    # 5. Empty / None raw response
    r5 = MCPToolResult(content="", is_error=False, raw_response=None)
    assert adapter._extract_structured_data(r5) == {}
    assert adapter._extract_structured_data(None) == {}


def test_generic_passthrough_live_execution(orchestrator):
    """Verifies that generic tools (eval, wait, tab_list, read) execute without AttributeError."""
    registry = orchestrator.tool_registry
    
    # Ensure open
    registry.get_instance("agent_browser_open").execute({"url": "https://example.com"}, None)

    # 1. Eval (read document.title)
    eval_tool = registry.get_instance("agent_browser_eval")
    res_eval = eval_tool.execute({"script": "document.title"}, None)
    assert res_eval.ok is True
    assert res_eval.data.get("result") == "Example Domain"

    # 2. Wait
    wait_tool = registry.get_instance("agent_browser_wait_ms")
    res_wait = wait_tool.execute({"ms": 50}, None)
    assert res_wait.ok is True
    assert isinstance(res_wait.data, dict)

    # 3. Tab List
    tab_tool = registry.get_instance("agent_browser_tab_list")
    res_tabs = tab_tool.execute({}, None)
    assert res_tabs.ok is True
    assert "tabs" in res_tabs.data

    # 4. Read
    read_tool = registry.get_instance("agent_browser_read")
    res_read = read_tool.execute({"url": "https://example.com"}, None)
    assert res_read.ok is True
    assert "Example Domain" in res_read.message or "documentation examples" in res_read.message

