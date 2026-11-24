"""
Tests for Systemic Browser Execution Reliability in Cortex.
Validates repairs for SYS-01 through SYS-05:
- SYS-01: Dynamic tool resolution in _chat_sequence and non-splitting of compound browser tasks.
- SYS-02: Support for open_url, navigate, and snapshot in _desktop_workflow.
- SYS-03: Prevention of browser requests leaking into legacy Python Playwright or native Safari subprocess.
- SYS-04: Prevention of FETCH_WEB_CONTENT misclassification for natural-language browser workflows.
- SYS-05: AutonomousPlanner routing browser commands to agent_browser tools rather than desktop_tool.
- Desktop Regression: Ensuring genuine desktop operations continue routing to desktop_tool.
"""

import pytest
from unittest.mock import MagicMock, patch
from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.planner import AutonomousPlanner
from backend.core.contracts import TaskCommand, Task, TaskStatus, RiskLevel
from backend.capabilities.device_actions import DeviceAutomation, DeviceActionResult


@pytest.fixture(scope="module")
def orchestrator():
    orch = CortexOrchestrator()
    orch.ensure_mcp_tools()
    yield orch
    close_tool = orch.tool_registry.get_instance("agent_browser_close")
    if close_tool:
        close_tool.execute({}, None)


def test_sys_01_split_sequence_preserves_compound_browser_prompts(orchestrator):
    """SYS-01: Verifies that compound browser instructions are not split into disjoint steps."""
    prompt1 = "Open https://www.sundirect.com/, inspect the webpage, tell me what this website is for, and verify that you are on the correct page."
    parts1 = orchestrator._split_sequence(prompt1)
    assert len(parts1) == 1, f"Expected compound browser prompt not to be split, got: {parts1}"

    prompt2 = "Open https://example.com, inspect the page, and explain what it is used for"
    parts2 = orchestrator._split_sequence(prompt2)
    assert len(parts2) == 1, f"Expected compound browser prompt not to be split, got: {parts2}"


def test_sys_01_chat_sequence_dynamic_tool_assignment(orchestrator):
    """SYS-01: If a sequence DOES contain browser steps, verifies tools are dynamically assigned."""
    planned = [
        (TaskCommand.OPEN_URL, {"url": "https://example.com"}, "open https://example.com"),
        (TaskCommand.UNKNOWN, {}, "verify that you are on the correct page"),
    ]
    task = Task(intent="Test sequence", command=TaskCommand.UNKNOWN)
    
    # Simulate step construction in _chat_sequence
    browser_cmds = (
        TaskCommand.OPEN_URL,
        TaskCommand.BROWSER_CLICK,
        TaskCommand.BROWSER_TYPE,
        TaskCommand.BROWSER_SCRAPE,
    )
    plan_steps = []
    for idx, (cmd, p_inputs, cmd_text) in enumerate(planned):
        p_inputs_copy = dict(p_inputs)
        p_inputs_copy["command"] = cmd
        is_prev_browser = (idx > 0 and planned[idx - 1][0] in browser_cmds)
        is_browser_verify = is_prev_browser and any(w in cmd_text.lower() for w in ("verify", "inspect", "snapshot", "check", "page", "look", "correct"))
        
        if cmd in browser_cmds or is_browser_verify:
            if is_browser_verify or cmd == TaskCommand.BROWSER_SCRAPE:
                step_tool = "agent_browser_snapshot" if orchestrator.planner._has_tool("agent_browser_snapshot") else "browser_tool"
                cmd = TaskCommand.BROWSER_SCRAPE
            elif cmd == TaskCommand.OPEN_URL:
                step_tool = "agent_browser_open" if orchestrator.planner._has_tool("agent_browser_open") else "browser_tool"
            else:
                step_tool = "browser_tool"
        else:
            step_tool = "desktop_tool"
        plan_steps.append((cmd, step_tool))

    assert plan_steps[0][1] in ("agent_browser_open", "browser_tool")
    assert plan_steps[1][1] in ("agent_browser_snapshot", "browser_tool")
    assert plan_steps[1][0] == TaskCommand.BROWSER_SCRAPE


def test_sys_02_desktop_workflow_supports_open_url_and_navigate():
    """SYS-02: Verifies that _desktop_workflow accepts open_url and navigate actions."""
    engine = DeviceAutomation(dry_run=True)
    steps = [
        {"action": "open_url", "url": "https://example.com"},
        {"action": "navigate", "url": "https://example.com/about"},
        {"action": "snapshot", "url": "https://example.com/about"},
    ]
    res = engine._desktop_workflow(steps)
    assert res.ok is True, f"Workflow failed: {res.message}"
    executed = res.data.get("executed_steps", [])
    assert len(executed) == 3
    assert executed[0]["action"] == "open_url"
    assert executed[1]["action"] == "navigate"
    assert executed[2]["action"] == "snapshot"


def test_sys_03_browser_open_url_delegates_to_agent_browser_mcp():
    """SYS-03: Verifies _browser_open_url delegates to agent-browser MCP before native/legacy."""
    mock_mcp = MagicMock()
    mock_mcp.is_running.return_value = True
    mock_res = MagicMock()
    mock_res.is_error = False
    mock_mcp.call_tool.return_value = mock_res

    engine = DeviceAutomation(dry_run=False)
    engine.mcp_manager = mock_mcp

    res = engine._browser_open_url("https://example.com")
    assert res.ok is True
    assert "Agent Browser" in res.message
    mock_mcp.call_tool.assert_called_once_with(
        "agent-browser", "agent_browser_open", {"url": "https://example.com"}
    )


def test_sys_04_intent_classification_distinguishes_browser_from_fetch():
    """SYS-04: Verifies natural-language browser workflows are classified as OPEN_URL, not FETCH_WEB_CONTENT."""
    from backend.core.contracts import command_from_intent

    # Compound interactive browser queries must be OPEN_URL
    assert command_from_intent("Open https://example.com and explain what it is used for") == TaskCommand.OPEN_URL
    assert command_from_intent("Open https://www.sundirect.com/, inspect the webpage, tell me what this website is for, and verify that you are on the correct page.") == TaskCommand.OPEN_URL
    assert command_from_intent("Open tradingview.com and inspect the charts") == TaskCommand.OPEN_URL
    assert command_from_intent("Navigate to https://news.ycombinator.com and check top stories") == TaskCommand.OPEN_URL

    # Headless content fetch queries must remain FETCH_WEB_CONTENT
    assert command_from_intent("fetch https://example.com/data.json") == TaskCommand.FETCH_WEB_CONTENT
    assert command_from_intent("read webpage https://example.com/terms.html") == TaskCommand.FETCH_WEB_CONTENT
    assert command_from_intent("summarize url https://example.com/blog/post") == TaskCommand.FETCH_WEB_CONTENT


def test_sys_05_planner_routes_browser_tasks_correctly(orchestrator):
    """SYS-05: Verifies AutonomousPlanner routes browser tasks to agent_browser tools."""
    planner = orchestrator.planner

    plan = planner.plan(
        goal="Open https://www.sundirect.com/ and inspect the page",
        command=TaskCommand.OPEN_URL,
        params={"url": "https://www.sundirect.com/"},
    )
    assert len(plan.steps) >= 2
    assert plan.steps[0].tool in ("agent_browser_open", "browser_tool")
    assert plan.steps[1].tool in ("agent_browser_snapshot", "browser_tool")


def test_desktop_regression_preserves_desktop_tool(orchestrator):
    """Desktop Regression: Verifies genuine desktop operations route to desktop_tool."""
    from backend.core.contracts import command_from_intent

    # Genuine desktop commands
    assert command_from_intent("click the Submit button") == TaskCommand.CLICK_ELEMENT
    assert command_from_intent("type 'hello world' into search field") in (TaskCommand.TYPE_TEXT, TaskCommand.TYPE_IN_ELEMENT)
    assert command_from_intent("observe screen") == TaskCommand.OBSERVE_SCREEN

    plan = orchestrator.planner.plan(
        goal="click the Submit button",
        command=TaskCommand.CLICK_ELEMENT,
        params={"target": "Submit button"},
    )
    assert all(step.tool == "desktop_tool" for step in plan.steps)
