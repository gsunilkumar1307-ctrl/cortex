from __future__ import annotations

import re
import time
from typing import Any

from .adapter import MCPToolAdapter, validate_input_schema
from .exceptions import MCPSecurityError, MCPTimeoutError, MCPValidationError
from .fetch_policy import FetchSecurityPolicy
from .models import MCPToolDefinition, MCPToolResult

try:
    from backend.core.contracts import (
        ExecutionError,
        ExecutionResult,
        Observation,
        TaskContext,
        VerificationResult,
    )
except ImportError:
    from core.contracts import (
        ExecutionError,
        ExecutionResult,
        Observation,
        TaskContext,
        VerificationResult,
    )


class MCPFetchToolAdapter(MCPToolAdapter):
    """
    Specialized MCP Tool Adapter for Web Content Retrieval (mcp-server-fetch).

    Enforces:
    1. Pre-invocation SSRF validation and URL canonicalization via FetchSecurityPolicy.
    2. Comprehensive metadata extraction: requested URL, final canonical URL, page title,
       extracted text, content length, timestamp, and truncation disclosure.
    3. Strict BaseTool lifecycle: EXECUTE -> OBSERVE -> VERIFY -> RECOVER.
    4. Safe handling of inaccessible pages (403, 404, 500, timeouts) without hallucinations.
    5. Conservative recovery rules preventing retries of blocked security violations.
    """

    def __init__(
        self,
        definition: MCPToolDefinition,
        manager: Any,
        namespaced_name: str | None = None,
        policy: FetchSecurityPolicy | None = None,
    ) -> None:
        super().__init__(definition, manager, namespaced_name=namespaced_name)
        self.policy = policy or FetchSecurityPolicy()

    def _extract_title(self, text: str) -> str:
        """Extracts the primary page title from markdown headings or metadata header."""
        for line in text.splitlines():
            line_s = line.strip()
            if line_s.startswith("# "):
                return line_s.lstrip("# ").strip()
            if line_s.startswith("## "):
                return line_s.lstrip("# ").strip()
            if line_s.lower().startswith("title:"):
                return line_s[6:].strip()
        return ""

    def execute(
        self,
        inputs: dict[str, Any],
        context: TaskContext | None = None,
    ) -> ExecutionResult:
        start_time = time.time()
        step_id = inputs.get("step_id", f"mcp-fetch-step-{self.name}")

        # 1. Extract arguments
        args = self._extract_call_arguments(inputs)
        raw_url = args.get("url") or inputs.get("url", "")
        if not raw_url and "urls" in inputs and isinstance(inputs["urls"], list) and inputs["urls"]:
            raw_url = inputs["urls"][0]

        if not raw_url:
            return ExecutionResult(
                step_id=step_id,
                ok=False,
                message="Missing required parameter 'url' for web content retrieval.",
                error="ValidationError",
                duration_ms=(time.time() - start_time) * 1000,
            )

        # 2. SSRF Guard and URL Validation
        is_valid, canonical_url, sec_err = self.policy.validate_url(raw_url)
        if not is_valid:
            return ExecutionResult(
                step_id=step_id,
                ok=False,
                message=f"URL validation failed: {sec_err}",
                data={"requested_url": raw_url, "error": sec_err},
                error="SecurityViolation",
                duration_ms=(time.time() - start_time) * 1000,
            )

        # 3. Prepare sanitized MCP arguments
        max_length = int(args.get("max_length", inputs.get("max_length", self.policy.max_response_length)))
        max_length = min(max_length, self.policy.max_response_length)
        raw_mode = bool(args.get("raw", inputs.get("raw", False)))

        call_args: dict[str, Any] = {
            "url": canonical_url,
            "max_length": max_length,
            "raw": raw_mode,
        }

        # 4. Invoke MCP Fetch Server via MCPServerManager
        timeout = float(inputs.get("timeout", self.policy.request_timeout_seconds))
        try:
            mcp_result: MCPToolResult = self.manager.call_tool(
                self.server_name,
                self.original_tool_name,
                call_args,
                timeout=timeout,
            )

            duration_ms = (time.time() - start_time) * 1000

            if mcp_result.is_error:
                error_msg = mcp_result.get_text_content() or "Failed to retrieve web content."
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=error_msg,
                    data={"requested_url": raw_url, "canonical_url": canonical_url, "raw": mcp_result.raw_response},
                    error="FetchError",
                    duration_ms=duration_ms,
                )

            extracted_text = mcp_result.get_text_content()
            title = self._extract_title(extracted_text)
            is_truncated = len(extracted_text) >= max_length

            metadata: dict[str, Any] = {
                "requested_url": raw_url,
                "canonical_url": canonical_url,
                "title": title,
                "character_count": len(extracted_text),
                "truncated": is_truncated,
                "timestamp": time.time(),
                "status": "success",
                "raw_mode": raw_mode,
            }

            if context is not None:
                if isinstance(context, dict):
                    context.setdefault("retrieved_content", {})[canonical_url] = {
                        "text": extracted_text,
                        "metadata": metadata,
                    }
                elif hasattr(context, "metadata") and isinstance(context.metadata, dict):
                    context.metadata.setdefault("retrieved_content", {})[canonical_url] = {
                        "text": extracted_text,
                        "metadata": metadata,
                    }
                elif hasattr(context, "custom_data") and isinstance(context.custom_data, dict):
                    context.custom_data.setdefault("retrieved_content", {})[canonical_url] = {
                        "text": extracted_text,
                        "metadata": metadata,
                    }

            return ExecutionResult(
                step_id=step_id,
                ok=True,
                message=extracted_text,
                data=metadata,
                duration_ms=duration_ms,
            )

        except MCPTimeoutError as te:
            return ExecutionResult(
                step_id=step_id,
                ok=False,
                message=f"Web content retrieval timed out for {canonical_url} after {timeout}s: {te}",
                data={"requested_url": raw_url, "canonical_url": canonical_url},
                error="TimeoutError",
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            return ExecutionResult(
                step_id=step_id,
                ok=False,
                message=f"Web content retrieval failed for {canonical_url}: {e}",
                data={"requested_url": raw_url, "canonical_url": canonical_url},
                error=type(e).__name__,
                duration_ms=(time.time() - start_time) * 1000,
            )

    def observe(
        self,
        inputs: dict[str, Any],
        execution_result: ExecutionResult,
    ) -> Observation:
        url = execution_result.data.get("canonical_url") or inputs.get("url", "")
        return Observation(
            target=f"fetch:{url}",
            state_data={
                "url": url,
                "ok": execution_result.ok,
                "title": execution_result.data.get("title", ""),
                "length": len(execution_result.message) if execution_result.ok else 0,
                "truncated": execution_result.data.get("truncated", False),
            },
            raw_output=execution_result.message,
            evidence_type="mcp_fetch_response",
        )

    def verify(
        self,
        inputs: dict[str, Any],
        observation: Observation,
        execution_result: ExecutionResult,
    ) -> VerificationResult:
        if not execution_result.ok:
            return VerificationResult(
                verified=False,
                confidence=1.0,
                evidence=f"Web content retrieval failed: {execution_result.error or execution_result.message}",
                error=execution_result.error,
            )

        length = observation.state_data.get("length", 0)
        url = observation.state_data.get("url", "")
        if length > 0:
            evidence = f"Successfully retrieved and verified {length} characters of readable web content from {url}."
            if observation.state_data.get("truncated"):
                evidence += " (Content was truncated at configured maximum limit)."
            return VerificationResult(
                verified=True,
                confidence=1.0,
                evidence=evidence,
            )

        return VerificationResult(
            verified=False,
            confidence=0.0,
            evidence=f"Retrieved empty response from {url}.",
            error="EmptyContent",
        )

    def recover(
        self,
        inputs: dict[str, Any],
        error: ExecutionError,
        attempt: int = 1,
    ) -> dict[str, Any]:
        err_type = error.error_type if hasattr(error, "error_type") else str(error)
        
        # Security violations (SSRF, prohibited addresses) must NEVER be retried
        if "SecurityViolation" in err_type:
            return {
                "can_retry": False,
                "strategy": "escalate",
                "message": "Access to this destination is blocked by the security policy.",
            }

        # Inaccessible pages (404, 403) should not be retried blind
        if "FetchError" in err_type:
            return {
                "can_retry": False,
                "strategy": "escalate",
                "message": "Webpage could not be retrieved. Offer browser automation or alternative public source.",
            }

        # Transient network timeouts can be retried once
        return {
            "can_retry": attempt < 2,
            "strategy": "retry" if attempt < 2 else "escalate",
            "message": "Transient network failure during web retrieval. Retrying..." if attempt < 2 else "Web retrieval failed after retry.",
        }
