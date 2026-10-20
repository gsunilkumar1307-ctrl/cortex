from __future__ import annotations

import time
from typing import Any, Callable
from cortex_sdk import (
    Task,
    TaskStatus,
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


class ExecutionEngine:
    """Core Agent Execution Loop:
    EXECUTE ONE STEP -> OBSERVE -> VERIFY -> RECOVER / RETRY / REPLAN.
    Enforces independent observation, evidence verification, and duplicate action protection.
    """

    def __init__(self, registry: ToolRegistry, policy_engine: PolicyEngine) -> None:
        self.registry = registry
        self.policy = policy_engine

    def execute_plan(
        self,
        task: Task,
        on_progress: Callable[[str, str], None] | None = None,
    ) -> FinalResult:
        start_time = time.time()
        plan = task.plan
        if not plan or not plan.steps:
            task.status = TaskStatus.COMPLETED
            return FinalResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                summary=task.result or "No execution steps required.",
                data={},
                duration_ms=(time.time() - start_time) * 1000,
            )

        task.status = TaskStatus.EXECUTING
        task.add_event("executing", f"Executing plan with {len(plan.steps)} steps.")

        all_evidence: list[str] = []
        final_data: dict[str, Any] = {}

        for idx, step in enumerate(plan.steps):
            if task.status in (TaskStatus.CANCELED, TaskStatus.CANCELLED):
                break

            step.status = "running"
            if on_progress:
                on_progress("executing", f"Step {idx + 1}/{len(plan.steps)}: {step.action}")

            # 1. Duplicate & Idempotency check for irreversible steps
            idempotency_key = self.policy.compute_idempotency_key(task.command, step.inputs)
            is_dup, dup_msg = self.policy.check_duplicate_or_uncertain(idempotency_key)
            if is_dup:
                task.status = TaskStatus.RECOVERING
                task.add_event("duplicate_prevented", dup_msg or "Duplicate execution prevented.")
                # Observe external state instead of repeating
                obs = self._observe_step(step, ExecutionResult(step_id=step.id, ok=True, message=dup_msg or ""))
                task.observations.append(obs)
                ver = self._verify_step(step, obs, ExecutionResult(step_id=step.id, ok=True, message=dup_msg or ""))
                task.verifications.append(ver)
                if ver.verified:
                    step.status = "completed"
                    all_evidence.append(ver.evidence)
                    continue
                else:
                    task.status = TaskStatus.FAILED
                    task.error = dup_msg
                    break

            self.policy.record_execution_attempt(idempotency_key, task.command, {"step_id": step.id})

            # 2. Execute Step with Bounded Retry / Recovery Loop
            max_retries = step.retry_policy.get("max_retries", 1)
            attempt = 0
            step_success = False

            while attempt <= max_retries and not step_success:
                attempt += 1
                exec_res = self._execute_step(task, step)
                task.execution_history.append(exec_res)

                # 3. Observe real-world external state
                task.status = TaskStatus.OBSERVING
                if on_progress:
                    on_progress("observing", f"Observing system state for: {step.action}")
                observation = self._observe_step(step, exec_res)
                task.observations.append(observation)
                task.add_event("observed", f"Observed state for {step.tool}", state=observation.state_data)

                # 4. Independent Verification
                task.status = TaskStatus.VERIFYING
                if on_progress:
                    on_progress("verifying", f"Verifying outcome for: {step.action}")
                verification = self._verify_step(step, observation, exec_res)
                task.verifications.append(verification)

                if verification.verified:
                    step_success = True
                    step.status = "completed"
                    self.policy.mark_execution_completed(idempotency_key, "completed")
                    task.add_event("step_verified", verification.evidence, confidence=verification.confidence)
                    all_evidence.append(verification.evidence)
                    if exec_res.ok and exec_res.message:
                        task.result = exec_res.message
                    else:
                        task.result = verification.evidence or "Action verified successfully."
                    if exec_res.data:
                        final_data.update(exec_res.data)
                else:
                    # 5. Recovery & Diagnosis
                    task.status = TaskStatus.RECOVERING
                    task.add_event("verification_failed", verification.evidence, uncertainty=verification.uncertainty_reason)

                    tool_inst = self._get_tool_for_step(step)
                    err = ExecutionError(
                        code="VerificationFailed",
                        message=verification.evidence or "Outcome not verified",
                        recoverable=not self.policy.is_irreversible(task.command) and attempt <= max_retries,
                    )
                    recovery = tool_inst.recover(step.inputs, err, attempt) if tool_inst else {"can_retry": False}

                    if recovery.get("strategy") == "resolve_as_success":
                        step_success = True
                        step.status = "completed"
                        self.policy.mark_execution_completed(idempotency_key, "completed")
                        res_msg = recovery.get("message", "Resolved via state observation.")
                        task.result = res_msg
                        all_evidence.append(res_msg)
                        break
                    elif recovery.get("can_retry") and attempt <= max_retries:
                        task.add_event("retrying", f"Attempting safe retry ({attempt}/{max_retries})...")
                        time.sleep(step.retry_policy.get("backoff_seconds", 0.5))
                    else:
                        task.status = TaskStatus.FAILED
                        task.error = recovery.get("message") or f"Step '{step.action}' failed verification: {verification.evidence}"
                        task.add_event("recovery_failed", task.error)
                        self.policy.mark_execution_completed(idempotency_key, "failed")
                        break

            if not step_success:
                task.status = TaskStatus.FAILED
                break

        duration_ms = (time.time() - start_time) * 1000
        if task.status != TaskStatus.FAILED and task.status not in (TaskStatus.CANCELED, TaskStatus.CANCELLED):
            task.status = TaskStatus.COMPLETED
            summary_msg = task.result or "Task executed and verified successfully."
            task.add_event("completed", summary_msg, evidence=all_evidence)
            return FinalResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                summary=summary_msg,
                data=final_data,
                verification_evidence="; ".join(all_evidence),
                duration_ms=duration_ms,
            )
        else:
            return FinalResult(
                task_id=task.id,
                status=task.status,
                summary=task.error or "Task execution failed.",
                data=final_data,
                verification_evidence="; ".join(all_evidence),
                duration_ms=duration_ms,
            )

    def _get_tool_for_step(self, step: PlanStep) -> BaseTool | None:
        inst = self.registry.get_instance(step.tool)
        if inst:
            return inst
        tool_name = step.tool.lower()
        if "mail" in tool_name:
            return self.registry.get_instance("mail_tool")
        if "file" in tool_name:
            return self.registry.get_instance("file_tool")
        if "browser" in tool_name or "url" in tool_name:
            return self.registry.get_instance("browser_tool")
        if "search" in tool_name:
            return self.registry.get_instance("web_search_tool")
        return self.registry.get_instance("desktop_tool")

    def _execute_step(self, task: Task, step: PlanStep) -> ExecutionResult:
        tool = self._get_tool_for_step(step)
        if not tool:
            return ExecutionResult(step_id=step.id, ok=False, message=f"No tool found for {step.tool}", error="ToolNotFound")

        inputs = dict(step.inputs)
        inputs["step_id"] = step.id
        inputs["command"] = task.command
        return tool.execute(inputs, context=task.context)

    def _observe_step(self, step: PlanStep, exec_res: ExecutionResult) -> Observation:
        tool = self._get_tool_for_step(step)
        if not tool:
            return Observation(target=step.tool, state_data={"ok": exec_res.ok}, raw_output=exec_res.message)
        inputs = dict(step.inputs)
        inputs["step_id"] = step.id
        return tool.observe(inputs, exec_res)

    def _verify_step(self, step: PlanStep, observation: Observation, exec_res: ExecutionResult) -> VerificationResult:
        tool = self._get_tool_for_step(step)
        if not tool:
            return VerificationResult(verified=exec_res.ok, evidence=exec_res.message)
        inputs = dict(step.inputs)
        inputs["step_id"] = step.id
        return tool.verify(inputs, observation, exec_res)
