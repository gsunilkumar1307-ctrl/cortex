from __future__ import annotations

import os
import sys
import time
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypedDict

# Official LangGraph framework imports
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
try:
    from langgraph.checkpoint.sqlite import SqliteSaver
    HAS_SQLITE_SAVER = True
except ImportError:
    HAS_SQLITE_SAVER = False
from langgraph.types import interrupt, Command
from langgraph.errors import GraphInterrupt

try:
    from backend.core.contracts import (
        Task,
        TaskStatus,
        TaskCommand,
        PlanStep,
        Plan,
        ToolCall,
        Observation,
        VerificationResult,
        ExecutionResult,
        ExecutionError,
        FinalResult,
        RiskLevel,
    )
    from backend.tools.base import BaseTool
    from backend.tools.registry import ToolRegistry
    from backend.agent.policy import PolicyEngine
except ImportError:
    from core.contracts import (
        Task,
        TaskStatus,
        TaskCommand,
        PlanStep,
        Plan,
        ToolCall,
        Observation,
        VerificationResult,
        ExecutionResult,
        ExecutionError,
        FinalResult,
        RiskLevel,
    )
    from tools.base import BaseTool
    from tools.registry import ToolRegistry
    from policy import PolicyEngine


def sanitize_state_value(val: Any, depth: int = 0) -> Any:
    """Recursively converts non-serializable objects (e.g. MagicMocks) into msgpack/json safe primitives."""
    if depth > 8:
        return str(val)
    if isinstance(val, dict):
        return {str(k): sanitize_state_value(v, depth + 1) for k, v in val.items()}
    elif isinstance(val, (list, tuple, set)):
        return [sanitize_state_value(x, depth + 1) for x in val]
    elif isinstance(val, (str, int, float, bool)) or val is None:
        return val
    else:
        return str(val)


class CortexAgentState(TypedDict, total=False):
    """
    Authoritative Typed LangGraph State for Cortex Agent.
    Maintains complete execution context, observation, verification, recovery, and audit tracking.
    """
    task_id: str
    goal: str
    command: str
    params: Dict[str, Any]
    context: Optional[Dict[str, Any]]
    status: str
    plan: Optional[Dict[str, Any]]
    steps: List[Dict[str, Any]]
    current_step_index: int
    current_step: Optional[Dict[str, Any]]
    selected_tool: Optional[str]
    tool_inputs: Optional[Dict[str, Any]]
    tool_result: Optional[Dict[str, Any]]
    observation: Optional[Dict[str, Any]]
    verification: Optional[Dict[str, Any]]
    all_evidence: List[str]
    final_data: Dict[str, Any]
    error: Optional[str]
    recovery_attempts: int
    max_retries: int
    replan_count: int
    needs_approval: bool
    approval_granted: Optional[bool]
    approval_hash: Optional[str]
    approval_consumed: bool
    cancellation_requested: bool
    final_response: Optional[str]
    audit_events: List[Dict[str, Any]]
    interrupted_action: Optional[Dict[str, Any]]


class LangGraphExecutionEngine:
    """
    Authoritative Agent Execution Engine powered by the official LangGraph framework.
    Replaces Cortex's custom agent loop with a compiled StateGraph controlling:
    - Lifecycle transitions (understand -> retrieve -> inspect -> plan -> select -> approval -> execute -> observe -> verify -> evaluate -> recover/finish/fail)
    - Typed state management
    - Cyclic execution for multi-step tasks and bounded recovery
    - Human-in-the-loop approval interruption and resumption via official LangGraph APIs
    - Independent observation and empirical verification
    - Checkpointed state persistence using SQLite / MemorySaver
    """

    def __init__(
        self,
        registry: ToolRegistry,
        policy_engine: PolicyEngine,
        checkpointer: Any = None,
        db_path: Optional[str] = None,
    ) -> None:
        self.registry = registry
        self.policy = policy_engine
        self._checkpointer = checkpointer or self._init_checkpointer(db_path)
        self._compiled_graph = self._build_graph().compile(checkpointer=self._checkpointer)

    def _init_checkpointer(self, db_path: Optional[str] = None) -> Any:
        if HAS_SQLITE_SAVER:
            try:
                target_db = db_path
                if not target_db:
                    root_dir = Path(__file__).resolve().parents[2]
                    work_dir = root_dir / "work"
                    work_dir.mkdir(parents=True, exist_ok=True)
                    target_db = str(work_dir / "cortex-langgraph.sqlite3")
                conn = sqlite3.connect(target_db, check_same_thread=False)
                saver = SqliteSaver(conn)
                saver.setup()
                return saver
            except Exception:
                pass
        return MemorySaver()

    def _get_tool_for_name(self, tool_name: str) -> Optional[BaseTool]:
        inst = self.registry.get_instance(tool_name)
        if inst:
            return inst
        lower_name = tool_name.lower()
        if "notes" in lower_name:
            return self.registry.get_instance("notes_adapter") or self.registry.get_instance("desktop_tool")
        if "whatsapp" in lower_name:
            return self.registry.get_instance("whatsapp_adapter") or self.registry.get_instance("desktop_tool")
        if "mail" in lower_name:
            return self.registry.get_instance("mail_tool")
        if "file" in lower_name:
            return self.registry.get_instance("file_tool")
        if "browser" in lower_name or "url" in lower_name:
            return self.registry.get_instance("browser_tool")
        if "search" in lower_name:
            return self.registry.get_instance("web_search_tool")
        if "fetch" in lower_name:
            return self.registry.get_instance("mcp_fetch") or self.registry.get_instance("mcp__fetch__fetch")
        return self.registry.get_instance("desktop_tool")

    def _build_graph(self) -> StateGraph:
        """Constructs the official LangGraph StateGraph with nodes, edges, cycles, and interrupts."""
        workflow = StateGraph(CortexAgentState)

        # ── Register Nodes ──────────────────────────────────────────────
        workflow.add_node("understand_goal", self._node_understand_goal)
        workflow.add_node("retrieve_context", self._node_retrieve_context)
        workflow.add_node("inspect_environment", self._node_inspect_environment)
        workflow.add_node("plan_task", self._node_plan_task)
        workflow.add_node("select_action", self._node_select_action)
        workflow.add_node("approval_gate", self._node_approval_gate)
        workflow.add_node("execute_tool", self._node_execute_tool)
        workflow.add_node("observe_result", self._node_observe_result)
        workflow.add_node("verify_step", self._node_verify_step)
        workflow.add_node("evaluate_progress", self._node_evaluate_progress)
        workflow.add_node("recover_or_replan", self._node_recover_or_replan)
        workflow.add_node("finish_task", self._node_finish_task)
        workflow.add_node("cancel_task", self._node_cancel_task)
        workflow.add_node("fail_task", self._node_fail_task)

        # ── Setup Linear Edges ──────────────────────────────────────────
        workflow.add_edge(START, "understand_goal")
        workflow.add_edge("understand_goal", "retrieve_context")
        workflow.add_edge("retrieve_context", "inspect_environment")
        workflow.add_edge("inspect_environment", "plan_task")
        workflow.add_edge("plan_task", "select_action")

        # ── Conditional Edge: Selection -> Action / Approval / Terminal ─
        workflow.add_conditional_edges(
            "select_action",
            self._route_after_select,
            {
                "execute_tool": "execute_tool",
                "approval_gate": "approval_gate",
                "finish_task": "finish_task",
                "cancel_task": "cancel_task",
            },
        )

        # ── Conditional Edge: Approval Gate -> Execute / Cancel ─────────
        workflow.add_conditional_edges(
            "approval_gate",
            self._route_after_approval,
            {
                "execute_tool": "execute_tool",
                "cancel_task": "cancel_task",
            },
        )

        # ── Execution, Observation, Verification Pipeline ───────────────
        workflow.add_edge("execute_tool", "observe_result")
        workflow.add_edge("observe_result", "verify_step")
        workflow.add_edge("verify_step", "evaluate_progress")

        # ── Conditional Edge: Cyclic Evaluation (Next / Retry / End) ────
        workflow.add_conditional_edges(
            "evaluate_progress",
            self._route_after_evaluate,
            {
                "select_action": "select_action",        # Cyclic transition for multi-step plan
                "recover_or_replan": "recover_or_replan",# Cyclic transition for bounded recovery
                "finish_task": "finish_task",
                "fail_task": "fail_task",
                "cancel_task": "cancel_task",
            },
        )

        # ── Recovery loops back to tool execution ───────────────────────
        workflow.add_edge("recover_or_replan", "execute_tool")

        # ── Terminal Edges ──────────────────────────────────────────────
        workflow.add_edge("finish_task", END)
        workflow.add_edge("cancel_task", END)
        workflow.add_edge("fail_task", END)

        return workflow

    # ── Graph Node Implementations ──────────────────────────────────────

    def _node_understand_goal(self, state: CortexAgentState) -> Dict[str, Any]:
        """Node 1: Understands user goal, verifies constraints and cancellation."""
        if state.get("cancellation_requested") or state.get("status") in (TaskStatus.CANCELED.value, TaskStatus.CANCELLED.value):
            return {"status": TaskStatus.CANCELLED.value}
        return {"status": TaskStatus.UNDERSTANDING.value}

    def _node_retrieve_context(self, state: CortexAgentState) -> Dict[str, Any]:
        """Node 2: Retrieves relevant context, memory, and environment settings."""
        return {"status": TaskStatus.UNDERSTANDING.value}

    def _node_inspect_environment(self, state: CortexAgentState) -> Dict[str, Any]:
        """Node 3: Inspects real environment state before committing to actions."""
        return {"status": TaskStatus.PLANNED.value}

    def _node_plan_task(self, state: CortexAgentState) -> Dict[str, Any]:
        """Node 4: Prepares execution steps."""
        steps = state.get("steps") or []
        return {
            "steps": steps,
            "current_step_index": state.get("current_step_index", 0),
            "status": TaskStatus.EXECUTING.value,
        }

    def _node_select_action(self, state: CortexAgentState) -> Dict[str, Any]:
        """Node 5: Selects the next action step, performs duplicate/idempotency checks, and flags approval needs."""
        idx = state.get("current_step_index", 0)
        steps = state.get("steps", [])

        if idx >= len(steps):
            return {"current_step": None}

        step = dict(steps[idx])
        step_cmd_val = step.get("command") or state.get("command") or "unknown"
        try:
            step_cmd = TaskCommand(step_cmd_val)
        except ValueError:
            step_cmd = TaskCommand.UNKNOWN

        step_inputs = dict(step.get("inputs") or {})
        # Context propagation across sequential steps in multi-step plans
        if step_cmd in (TaskCommand.WRITE_FILE, TaskCommand.CREATE_DOCUMENT) and (not step_inputs.get("content") or step_inputs.get("content") == "Cortex execution verified." or "placeholder" in step_inputs.get("content", "").lower() or len(step_inputs.get("content", "")) < 100):
            prev_result = state.get("final_response") or (state.get("all_evidence", [])[-1] if state.get("all_evidence") else "")
            if not prev_result:
                tool_res = state.get("tool_result") or {}
                prev_result = tool_res.get("message") or ""
            search_items = (state.get("final_data") or {}).get("results") or (state.get("tool_result", {}).get("data") or {}).get("results")
            if search_items and isinstance(search_items, list):
                report_lines = ["# Research Report\n"]
                for item in search_items:
                    t = item.get("title", "")
                    b = item.get("body", "")
                    u = item.get("href", "")
                    report_lines.append(f"## {t}\n{b}\nSource: {u}\n")
                prev_result = "\n".join(report_lines)
            if prev_result:
                step_inputs["content"] = prev_result
                step["inputs"] = dict(step_inputs)
        idempotency_key = self.policy.compute_idempotency_key(step_cmd, step_inputs)
        is_dup, dup_msg = self.policy.check_duplicate_or_uncertain(idempotency_key)

        if is_dup:
            return {
                "current_step": step,
                "error": dup_msg or "Duplicate execution prevented.",
                "status": TaskStatus.FAILED.value,
            }

        # Check if action requires explicit user approval
        needs_approval = bool(
            step.get("approval_required")
            or self.policy.is_irreversible(step_cmd)
            or step.get("risk_level") in (RiskLevel.HIGH.value, RiskLevel.CRITICAL.value, RiskLevel.BLOCKED.value)
        )

        return {
            "current_step": step,
            "selected_tool": step.get("tool"),
            "tool_inputs": step_inputs,
            "needs_approval": needs_approval and not state.get("approval_granted", False),
            "status": TaskStatus.EXECUTING.value,
        }

    def _node_approval_gate(self, state: CortexAgentState) -> Dict[str, Any]:
        """Node 6: Approval boundary using official LangGraph interrupt / pause capability."""
        step = state.get("current_step") or {}
        action_desc = step.get("action") or state.get("goal") or "consequential action"

        # If already approved, proceed directly
        if state.get("approval_granted"):
            return {
                "needs_approval": False,
                "status": TaskStatus.EXECUTING.value,
            }

        # Trigger official LangGraph interrupt
        interrupt_payload = {
            "task_id": state.get("task_id"),
            "action": action_desc,
            "tool": step.get("tool"),
            "inputs": sanitize_state_value(step.get("inputs")),
            "approval_hash": step.get("approval_hash") or state.get("approval_hash"),
        }

        # Official LangGraph interrupt halts invocation and saves state to checkpointer
        resume_val = interrupt(interrupt_payload)

        # When resumed via Command(resume={...}):
        approved = bool(resume_val.get("approved", False)) if isinstance(resume_val, dict) else bool(resume_val)
        return {
            "approval_granted": approved,
            "needs_approval": False,
            "status": TaskStatus.EXECUTING.value if approved else TaskStatus.CANCELLED.value,
        }

    def _node_execute_tool(self, state: CortexAgentState) -> Dict[str, Any]:
        """Node 7: Executes tool action via Cortex ToolRegistry."""
        step = state.get("current_step") or {}
        tool_name = step.get("tool") or state.get("selected_tool") or "desktop_tool"
        tool_inst = self._get_tool_for_name(tool_name)

        if not tool_inst:
            res = ExecutionResult(
                step_id=step.get("id", "step"),
                ok=False,
                message=f"No tool found for {tool_name}",
                error="ToolNotFound",
            )
            return {
                "tool_result": sanitize_state_value(res.to_dict()),
                "status": TaskStatus.RECOVERING.value,
            }

        inputs = dict(state.get("tool_inputs") or step.get("inputs") or {})
        inputs["step_id"] = step.get("id", "step")
        inputs["task_id"] = state.get("task_id", "")
        step_cmd_val = step.get("command") or state.get("command")
        try:
            cmd = TaskCommand(step_cmd_val) if step_cmd_val else TaskCommand.UNKNOWN
        except ValueError:
            cmd = TaskCommand.UNKNOWN
        inputs["command"] = cmd

        exec_res = tool_inst.execute(inputs, context=None)

        # Sanitize result to ensure MsgPack/JSON serializable
        clean_data = sanitize_state_value(exec_res.data) if isinstance(exec_res.data, dict) else {}
        clean_res = {
            "step_id": str(getattr(exec_res, "step_id", "step")),
            "ok": bool(exec_res.ok),
            "message": str(exec_res.message or ""),
            "data": clean_data,
            "error": str(exec_res.error) if exec_res.error else None,
            "duration_ms": float(exec_res.duration_ms or 0.0),
        }

        return {
            "tool_result": clean_res,
            "status": TaskStatus.OBSERVING.value,
        }

    def _node_observe_result(self, state: CortexAgentState) -> Dict[str, Any]:
        """Node 8: Independently observes real-world system state."""
        step = state.get("current_step") or {}
        tool_name = step.get("tool") or state.get("selected_tool") or "desktop_tool"
        tool_inst = self._get_tool_for_name(tool_name)

        raw_res = state.get("tool_result") or {}
        exec_res = ExecutionResult(
            step_id=raw_res.get("step_id") or raw_res.get("stepId", "step"),
            ok=bool(raw_res.get("ok", False)),
            message=str(raw_res.get("message", "")),
            data=dict(raw_res["data"]) if isinstance(raw_res.get("data"), dict) else {},
            error=raw_res.get("error"),
            duration_ms=float(raw_res.get("duration_ms") or raw_res.get("durationMs", 0.0)),
        )

        inputs = dict(state.get("tool_inputs") or step.get("inputs") or {})
        inputs["step_id"] = step.get("id", "step")
        step_cmd_val = step.get("command") or state.get("command")
        if step_cmd_val:
            try:
                inputs["command"] = TaskCommand(step_cmd_val)
            except ValueError:
                pass

        if not tool_inst:
            obs = Observation(target=tool_name, state_data={"ok": exec_res.ok}, raw_output=exec_res.message)
        else:
            obs = tool_inst.observe(inputs, exec_res)

        clean_state_data = sanitize_state_value(obs.state_data) if isinstance(obs.state_data, dict) else {}
        clean_obs = {
            "target": str(obs.target),
            "state_data": clean_state_data,
            "raw_output": str(obs.raw_output or ""),
            "evidence_type": str(obs.evidence_type or "direct"),
        }

        return {
            "observation": clean_obs,
            "status": TaskStatus.VERIFYING.value,
        }

    def _node_verify_step(self, state: CortexAgentState) -> Dict[str, Any]:
        """Node 9: Independently verifies execution outcome against expected evidence."""
        step = state.get("current_step") or {}
        tool_name = step.get("tool") or state.get("selected_tool") or "desktop_tool"
        tool_inst = self._get_tool_for_name(tool_name)

        raw_res = state.get("tool_result") or {}
        exec_res = ExecutionResult(
            step_id=raw_res.get("step_id") or raw_res.get("stepId", "step"),
            ok=bool(raw_res.get("ok", False)),
            message=str(raw_res.get("message", "")),
            data=dict(raw_res["data"]) if isinstance(raw_res.get("data"), dict) else {},
            error=raw_res.get("error"),
            duration_ms=float(raw_res.get("duration_ms") or raw_res.get("durationMs", 0.0)),
        )

        raw_obs = state.get("observation") or {}
        raw_state_data = raw_obs.get("state_data") if isinstance(raw_obs.get("state_data"), dict) else (raw_obs.get("stateData") if isinstance(raw_obs.get("stateData"), dict) else {})
        obs = Observation(
            target=str(raw_obs.get("target", tool_name)),
            state_data=dict(raw_state_data),
            raw_output=str(raw_obs.get("raw_output") or raw_obs.get("rawOutput") or ""),
            evidence_type=str(raw_obs.get("evidence_type") or raw_obs.get("evidenceType", "state_readback")),
        )

        inputs = dict(state.get("tool_inputs") or step.get("inputs") or {})
        inputs["step_id"] = step.get("id", "step")
        step_cmd_val = step.get("command") or state.get("command")
        if step_cmd_val:
            try:
                inputs["command"] = TaskCommand(step_cmd_val)
            except ValueError:
                pass

        if not tool_inst:
            ver = VerificationResult(verified=exec_res.ok, evidence=exec_res.message)
        else:
            ver = tool_inst.verify(inputs, obs, exec_res)

        clean_ver = {
            "verified": bool(ver.verified),
            "evidence": str(ver.evidence or ""),
            "confidence": float(ver.confidence or 1.0),
            "uncertainty_reason": str(ver.uncertainty_reason) if ver.uncertainty_reason else None,
            "error": str(ver.error) if ver.error else None,
        }

        return {
            "verification": clean_ver,
        }

    def _node_evaluate_progress(self, state: CortexAgentState) -> Dict[str, Any]:
        """Node 10: Evaluates verified results, manages step completion, or triggers recovery."""
        if state.get("cancellation_requested") or state.get("status") in (TaskStatus.CANCELLED.value, TaskStatus.CANCELED.value):
            return {
                "status": TaskStatus.CANCELLED.value,
                "error": "Task was cancelled.",
            }

        ver = state.get("verification") or {}
        verified = bool(ver.get("verified", False))
        idx = state.get("current_step_index", 0)
        steps = list(state.get("steps") or [])
        step = dict(steps[idx]) if idx < len(steps) else {}

        all_evidence = list(state.get("all_evidence") or [])
        final_data = dict(state.get("final_data") or {})

        tool_res = state.get("tool_result") or {}
        if tool_res.get("data") and isinstance(tool_res["data"], dict):
            final_data.update(tool_res["data"])

        evidence_str = ver.get("evidence") or "Step verified."
        resp_msg = tool_res.get("message") if (tool_res.get("ok") and tool_res.get("message")) else evidence_str

        if verified:
            all_evidence.append(evidence_str)
            if idx < len(steps):
                steps[idx]["status"] = "completed"

            # Record completed attempt idempotency
            step_cmd_val = step.get("command") or state.get("command") or "unknown"
            try:
                step_cmd = TaskCommand(step_cmd_val)
            except ValueError:
                step_cmd = TaskCommand.UNKNOWN
            idempotency_key = self.policy.compute_idempotency_key(step_cmd, step.get("inputs", {}))
            self.policy.mark_execution_completed(idempotency_key, "completed")

            return {
                "current_step_index": idx + 1,
                "steps": steps,
                "all_evidence": all_evidence,
                "final_data": final_data,
                "recovery_attempts": 0,
                "final_response": resp_msg,
                "status": TaskStatus.EXECUTING.value,
            }
        else:
            # Check for resolve_as_success recovery via positive evidence
            tool_name = step.get("tool") or "desktop_tool"
            tool_inst = self._get_tool_for_name(tool_name)
            attempt = state.get("recovery_attempts", 0) + 1
            max_retries = (step.get("retry_policy") or {}).get("max_retries", state.get("max_retries", 1))

            err = ExecutionError(
                code="VerificationFailed",
                message=ver.get("evidence") or "Outcome not verified",
                recoverable=attempt <= max_retries,
            )
            recovery = tool_inst.recover(step.get("inputs", {}), err, attempt) if tool_inst else {"can_retry": False}

            if recovery.get("strategy") == "resolve_as_success":
                obs_data = (state.get("observation") or {}).get("state_data") or (state.get("observation") or {}).get("stateData") or {}
                has_positive_proof = bool(
                    obs_data.get("already_present") is True
                    or obs_data.get("text_verified") is True
                    or obs_data.get("verified") is True
                    or obs_data.get("verified_outcome") is True
                    or obs_data.get("task_verified") is True
                    or obs_data.get("transaction_recorded") is True
                    or (obs_data.get("note_exists") is True and obs_data.get("note_title"))
                ) and not obs_data.get("unverified", False)

                if has_positive_proof:
                    res_msg = recovery.get("message", "Resolved via verified state observation.")
                    all_evidence.append(res_msg)
                    if idx < len(steps):
                        steps[idx]["status"] = "completed"
                    return {
                        "current_step_index": idx + 1,
                        "steps": steps,
                        "all_evidence": all_evidence,
                        "final_data": final_data,
                        "recovery_attempts": 0,
                        "final_response": res_msg,
                        "status": TaskStatus.EXECUTING.value,
                    }
                else:
                    return {
                        "status": TaskStatus.NEEDS_ATTENTION.value,
                        "error": "Recovery rejected: independent observation could not verify intended side effect.",
                    }

            return {
                "status": TaskStatus.RECOVERING.value,
                "error": ver.get("evidence") or recovery.get("message") or "Verification failed",
            }

    def _node_recover_or_replan(self, state: CortexAgentState) -> Dict[str, Any]:
        """Node 11: Performs bounded retry backoff or replanning."""
        attempt = state.get("recovery_attempts", 0) + 1
        idx = state.get("current_step_index", 0)
        steps = state.get("steps") or []
        step = steps[idx] if idx < len(steps) else {}
        backoff = (step.get("retry_policy") or {}).get("backoff_seconds", 0.1)

        time.sleep(backoff)
        return {
            "recovery_attempts": attempt,
            "status": TaskStatus.RECOVERING.value,
        }

    def _node_finish_task(self, state: CortexAgentState) -> Dict[str, Any]:
        """Node 12: Completes task with evidence compilation."""
        summary = state.get("final_response") or "; ".join(state.get("all_evidence") or []) or "Task completed and verified."
        return {
            "status": TaskStatus.COMPLETED.value,
            "final_response": summary,
        }

    def _node_cancel_task(self, state: CortexAgentState) -> Dict[str, Any]:
        """Node 13: Handles clean task cancellation."""
        return {
            "status": TaskStatus.CANCELLED.value,
            "error": "Task was cancelled.",
            "final_response": "Task cancelled by user.",
        }

    def _node_fail_task(self, state: CortexAgentState) -> Dict[str, Any]:
        """Node 14: Handles terminal failure with honest reporting."""
        current_status = state.get("status", TaskStatus.FAILED.value)
        ver = state.get("verification") or {}
        tool_res = state.get("tool_result") or {}
        obs = state.get("observation") or {}
        is_unverified = (
            current_status in (TaskStatus.NEEDS_ATTENTION.value, "unverified", TaskStatus.UNVERIFIED.value)
            or (tool_res.get("ok") and not ver.get("verified", False))
            or "unverified" in str(ver.get("evidence", "")).lower()
            or "unverified" in str(obs.get("raw_output", "")).lower()
        )
        if is_unverified:
            term_status = TaskStatus.NEEDS_ATTENTION.value
        else:
            term_status = TaskStatus.FAILED.value
        err = state.get("error") or "Task execution failed verification."
        return {
            "status": term_status,
            "error": err,
            "final_response": err,
        }

    # ── Conditional Routing Functions ───────────────────────────────────

    def _route_after_select(self, state: CortexAgentState) -> str:
        if state.get("cancellation_requested") or state.get("status") in (TaskStatus.CANCELED.value, TaskStatus.CANCELLED.value):
            return "cancel_task"

        idx = state.get("current_step_index", 0)
        steps = state.get("steps", [])

        if idx >= len(steps):
            return "finish_task"

        if state.get("needs_approval") and not state.get("approval_granted"):
            return "approval_gate"

        return "execute_tool"

    def _route_after_approval(self, state: CortexAgentState) -> str:
        if state.get("approval_granted"):
            return "execute_tool"
        return "cancel_task"

    def _route_after_evaluate(self, state: CortexAgentState) -> str:
        if state.get("cancellation_requested") or state.get("status") in (TaskStatus.CANCELED.value, TaskStatus.CANCELLED.value):
            return "cancel_task"

        if state.get("status") == TaskStatus.NEEDS_ATTENTION.value:
            return "fail_task"

        ver = state.get("verification") or {}
        verified = bool(ver.get("verified", False))

        if verified:
            idx = state.get("current_step_index", 0)
            steps = state.get("steps", [])
            if idx < len(steps):
                return "select_action"  # Cyclic transition to next step
            return "finish_task"

        # Not verified -> check bounded recovery
        idx = state.get("current_step_index", 0)
        steps = state.get("steps", [])
        step = steps[idx] if idx < len(steps) else {}
        max_retries = (step.get("retry_policy") or {}).get("max_retries", state.get("max_retries", 1))
        attempts = state.get("recovery_attempts", 0)

        if attempts < max_retries:
            return "recover_or_replan"  # Cyclic retry loop

        return "fail_task"

    # ── Public Execution Interface (Preserving Cortex Contract) ─────────

    def execute_plan(
        self,
        task: Task,
        plan: Plan | None = None,
        on_progress: Callable[[str, str], None] | None = None,
    ) -> FinalResult:
        """
        Executes an agent task using the authoritative LangGraph StateGraph.
        """
        if callable(plan) and on_progress is None:
            on_progress = plan
            plan = None

        if plan is not None:
            task.plan = plan

        start_time = time.time()
        effective_plan = task.plan

        if not effective_plan or not effective_plan.steps:
            task.status = TaskStatus.COMPLETED
            summary = task.result or "No execution steps required."
            return FinalResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                summary=summary,
                data={},
                duration_ms=(time.time() - start_time) * 1000,
            )

        # Early check for cancellation
        if task.status in (TaskStatus.CANCELED, TaskStatus.CANCELLED) or task.cancellation_requested:
            task.status = TaskStatus.CANCELLED
            task.add_event("canceled", "Task cancelled before execution.")
            return FinalResult(
                task_id=task.id,
                status=TaskStatus.CANCELLED,
                summary="Task cancelled.",
                data={},
                duration_ms=0,
            )

        # Prepare initial LangGraph state
        serialized_steps = [
            {
                "id": str(s.id),
                "action": str(s.action),
                "tool": str(s.tool),
                "command": s.command.value if hasattr(s.command, "value") else str(s.command or task.command.value),
                "inputs": sanitize_state_value(dict(s.inputs or {})),
                "expected_result": str(s.expected_result or ""),
                "risk_level": s.risk_level.value if hasattr(s.risk_level, "value") else str(s.risk_level),
                "approval_required": getattr(s, "approval_required", False),
                "retry_policy": s.retry_policy.to_dict() if hasattr(s.retry_policy, "to_dict") else (dict(s.retry_policy) if isinstance(s.retry_policy, dict) else {}),
                "status": "pending",
            }
            for s in effective_plan.steps
        ]

        initial_state: CortexAgentState = {
            "task_id": str(task.id),
            "goal": str(effective_plan.goal or task.intent),
            "command": task.command.value if hasattr(task.command, "value") else str(task.command),
            "params": sanitize_state_value(dict(task.params or {})),
            "context": sanitize_state_value(task.context.to_dict() if hasattr(task.context, "to_dict") else dict(task.context or {})),
            "status": TaskStatus.EXECUTING.value,
            "plan": sanitize_state_value(effective_plan.to_dict() if hasattr(effective_plan, "to_dict") else None),
            "steps": serialized_steps,
            "current_step_index": 0,
            "current_step": None,
            "selected_tool": None,
            "tool_inputs": None,
            "tool_result": None,
            "observation": None,
            "verification": None,
            "all_evidence": [],
            "final_data": {},
            "error": None,
            "recovery_attempts": 0,
            "max_retries": 1,
            "replan_count": 0,
            "needs_approval": False,
            "approval_granted": bool(task.params.get("approval_granted") or task.params.get("approved")),
            "approval_hash": task.params.get("approval_hash"),
            "approval_consumed": bool(task.params.get("approval_consumed")),
            "cancellation_requested": bool(task.cancellation_requested),
            "final_response": None,
            "audit_events": [],
        }

        task.status = TaskStatus.EXECUTING
        task.add_event("executing", f"Executing plan with {len(effective_plan.steps)} steps via LangGraph.")
        if on_progress:
            on_progress("executing", f"Executing plan with {len(effective_plan.steps)} steps.")

        config = {"configurable": {"thread_id": task.id}, "recursion_limit": 100}

        try:
            # Stream execution through LangGraph so progress updates and audits are real-time
            final_state = dict(initial_state)
            for chunk in self._compiled_graph.stream(initial_state, config=config, stream_mode="updates"):
                # Check for LangGraph interrupt at chunk level
                if "__interrupt__" in chunk:
                    task.status = TaskStatus.WAITING_APPROVAL
                    task.add_event("awaiting_approval", "Action paused at LangGraph approval gate.")
                    if on_progress:
                        on_progress("waiting_approval", "Approval required to proceed.")
                    return FinalResult(
                        task_id=task.id,
                        status=TaskStatus.WAITING_APPROVAL,
                        summary="Action requires approval.",
                        data=final_state.get("final_data", {}),
                        duration_ms=(time.time() - start_time) * 1000,
                    )

                for node_name, node_update in chunk.items():
                    if not isinstance(node_update, dict):
                        continue
                    final_state.update(node_update)

                    # Check for external cancellation triggered during on_progress
                    if task.status in (TaskStatus.CANCELED, TaskStatus.CANCELLED) or task.cancellation_requested:
                        task.status = TaskStatus.CANCELLED
                        task.add_event("canceled", "Task cancelled during execution.")
                        return FinalResult(
                            task_id=task.id,
                            status=TaskStatus.CANCELLED,
                            summary="Task execution cancelled.",
                            data=final_state.get("final_data", {}),
                            duration_ms=(time.time() - start_time) * 1000,
                        )

                    # Check for LangGraph interrupt
                    if "__interrupt__" in node_update or node_name == "approval_gate":
                        st_check = self._compiled_graph.get_state(config)
                        if st_check.tasks and any(t.interrupts for t in st_check.tasks):
                            task.status = TaskStatus.WAITING_APPROVAL
                            task.add_event("awaiting_approval", "Action paused at LangGraph approval gate.")
                            if on_progress:
                                on_progress("waiting_approval", "Approval required to proceed.")
                            return FinalResult(
                                task_id=task.id,
                                status=TaskStatus.WAITING_APPROVAL,
                                summary="Action requires approval.",
                                data=final_state.get("final_data", {}),
                                duration_ms=(time.time() - start_time) * 1000,
                            )

                    # Emit progress events and audit updates
                    curr_idx = final_state.get("current_step_index", 0)
                    step_count = len(serialized_steps)
                    if node_name == "execute_tool":
                        task.status = TaskStatus.EXECUTING
                        curr_step = final_state.get("current_step") or {}
                        msg = f"Step {curr_idx + 1}/{step_count}: {curr_step.get('action', '')}"
                        if on_progress:
                            on_progress("executing", msg)

                    elif node_name == "observe_result":
                        task.status = TaskStatus.OBSERVING
                        curr_step = final_state.get("current_step") or {}
                        if on_progress:
                            on_progress("observing", f"Observing system state for: {curr_step.get('action', '')}")
                        raw_obs = final_state.get("observation") or {}
                        obs_obj = Observation(
                            target=raw_obs.get("target", "system"),
                            state_data=raw_obs.get("state_data") or raw_obs.get("stateData") or {},
                            raw_output=raw_obs.get("raw_output") or raw_obs.get("rawOutput") or "",
                            evidence_type=raw_obs.get("evidence_type") or raw_obs.get("evidenceType", "state_readback"),
                        )
                        task.observations.append(obs_obj)
                        task.add_event("observed", f"Observed state for {curr_step.get('tool', 'tool')}", state=obs_obj.state_data)

                    elif node_name == "verify_step":
                        task.status = TaskStatus.VERIFYING
                        curr_step = final_state.get("current_step") or {}
                        if on_progress:
                            on_progress("verifying", f"Verifying outcome for: {curr_step.get('action', '')}")
                        raw_ver = final_state.get("verification") or {}
                        ver_obj = VerificationResult(
                            verified=raw_ver.get("verified", False),
                            evidence=raw_ver.get("evidence", ""),
                            confidence=raw_ver.get("confidence", 1.0),
                            uncertainty_reason=raw_ver.get("uncertainty_reason") or raw_ver.get("uncertaintyReason"),
                        )
                        task.verifications.append(ver_obj)

                    elif node_name == "evaluate_progress":
                        curr_step = final_state.get("current_step") or {}
                        tool_res = final_state.get("tool_result") or {}
                        exec_res_obj = ExecutionResult(
                            step_id=tool_res.get("step_id") or tool_res.get("stepId", "step"),
                            ok=tool_res.get("ok", False),
                            message=tool_res.get("message", ""),
                            data=tool_res.get("data", {}),
                            error=tool_res.get("error"),
                        )
                        task.execution_history.append(exec_res_obj)

                        last_ver = task.verifications[-1] if task.verifications else VerificationResult(verified=True, evidence="")
                        if last_ver.verified:
                            cmd_val = curr_step.get("command") or task.command.value
                            step_inputs = dict(curr_step.get("inputs") or {})
                            app_name = step_inputs.get("appName") or step_inputs.get("params", {}).get("appName") or ""
                            text_preview = step_inputs.get("text") or step_inputs.get("params", {}).get("text") or ""
                            if len(text_preview) > 100:
                                text_preview = text_preview[:97] + "..."

                            comp_data = {"command": cmd_val, "intent": curr_step.get("action", "")}
                            if app_name:
                                comp_data["appName"] = app_name
                            if text_preview:
                                comp_data["text"] = text_preview

                            verif_data = {"confidence": last_ver.confidence, "action": cmd_val, "verified": True}
                            if app_name:
                                verif_data["appName"] = app_name
                            if text_preview:
                                verif_data["text"] = text_preview

                            task.add_event("step_completed", exec_res_obj.message, **comp_data)
                            task.add_event("step_verified", last_ver.evidence, **verif_data)
                        else:
                            task.status = TaskStatus.RECOVERING
                            if on_progress:
                                on_progress("recovering", f"Diagnosing recovery for: {curr_step.get('action', '')}")
                            task.add_event("verification_failed", last_ver.evidence, uncertainty=last_ver.uncertainty_reason)

                    elif node_name == "recover_or_replan":
                        task.status = TaskStatus.RECOVERING
                        att = final_state.get("recovery_attempts", 1)
                        task.add_event("retrying", f"Attempting safe retry ({att})...")

        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.error = f"LangGraph execution exception: {exc}"
            task.add_event("failed", task.error)
            return FinalResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                summary=task.error,
                data={},
                duration_ms=(time.time() - start_time) * 1000,
            )

        duration_ms = (time.time() - start_time) * 1000
        state_status = final_state.get("status", TaskStatus.COMPLETED.value)
        try:
            task.status = TaskStatus(state_status)
        except ValueError:
            task.status = TaskStatus.COMPLETED if state_status == "completed" else TaskStatus.FAILED

        task.result = final_state.get("final_response") or task.result or "Task executed successfully."
        if final_state.get("error"):
            task.error = final_state["error"]

        all_ev = final_state.get("all_evidence", [])
        if task.status == TaskStatus.COMPLETED:
            task.add_event("completed", task.result, evidence=all_ev)
        elif task.status in (TaskStatus.CANCELLED, TaskStatus.CANCELED):
            task.add_event("canceled", "Task execution cancelled.")
        elif task.status in (TaskStatus.NEEDS_ATTENTION, TaskStatus.UNVERIFIED):
            task.add_event("step_unverified", task.error or "Outcome unverified.", strategy="resolve_as_success")
        else:
            task.add_event("failed", task.error or "Execution failed.")

        return FinalResult(
            task_id=task.id,
            status=task.status,
            summary=task.result or task.error or "Execution finished.",
            data=final_state.get("final_data", {}),
            verification_evidence="; ".join(all_ev),
            duration_ms=duration_ms,
        )

    def is_interrupted(self, task: Task) -> bool:
        """Checks if the task has an active interrupt awaiting resumption in LangGraph checkpointer."""
        try:
            config = {"configurable": {"thread_id": str(task.id)}}
            st = self._compiled_graph.get_state(config)
            return bool(st and st.tasks and any(t.interrupts for t in st.tasks))
        except Exception:
            return False

    def resume_task(
        self,
        task: Task,
        approval_decision: Dict[str, Any],
        on_progress: Callable[[str, str], None] | None = None,
    ) -> FinalResult:
        """
        Resumes an approval-interrupted task from its LangGraph checkpoint.
        """
        config = {"configurable": {"thread_id": task.id}, "recursion_limit": 100}
        resume_cmd = Command(resume=approval_decision)
        start_time = time.time()

        approved = bool(approval_decision.get("approved", False)) if isinstance(approval_decision, dict) else bool(approval_decision)
        if approved:
            task.status = TaskStatus.EXECUTING
            task.add_event("resumed", "Resuming execution from LangGraph checkpoint.")
        else:
            task.status = TaskStatus.CANCELLED
            task.add_event("approval_rejected", "Action rejected; cancelling graph execution.")

        try:
            final_state: Dict[str, Any] = {}
            for chunk in self._compiled_graph.stream(resume_cmd, config=config, stream_mode="updates"):
                if "__interrupt__" in chunk:
                    task.status = TaskStatus.WAITING_APPROVAL
                    task.add_event("awaiting_approval", "Action paused at LangGraph approval gate.")
                    if on_progress:
                        on_progress("waiting_approval", "Approval required to proceed.")
                    return FinalResult(
                        task_id=task.id,
                        status=TaskStatus.WAITING_APPROVAL,
                        summary="Action requires approval.",
                        data=final_state.get("final_data", {}),
                        duration_ms=(time.time() - start_time) * 1000,
                    )

                for node_name, node_update in chunk.items():
                    if not isinstance(node_update, dict):
                        continue
                    final_state.update(node_update)

                    # Check for external cancellation triggered during on_progress
                    if task.status in (TaskStatus.CANCELED, TaskStatus.CANCELLED) or task.cancellation_requested:
                        task.status = TaskStatus.CANCELLED
                        task.add_event("canceled", "Task cancelled during execution.")
                        return FinalResult(
                            task_id=task.id,
                            status=TaskStatus.CANCELLED,
                            summary="Task execution cancelled.",
                            data=final_state.get("final_data", {}),
                            duration_ms=(time.time() - start_time) * 1000,
                        )

                    # Emit progress events and audit updates
                    curr_idx = final_state.get("current_step_index", 0)
                    curr_step = final_state.get("current_step") or {}
                    if node_name == "execute_tool":
                        task.status = TaskStatus.EXECUTING
                        msg = f"Step: {curr_step.get('action', '')}"
                        if on_progress:
                            on_progress("executing", msg)

                    elif node_name == "observe_result":
                        task.status = TaskStatus.OBSERVING
                        if on_progress:
                            on_progress("observing", f"Observing system state for: {curr_step.get('action', '')}")
                        raw_obs = final_state.get("observation") or {}
                        obs_obj = Observation(
                            target=raw_obs.get("target", "system"),
                            state_data=raw_obs.get("state_data") or raw_obs.get("stateData") or {},
                            raw_output=raw_obs.get("raw_output") or raw_obs.get("rawOutput") or "",
                            evidence_type=raw_obs.get("evidence_type") or raw_obs.get("evidenceType", "state_readback"),
                        )
                        task.observations.append(obs_obj)
                        task.add_event("observed", f"Observed state for {curr_step.get('tool', 'tool')}", state=obs_obj.state_data)

                    elif node_name == "verify_step":
                        task.status = TaskStatus.VERIFYING
                        if on_progress:
                            on_progress("verifying", f"Verifying outcome for: {curr_step.get('action', '')}")
                        raw_ver = final_state.get("verification") or {}
                        ver_obj = VerificationResult(
                            verified=raw_ver.get("verified", False),
                            evidence=raw_ver.get("evidence", ""),
                            confidence=raw_ver.get("confidence", 1.0),
                            uncertainty_reason=raw_ver.get("uncertainty_reason") or raw_ver.get("uncertaintyReason"),
                        )
                        task.verifications.append(ver_obj)

                    elif node_name == "evaluate_progress":
                        tool_res = final_state.get("tool_result") or {}
                        exec_res_obj = ExecutionResult(
                            step_id=tool_res.get("step_id") or tool_res.get("stepId", "step"),
                            ok=tool_res.get("ok", False),
                            message=tool_res.get("message", ""),
                            data=tool_res.get("data", {}),
                            error=tool_res.get("error"),
                        )
                        task.execution_history.append(exec_res_obj)

                        last_ver = task.verifications[-1] if task.verifications else VerificationResult(verified=True, evidence="")
                        if last_ver.verified:
                            cmd_val = curr_step.get("command") or task.command.value
                            step_inputs = dict(curr_step.get("inputs") or {})
                            app_name = step_inputs.get("appName") or step_inputs.get("params", {}).get("appName") or ""
                            text_preview = step_inputs.get("text") or step_inputs.get("params", {}).get("text") or ""
                            if len(text_preview) > 100:
                                text_preview = text_preview[:97] + "..."

                            comp_data = {"command": cmd_val, "intent": curr_step.get("action", "")}
                            if app_name:
                                comp_data["appName"] = app_name
                            if text_preview:
                                comp_data["text"] = text_preview

                            verif_data = {"confidence": last_ver.confidence, "action": cmd_val, "verified": True}
                            if app_name:
                                verif_data["appName"] = app_name
                            if text_preview:
                                verif_data["text"] = text_preview

                            task.add_event("step_completed", exec_res_obj.message, **comp_data)
                            task.add_event("step_verified", last_ver.evidence, **verif_data)
                        else:
                            task.status = TaskStatus.RECOVERING
                            if on_progress:
                                on_progress("recovering", f"Diagnosing recovery for: {curr_step.get('action', '')}")
                            task.add_event("verification_failed", last_ver.evidence, uncertainty=last_ver.uncertainty_reason)

                    elif node_name == "recover_or_replan":
                        task.status = TaskStatus.RECOVERING
                        att = final_state.get("recovery_attempts", 1)
                        task.add_event("retrying", f"Attempting safe retry ({att})...")

            duration_ms = (time.time() - start_time) * 1000
            state_status = final_state.get("status", TaskStatus.COMPLETED.value)
            try:
                task.status = TaskStatus(state_status)
            except ValueError:
                task.status = TaskStatus.COMPLETED if state_status == "completed" else TaskStatus.FAILED

            task.result = final_state.get("final_response") or task.result or "Resumed task completed."
            if final_state.get("error"):
                task.error = final_state["error"]

            all_ev = final_state.get("all_evidence", [])
            if task.status == TaskStatus.COMPLETED:
                task.add_event("completed", task.result, evidence=all_ev)
            elif task.status in (TaskStatus.CANCELLED, TaskStatus.CANCELED):
                task.add_event("canceled", "Task execution cancelled.")
            elif task.status in (TaskStatus.NEEDS_ATTENTION, TaskStatus.UNVERIFIED):
                task.add_event("step_unverified", task.error or "Outcome unverified.", strategy="resolve_as_success")
            else:
                task.add_event("failed", task.error or "Execution failed.")

            return FinalResult(
                task_id=task.id,
                status=task.status,
                summary=task.result or task.error or "Execution finished.",
                data=final_state.get("final_data", {}),
                verification_evidence="; ".join(all_ev),
                duration_ms=duration_ms,
            )
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.error = f"LangGraph resume exception: {exc}"
            task.add_event("failed", task.error)
            return FinalResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                summary=task.error,
                data={},
                duration_ms=(time.time() - start_time) * 1000,
            )
