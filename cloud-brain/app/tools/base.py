from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from cortex_sdk import (
    RiskLevel,
    TaskCommand,
    ExecutionResult,
    Observation,
    VerificationResult,
    ExecutionError,
    TaskContext,
)


class BaseTool(ABC):
    """Universal Tool Contract for Cortex.
    Every tool must implement:
    - execute: perform real action
    - observe: observe real-world external state
    - verify: independently verify whether action succeeded based on evidence
    - recover: provide safe recovery or diagnostic steps
    """

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any] | None = None,
        risk_level: RiskLevel = RiskLevel.LOW,
        command: TaskCommand = TaskCommand.UNKNOWN,
        irreversible: bool = False,
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema or {}
        self.risk_level = risk_level
        self.command = command
        self.irreversible = irreversible

    @abstractmethod
    def execute(
        self,
        inputs: dict[str, Any],
        context: TaskContext | None = None,
    ) -> ExecutionResult:
        """Executes the action on the external system."""
        pass

    @abstractmethod
    def observe(
        self,
        inputs: dict[str, Any],
        execution_result: ExecutionResult,
    ) -> Observation:
        """Inspects external system state to capture observable facts."""
        pass

    @abstractmethod
    def verify(
        self,
        inputs: dict[str, Any],
        observation: Observation,
        execution_result: ExecutionResult,
    ) -> VerificationResult:
        """Independently verifies that the expected outcome actually occurred."""
        pass

    def recover(
        self,
        inputs: dict[str, Any],
        error: ExecutionError,
        attempt: int = 1,
    ) -> dict[str, Any]:
        """Provides recovery suggestion or safe fallback. Default stops safely."""
        return {
            "can_retry": not self.irreversible and attempt < 3,
            "strategy": "retry" if (not self.irreversible and attempt < 3) else "escalate",
            "message": f"Action {self.name} encountered error: {error.message}. Escalate to user for guidance.",
        }
