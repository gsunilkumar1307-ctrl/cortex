from __future__ import annotations

import time
from typing import Any
from cortex_sdk import (
    ExecutionResult,
    Observation,
    VerificationResult,
    ExecutionError,
    RiskLevel,
    TaskCommand,
    TaskContext,
)
try:
    from backend.integrations.search import search_web
except ImportError:
    from skills import search_web
from .base import BaseTool


class WebSearchTool(BaseTool):
    """Universal Web Search Tool."""

    def __init__(self) -> None:
        super().__init__(
            name="web_search_tool",
            description="Searches the web using DuckDuckGo/Google search.",
            risk_level=RiskLevel.LOW,
            command=TaskCommand.WEB_SEARCH,
            irreversible=False,
        )

    def execute(self, inputs: dict[str, Any], context: TaskContext | None = None) -> ExecutionResult:
        start_time = time.time()
        query = inputs.get("query", "")
        step_id = inputs.get("step_id", "search-step")
        results = search_web(query, max_results=int(inputs.get("max_results", 5)))
        duration_ms = (time.time() - start_time) * 1000

        return ExecutionResult(
            step_id=step_id,
            ok=bool(results),
            message=f"Found {len(results)} results." if results else "No results found.",
            data={"results": results},
            duration_ms=duration_ms,
        )

    def observe(self, inputs: dict[str, Any], execution_result: ExecutionResult) -> Observation:
        query = inputs.get("query", "")
        results = execution_result.data.get("results", [])
        return Observation(
            target=f"web_search:{query}",
            state_data={"query": query, "result_count": len(results)},
            raw_output=execution_result.message,
            evidence_type="search_api_response",
        )

    def verify(
        self,
        inputs: dict[str, Any],
        observation: Observation,
        execution_result: ExecutionResult,
    ) -> VerificationResult:
        count = observation.state_data.get("result_count", 0)
        return VerificationResult(
            verified=count > 0,
            confidence=1.0 if count > 0 else 0.5,
            evidence=f"Retrieved {count} web search citations and snippets.",
        )

    def recover(
        self,
        inputs: dict[str, Any],
        error: ExecutionError,
        attempt: int = 1,
    ) -> dict[str, Any]:
        return {
            "can_retry": attempt < 2,
            "strategy": "replan" if attempt < 2 else "escalate",
            "message": "Web search returned no results. Try rephrasing query or using direct assistant knowledge.",
        }
