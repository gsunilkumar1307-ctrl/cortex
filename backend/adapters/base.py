"""Application Adapter Contract for Cortex Agent.

Defines the universal application adapter interface, structured execution statuses,
adapter observations, and registry for application-specific drivers.

Every application adapter provides a standardized, verifiable boundary for desktop apps:
- launch()
- focus()
- observe(target_context)
- execute_action(action, params)
- verify_action(action, params, observation)
- recover(action, params, error, attempt)
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

try:
    from backend.core.contracts import (
        AdapterExecutionStatus,
        AdapterObservation,
        AdapterRecoveryResult,
        AdapterResult,
        ExecutionError,
        ExecutionResult,
        Observation,
        RiskLevel,
        TaskCommand,
        TaskContext,
        VerificationResult,
    )
    from backend.tools.base import BaseTool
except ImportError:
    from core.contracts import (
        AdapterExecutionStatus,
        AdapterObservation,
        AdapterRecoveryResult,
        AdapterResult,
        ExecutionError,
        ExecutionResult,
        Observation,
        RiskLevel,
        TaskCommand,
        TaskContext,
        VerificationResult,
    )
    from tools.base import BaseTool


class ApplicationAdapter(ABC):
    """Abstract base class for all application-specific adapters.

    Guarantees:
    - Consistent input/output contracts.
    - Structured execution results with explicit state distinctions
      (attempted, executed, verified, unverified, failed).
    - Independent observation and empirical verification.
    - Bounded recovery and safe retries without repeating completed side-effects.
    - No adapter may independently mark a task COMPLETED without satisfying the
      engine's verification requirements.
    """

    def __init__(self, app_name: str, dry_run: bool = False) -> None:
        self.app_name = app_name
        self.dry_run = dry_run

    @abstractmethod
    def launch(self) -> AdapterResult:
        """Launches the application process if not already running."""
        pass

    @abstractmethod
    def focus(self) -> AdapterResult:
        """Brings the application and its main window to the foreground."""
        pass

    @abstractmethod
    def observe(self, target_context: dict[str, Any] | None = None) -> AdapterObservation:
        """Captures observable external state from the application interface or system."""
        pass

    @abstractmethod
    def execute_action(self, action: str, params: dict[str, Any]) -> AdapterResult:
        """Executes a specific domain action on the application."""
        pass

    @abstractmethod
    def verify_action(
        self,
        action: str,
        params: dict[str, Any],
        observation: AdapterObservation,
    ) -> VerificationResult:
        """Independently verifies that the requested action produced the expected state."""
        pass

    @abstractmethod
    def recover(
        self,
        action: str,
        params: dict[str, Any],
        error: ExecutionError | str,
        attempt: int = 1,
    ) -> AdapterRecoveryResult:
        """Evaluates execution or verification errors and suggests recovery strategy."""
        pass


class ApplicationAdapterRegistry:
    """Registry managing available application adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, ApplicationAdapter] = {}

    def register(self, adapter: ApplicationAdapter) -> None:
        """Registers an application adapter under its canonical name and aliases."""
        canonical = adapter.app_name.strip().lower()
        self._adapters[canonical] = adapter

    def get_adapter(self, app_name: str) -> ApplicationAdapter | None:
        """Retrieves an application adapter by name or alias."""
        if not app_name:
            return None
        key = app_name.strip().lower()
        return self._adapters.get(key)

    def has_adapter(self, app_name: str) -> bool:
        """Checks if an adapter is registered for the given application."""
        if not app_name:
            return False
        return app_name.strip().lower() in self._adapters

    def list_adapters(self) -> list[str]:
        """Returns the list of registered adapter application names."""
        return [adapter.app_name for adapter in self._adapters.values()]


class AdapterToolWrapper(BaseTool):
    """Bridges an ApplicationAdapter into Cortex's BaseTool system.

    Allows ExecutionEngine and ToolRegistry to execute, observe, verify,
    and recover adapter-backed plan steps seamlessly.
    """

    def __init__(self, adapter: ApplicationAdapter, tool_name: str | None = None) -> None:
        name = tool_name or f"{adapter.app_name.lower()}_adapter"
        super().__init__(
            name=name,
            description=f"Automated controller for macOS application {adapter.app_name}",
            risk_level=RiskLevel.LOW,
            command=TaskCommand.UNKNOWN,
            irreversible=False,
        )
        self.adapter = adapter

    def execute(self, inputs: dict[str, Any], context: TaskContext | None = None) -> ExecutionResult:
        start_time = time.time()
        step_id = inputs.get("step_id", f"{self.adapter.app_name.lower()}_step")
        action = inputs.get("action") or inputs.get("command") or "execute"
        if isinstance(action, TaskCommand):
            action = action.value
        action_str = str(action)

        params = dict(inputs.get("params") or {})
        for k, v in inputs.items():
            if k not in ("action", "command", "params", "step_id") and k not in params:
                params[k] = v

        res = self.adapter.execute_action(action_str, params)
        duration_ms = (time.time() - start_time) * 1000

        return ExecutionResult(
            step_id=step_id,
            ok=res.success,
            message=res.message,
            data=res.data,
            error=res.error,
            duration_ms=duration_ms,
        )

    def observe(self, inputs: dict[str, Any], execution_result: ExecutionResult) -> Observation:
        params = dict(inputs.get("params") or {})
        for k, v in inputs.items():
            if k not in ("action", "command", "params", "step_id") and k not in params:
                params[k] = v
        if "appName" not in params and getattr(self.adapter, "app_name", None):
            params["appName"] = self.adapter.app_name

        adapter_obs = self.adapter.observe(params)
        state_data = dict(adapter_obs.state_data)
        state_data["ok"] = execution_result.ok
        action = inputs.get("action") or inputs.get("command") or "execute"
        action_str = action.value if isinstance(action, TaskCommand) else str(action)
        state_data["action"] = action_str
        if "appName" not in state_data and params.get("appName"):
            state_data["appName"] = params["appName"]
        if "text" not in state_data and params.get("text"):
            state_data["text"] = params["text"]

        return Observation(
            target=adapter_obs.target,
            state_data=state_data,
            raw_output=adapter_obs.raw_output,
            timestamp=adapter_obs.timestamp,
            evidence_type="application_adapter_observation",
        )

    def verify(
        self,
        inputs: dict[str, Any],
        observation: Observation,
        execution_result: ExecutionResult,
    ) -> VerificationResult:
        action = inputs.get("action") or inputs.get("command") or "execute"
        action_str = action.value if isinstance(action, TaskCommand) else str(action)
        if not execution_result.ok:
            return VerificationResult(
                verified=False,
                confidence=1.0,
                evidence=f"Action '{action_str}' failed during execution: {execution_result.error or execution_result.message}",
                error=execution_result.error,
            )

        params = dict(inputs.get("params") or {})
        for k, v in inputs.items():
            if k not in ("action", "command", "params", "step_id") and k not in params:
                params[k] = v
        if "appName" not in params and getattr(self.adapter, "app_name", None):
            params["appName"] = self.adapter.app_name

        adapter_obs = AdapterObservation(
            target=observation.target,
            state_data=observation.state_data,
            raw_output=observation.raw_output,
            timestamp=observation.timestamp,
        )

        return self.adapter.verify_action(action_str, params, adapter_obs)

    def recover(
        self,
        inputs: dict[str, Any],
        error: ExecutionError,
        attempt: int = 1,
    ) -> dict[str, Any]:
        action = inputs.get("action") or inputs.get("command") or "execute"
        action_str = action.value if isinstance(action, TaskCommand) else str(action)
        params = dict(inputs.get("params") or {})
        for k, v in inputs.items():
            if k not in ("action", "command", "params", "step_id") and k not in params:
                params[k] = v
        if "appName" not in params and getattr(self.adapter, "app_name", None):
            params["appName"] = self.adapter.app_name
        rec = self.adapter.recover(action_str, params, error, attempt)
        return {
            "can_retry": rec.can_retry,
            "strategy": rec.strategy,
            "message": rec.message,
            "suggested_params": rec.suggested_params,
        }
