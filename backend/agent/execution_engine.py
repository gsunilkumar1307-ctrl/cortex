from __future__ import annotations

"""
Authoritative Execution Engine for Cortex Agent.
This module replaces the old custom agent loop with the official LangGraph framework.
"""

from typing import Any, Callable
try:
    from backend.agent.langgraph_engine import LangGraphExecutionEngine, CortexAgentState
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
    from agent.langgraph_engine import LangGraphExecutionEngine, CortexAgentState
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


# Official authoritative LangGraph engine replacing the custom agent loop
class ExecutionEngine(LangGraphExecutionEngine):
    """
    Cortex Execution Engine powered by the official LangGraph framework.
    All execution, observation, independent verification, bounded recovery,
    and approval interrupts are controlled by the compiled StateGraph.
    """
    pass


AutonomousExecutionEngine = ExecutionEngine
__all__ = ["ExecutionEngine", "AutonomousExecutionEngine", "LangGraphExecutionEngine", "CortexAgentState"]
