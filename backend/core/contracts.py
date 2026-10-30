from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4
import re


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    BLOCKED = "blocked"


class TaskStatus(str, Enum):
    # ── Canonical Phase 1 States (Spec Section 5.1) ───────────
    QUEUED = "queued"
    UNDERSTANDING = "understanding"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    PLANNED = "planned"
    EXECUTING = "executing"
    AWAITING_APPROVAL = "awaiting_approval"
    PAUSED_MODEL_UNAVAILABLE = "paused_model_unavailable"
    PAUSED_PERMISSION_REQUIRED = "paused_permission_required"
    RECOVERING = "recovering"
    VERIFYING = "verifying"
    NEEDS_ATTENTION = "needs_attention"
    COMPLETED = "completed"
    CANCELLED = "canceled"
    FAILED = "failed"

    # ── Compatibility Aliases ─────────────────────────────────
    IDLE = "idle"
    LISTENING = "listening"
    RECEIVED = "received"
    CONTEXT_BUILDING = "context_building"
    PLANNING = "planning"
    POLICY_CHECK = "policy_check"
    PROPOSED = "proposed"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_FOR_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    NEED_INFO = "need_info"
    WAITING_INPUT = "need_info"
    RUNNING = "running"
    OBSERVING = "observing"
    CANCELED = "canceled"
    BLOCKED = "blocked"
    UNCERTAIN = "uncertain"


class IllegalStateTransitionError(ValueError):
    """Raised when an illegal lifecycle transition is attempted."""
    pass


class ConcurrencyError(RuntimeError):
    """Raised when an optimistic concurrency version check fails."""
    pass


def canonical_status(status: TaskStatus | str) -> TaskStatus:
    """Normalize any task status or legacy alias to a canonical TaskStatus."""
    val = status.value if isinstance(status, TaskStatus) else str(status)
    val = val.lower().strip()
    alias_map: dict[str, TaskStatus] = {
        "idle": TaskStatus.QUEUED,
        "queued": TaskStatus.QUEUED,
        "listening": TaskStatus.UNDERSTANDING,
        "received": TaskStatus.UNDERSTANDING,
        "context_building": TaskStatus.UNDERSTANDING,
        "understanding": TaskStatus.UNDERSTANDING,
        "planning": TaskStatus.PLANNED,
        "policy_check": TaskStatus.PLANNED,
        "proposed": TaskStatus.PLANNED,
        "planned": TaskStatus.PLANNED,
        "waiting_approval": TaskStatus.AWAITING_APPROVAL,
        "waiting_for_approval": TaskStatus.AWAITING_APPROVAL,
        "awaiting_approval": TaskStatus.AWAITING_APPROVAL,
        "approved": TaskStatus.EXECUTING,
        "need_info": TaskStatus.AWAITING_CLARIFICATION,
        "waiting_input": TaskStatus.AWAITING_CLARIFICATION,
        "awaiting_clarification": TaskStatus.AWAITING_CLARIFICATION,
        "running": TaskStatus.EXECUTING,
        "executing": TaskStatus.EXECUTING,
        "observing": TaskStatus.VERIFYING,
        "verifying": TaskStatus.VERIFYING,
        "recovering": TaskStatus.RECOVERING,
        "paused_model_unavailable": TaskStatus.PAUSED_MODEL_UNAVAILABLE,
        "paused_permission_required": TaskStatus.PAUSED_PERMISSION_REQUIRED,
        "needs_attention": TaskStatus.NEEDS_ATTENTION,
        "completed": TaskStatus.COMPLETED,
        "canceled": TaskStatus.CANCELLED,
        "cancelled": TaskStatus.CANCELLED,
        "failed": TaskStatus.FAILED,
        "blocked": TaskStatus.NEEDS_ATTENTION,
        "uncertain": TaskStatus.NEEDS_ATTENTION,
    }
    return alias_map.get(val, TaskStatus.FAILED)


# Authoritative Allowed Lifecycle Transitions Table (Spec Section 5.1 & 5.2)
ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.QUEUED: {
        TaskStatus.UNDERSTANDING, TaskStatus.CANCELLED, TaskStatus.FAILED
    },
    TaskStatus.UNDERSTANDING: {
        TaskStatus.AWAITING_CLARIFICATION, TaskStatus.PLANNED, TaskStatus.AWAITING_APPROVAL,
        TaskStatus.EXECUTING, TaskStatus.PAUSED_MODEL_UNAVAILABLE, TaskStatus.CANCELLED, TaskStatus.FAILED
    },
    TaskStatus.AWAITING_CLARIFICATION: {
        TaskStatus.UNDERSTANDING, TaskStatus.PLANNED, TaskStatus.AWAITING_APPROVAL,
        TaskStatus.CANCELLED, TaskStatus.FAILED
    },
    TaskStatus.PLANNED: {
        TaskStatus.AWAITING_APPROVAL, TaskStatus.EXECUTING, TaskStatus.PAUSED_PERMISSION_REQUIRED,
        TaskStatus.CANCELLED, TaskStatus.FAILED
    },
    TaskStatus.AWAITING_APPROVAL: {
        TaskStatus.EXECUTING, TaskStatus.AWAITING_CLARIFICATION, TaskStatus.CANCELLED, TaskStatus.FAILED
    },
    TaskStatus.EXECUTING: {
        TaskStatus.VERIFYING, TaskStatus.RECOVERING, TaskStatus.NEEDS_ATTENTION,
        TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED,
        TaskStatus.PAUSED_MODEL_UNAVAILABLE, TaskStatus.PAUSED_PERMISSION_REQUIRED
    },
    TaskStatus.VERIFYING: {
        TaskStatus.COMPLETED, TaskStatus.RECOVERING, TaskStatus.NEEDS_ATTENTION,
        TaskStatus.FAILED, TaskStatus.CANCELLED
    },
    TaskStatus.RECOVERING: {
        TaskStatus.EXECUTING, TaskStatus.VERIFYING, TaskStatus.NEEDS_ATTENTION,
        TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.COMPLETED
    },
    TaskStatus.PAUSED_MODEL_UNAVAILABLE: {
        TaskStatus.UNDERSTANDING, TaskStatus.EXECUTING, TaskStatus.CANCELLED, TaskStatus.FAILED
    },
    TaskStatus.PAUSED_PERMISSION_REQUIRED: {
        TaskStatus.PLANNED, TaskStatus.EXECUTING, TaskStatus.CANCELLED, TaskStatus.FAILED
    },
    TaskStatus.NEEDS_ATTENTION: {
        TaskStatus.AWAITING_CLARIFICATION, TaskStatus.AWAITING_APPROVAL,
        TaskStatus.EXECUTING, TaskStatus.CANCELLED, TaskStatus.FAILED
    },
    TaskStatus.COMPLETED: set(),  # Terminal
    TaskStatus.CANCELLED: set(),  # Terminal
    TaskStatus.FAILED: set(),     # Terminal
}

TERMINAL_STATUSES: set[TaskStatus] = {
    TaskStatus.COMPLETED,
    TaskStatus.CANCELLED,
    TaskStatus.FAILED,
}


class ActionAttemptStatus(str, Enum):
    INITIATED = "initiated"
    OBSERVED = "observed"
    VERIFIED = "verified"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


@dataclass
class ActionAttempt:
    id: str = field(default_factory=lambda: str(uuid4()))
    task_id: str = ""
    step_id: str | None = None
    action_type: str = ""
    payload_hash: str = ""
    status: ActionAttemptStatus = ActionAttemptStatus.INITIATED
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "taskId": self.task_id,
            "stepId": self.step_id,
            "actionType": self.action_type,
            "payloadHash": self.payload_hash,
            "status": self.status.value,
            "startedAt": self.started_at,
            "completedAt": self.completed_at,
            "evidence": self.evidence,
        }


class TaskCommand(str, Enum):
    OPEN_APP = "open_app"
    CLOSE_APP = "close_app"
    FOCUS_APP = "focus_app"
    TYPE_TEXT = "type_text"
    KEYSTROKE = "keystroke"
    MENU_ITEM = "menu_item"
    WRITE_NOTE = "write_note"
    SEND_MESSAGE = "send_message"
    CALCULATE = "calculate"
    SCREENSHOT = "screenshot"
    CLIPBOARD_READ = "clipboard_read"
    CLIPBOARD_WRITE = "clipboard_write"
    NOTIFICATION = "notification"
    REMINDER = "reminder"
    SHUTDOWN = "shutdown"
    RESTART = "restart"
    ASK_QUESTION = "ask_question"
    WEB_SEARCH = "web_search"
    # ── Phase 4: Browser & Vision ──────────────────────────
    OPEN_URL = "open_url"           # Navigate browser to a URL
    BROWSER_CLICK = "browser_click" # Click an element on a web page
    BROWSER_TYPE = "browser_type"   # Type into a web page field
    BROWSER_SCRAPE = "browser_scrape" # Extract text/data from a web page
    SCREEN_VISION = "screen_vision" # Take screenshot + AI describes what it sees
    # ── Phase 5: Mail Automation ───────────────────────────
    READ_MAIL = "read_mail"         # Read recent/unread inbox messages
    SUMMARIZE_MAIL = "summarize_mail" # AI summary of recent email threads
    DRAFT_MAIL = "draft_mail"       # Create/open draft email in Apple Mail
    SEND_MAIL = "send_mail"         # Send email (requires approval)
    SEARCH_MAIL = "search_mail"     # Search emails by query/sender
    EMAIL_BRIEFING = "email_briefing" # Executive briefing of emails
    EXTRACT_ACTIONS = "extract_actions" # Action item extraction from emails
    # ── Phase 7: Personal Assistant, Files & Calendar ──────
    SEARCH_FILES = "search_files"   # Search files
    READ_FILE = "read_file"         # Read file
    WRITE_FILE = "write_file"       # Write file
    CALENDAR_READ = "calendar_read" # Read calendar events
    CALENDAR_CREATE = "calendar_create" # Create calendar event
    PERSONAL_TASK_CREATE = "personal_task_create" # Create personal task
    PERSONAL_TASK_LIST = "personal_task_list"     # List personal tasks
    DAILY_BRIEFING = "daily_briefing"             # Daily briefing
    # ── Phase 3: Multilingual & Translation ────────────────
    TRANSLATE = "translate"                       # Translate text across languages
    # ── Phase 8: Autonomous Desktop Operator & WhatsApp ────
    DRAFT_WHATSAPP = "draft_whatsapp"             # Prepare WhatsApp message draft
    SEND_WHATSAPP = "send_whatsapp"               # Send WhatsApp message (requires approval)
    CLOSE_WINDOW = "close_window"                 # Close frontmost window without quitting app
    QUIT_APP = "quit_app"                         # Quit application (with unsaved changes check)
    INSPECT_APP = "inspect_app"                   # Inspect application state (running, windows)
    MOVE_FILE = "move_file"                       # Move or rename file in safe sandbox
    CREATE_DOCUMENT = "create_document"           # Create structured document
    # ── Screen Intelligence & Autonomous Desktop Operator ──
    OBSERVE_SCREEN = "observe_screen"             # Multi-source desktop perception
    RESOLVE_UI_ELEMENT = "resolve_ui_element"     # Resolve UI element target
    CLICK_ELEMENT = "click_element"               # Click resolved UI element
    TYPE_IN_ELEMENT = "type_in_element"           # Type into resolved UI element
    DESKTOP_WORKFLOW = "desktop_workflow"         # Multi-step supervised UI workflow
    UNKNOWN = "unknown"



# ── Language Support ──────────────────────────────────────────────────────────
class LanguageCode(str, Enum):
    """Supported language codes for Cortex multilingual mode."""
    AUTO   = "auto"   # Detect automatically
    ENGLISH  = "en"  # English
    KANNADA  = "kn"  # ಕನ್ನಡ
    HINDI    = "hi"  # हिन्दी
    TAMIL    = "ta"  # தமிழ்
    TELUGU   = "te"  # తెలుగు

    @classmethod
    def from_string(cls, value: str) -> "LanguageCode":
        """Case-insensitive lookup with AUTO as default fallback."""
        try:
            return cls(value.lower())
        except (ValueError, AttributeError):
            return cls.AUTO

    @property
    def display_name(self) -> str:
        return {
            "auto": "Auto-detect",
            "en": "English",
            "kn": "ಕನ್ನಡ (Kannada)",
            "hi": "हिन्दी (Hindi)",
            "ta": "தமிழ் (Tamil)",
            "te": "తెలుగు (Telugu)",
        }.get(self.value, self.value)


@dataclass(frozen=True)
class AuditEvent:
    type: str
    message: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.type

    @property
    def event_type(self) -> str:
        return self.type

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "message": self.message,
            "createdAt": self.created_at,
            "data": self.data,
        }


# ── Structured Pipeline Models ─────────────────────────────────────────────────

@dataclass
class UserRequest:
    text: str
    source: str = "text"  # text, voice, api
    session_id: str = field(default_factory=lambda: str(uuid4()))
    language: LanguageCode = LanguageCode.ENGLISH
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "source": self.source,
            "sessionId": self.session_id,
            "language": self.language.value,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class Intent:
    command: TaskCommand
    action: str
    confidence: float = 1.0
    parameters: dict[str, Any] = field(default_factory=dict)
    raw_content: str = ""
    is_command: bool = True
    purpose: str = ""
    requires_disambiguation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command.value,
            "action": self.action,
            "confidence": self.confidence,
            "parameters": self.parameters,
            "rawContent": self.raw_content,
            "isCommand": self.is_command,
            "purpose": self.purpose,
            "requiresDisambiguation": self.requires_disambiguation,
        }


@dataclass
class TaskContext:
    recipient: str = ""
    recipient_role: str = ""        # professor, manager, recruiter, client, colleague, friend, support, unknown
    relationship: str = "professional"  # professional, academic, hierarchical, peer, external, personal
    user_role: str = ""
    company_organization: str = ""
    purpose: str = ""
    subject_context: str = ""
    known_facts: list[str] = field(default_factory=list)
    thread_context: list[dict[str, Any]] = field(default_factory=list)
    requested_tone: str = ""        # formal, concise, respectful, casual, warm
    urgency: str = "normal"         # low, normal, urgent
    language: LanguageCode = LanguageCode.ENGLISH
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipient": self.recipient,
            "recipientRole": self.recipient_role,
            "relationship": self.relationship,
            "userRole": self.user_role,
            "companyOrganization": self.company_organization,
            "purpose": self.purpose,
            "subjectContext": self.subject_context,
            "knownFacts": self.known_facts,
            "threadContext": self.thread_context,
            "requestedTone": self.requested_tone,
            "urgency": self.urgency,
            "language": self.language.value,
            "metadata": self.metadata,
        }


@dataclass
class StructuredGoal:
    """Explicit, schema-validated representation of user objective before execution."""
    objective: str
    desired_outcome: str = ""
    target_app: str = ""
    target_entity: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)
    prohibitions: list[str] = field(default_factory=list)
    language: LanguageCode = LanguageCode.ENGLISH
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    missing_info: list[str] = field(default_factory=list)
    success_criteria: str = ""
    verification_method: str = "state_check"
    channel: str = "desktop"  # desktop, email, whatsapp, browser, files

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "desiredOutcome": self.desired_outcome,
            "targetApp": self.target_app,
            "targetEntity": self.target_entity,
            "parameters": self.parameters,
            "constraints": self.constraints,
            "prohibitions": self.prohibitions,
            "language": self.language.value,
            "riskLevel": self.risk_level.value,
            "requiresApproval": self.requires_approval,
            "missingInfo": self.missing_info,
            "successCriteria": self.success_criteria,
            "verificationMethod": self.verification_method,
            "channel": self.channel,
        }


class ContactResolutionStatus(str, Enum):
    EXACT_MATCH = "exact_match"
    MULTIPLE_MATCHES = "multiple_matches"
    NO_MATCH = "no_match"
    SOURCE_UNAVAILABLE = "source_unavailable"
    CONTACT_DATA_STALE = "contact_data_stale"
    INVALID_OR_UNVERIFIED_NUMBER = "invalid_or_unverified_number"
    # Phase 2 UI Contact Resolution States:
    NEEDS_RECIPIENT = "needs_recipient"
    SEARCHING_WHATSAPP = "searching_whatsapp"
    CANDIDATES_FOUND = "candidates_found"
    NEEDS_DISAMBIGUATION = "needs_disambiguation"
    RECIPIENT_VERIFIED_FOR_DRAFT = "recipient_verified_for_draft"
    RECIPIENT_STALE = "recipient_stale"
    WHATSAPP_UNAVAILABLE = "whatsapp_unavailable"
    RECIPIENT_UNVERIFIED = "recipient_unverified"
    CANCELLED = "cancelled"


@dataclass
class VerifiedContact:
    id: str
    name: str
    phone: str
    source: str
    is_verified: bool = True
    verified_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def role(self) -> str:
        return self.metadata.get("role", "contact")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone,
            "source": self.source,
            "isVerified": self.is_verified,
            "verifiedAt": self.verified_at,
            "metadata": self.metadata,
        }


@dataclass
class ContactResolutionResult:
    status: ContactResolutionStatus
    query: str
    contact: VerifiedContact | None = None
    candidates: list[VerifiedContact] = field(default_factory=list)
    suggestions: list[VerifiedContact] = field(default_factory=list)
    clarification_prompt: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "query": self.query,
            "contact": self.contact.to_dict() if self.contact else None,
            "candidates": [c.to_dict() for c in self.candidates],
            "suggestions": [s.to_dict() for s in self.suggestions],
            "clarificationPrompt": self.clarification_prompt,
            "source": self.source,
        }


@dataclass
class WhatsAppDraft:
    """Payload-bound representation of a WhatsApp message draft with cryptographic hashing."""
    recipient: str
    phone: str = ""
    body: str = ""
    tone: str = "casual"
    language: str = "en"
    channel: str = "whatsapp"
    contact_id: str = ""
    contact_source: str = ""
    draft_only: bool = False
    evidence_type: str = "visible_ui"
    evidence_label: str = ""
    attempt_id: str = ""
    conversation_title: str = ""
    audit_notes: list[str] = field(default_factory=list)
    approval_hash: str = ""

    def __post_init__(self) -> None:
        if not self.approval_hash:
            self.approval_hash = self.compute_hash()

    def canonicalize(self) -> dict[str, Any]:
        """Returns normalized canonical dictionary for tamper-evident hashing."""
        data = {
            "channel": "whatsapp",
            "recipient": (self.recipient or "").strip(),
            "phone": re.sub(r"[^\d+]", "", (self.phone or "").strip()),
            "body": (self.body or "").strip(),
        }
        if self.contact_id:
            data["contact_id"] = self.contact_id.strip()
        if self.contact_source:
            data["contact_source"] = self.contact_source.strip()
        if self.draft_only:
            data["draft_only"] = True
        if self.conversation_title:
            data["conversation_title"] = self.conversation_title.strip()
        return data

    def compute_hash(self) -> str:
        """Computes unambiguous SHA-256 digest over normalized payload fields."""
        import hashlib
        import json
        data = self.canonicalize()
        serialized = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipient": self.recipient,
            "phone": self.phone,
            "body": self.body,
            "tone": self.tone,
            "language": self.language,
            "channel": self.channel,
            "contactId": self.contact_id,
            "contactSource": self.contact_source,
            "draftOnly": self.draft_only,
            "evidenceType": self.evidence_type,
            "evidenceLabel": self.evidence_label,
            "attemptId": self.attempt_id,
            "conversationTitle": self.conversation_title,
            "approvalHash": self.approval_hash,
            "auditNotes": self.audit_notes,
        }


@dataclass
class PlanStep:
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    action: str = ""
    tool: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    expected_result: str = ""
    risk_level: RiskLevel = RiskLevel.LOW
    approval_required: bool = False
    verification_method: str = "state_check"
    timeout_seconds: float = 30.0
    retry_policy: dict[str, Any] = field(default_factory=lambda: {"max_retries": 2, "backoff_seconds": 1.0})
    recovery_strategy: str = "abort"  # retry, replan, fallback, abort, escalate
    status: str = "pending"          # pending, running, completed, failed, skipped
    command: TaskCommand = TaskCommand.UNKNOWN
    description: str = ""
    expected_outcome: str = ""

    def __post_init__(self) -> None:
        if not self.action and self.description:
            self.action = self.description
        if not self.description and self.action:
            self.description = self.action
        if not self.expected_result and self.expected_outcome:
            self.expected_result = self.expected_outcome
        if not self.expected_outcome and self.expected_result:
            self.expected_outcome = self.expected_result

    @property
    def params(self) -> dict[str, Any]:
        return self.inputs

    @params.setter
    def params(self, value: dict[str, Any]) -> None:
        self.inputs = value

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "tool": self.tool,
            "inputs": self.inputs,
            "expectedResult": self.expected_result,
            "riskLevel": self.risk_level.value,
            "approvalRequired": self.approval_required,
            "verificationMethod": self.verification_method,
            "timeoutSeconds": self.timeout_seconds,
            "retryPolicy": self.retry_policy,
            "recoveryStrategy": self.recovery_strategy,
            "status": self.status,
        }


@dataclass
class Plan:
    goal: str = ""
    steps: list[PlanStep] = field(default_factory=list)
    strategy: str = "sequential"
    estimated_duration_seconds: int = 5
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    task_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "taskId": self.task_id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "strategy": self.strategy,
            "estimatedDurationSeconds": self.estimated_duration_seconds,
            "createdAt": self.created_at,
        }


@dataclass
class ToolCall:
    tool_name: str
    action: str
    parameters: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    idempotency_token: str = field(default_factory=lambda: str(uuid4()))
    timeout_seconds: float = 30.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "toolName": self.tool_name,
            "action": self.action,
            "parameters": self.parameters,
            "idempotencyToken": self.idempotency_token,
            "timeoutSeconds": self.timeout_seconds,
        }


@dataclass
class Observation:
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    target: str = ""
    state_data: dict[str, Any] = field(default_factory=dict)
    raw_output: str = ""
    evidence_type: str = "direct"

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "target": self.target,
            "stateData": self.state_data,
            "rawOutput": self.raw_output,
            "evidenceType": self.evidence_type,
        }


@dataclass
class VerificationResult:
    verified: bool
    evidence: str = ""
    confidence: float = 1.0
    uncertainty_reason: str | None = None
    error: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "uncertaintyReason": self.uncertainty_reason,
            "error": self.error,
            "timestamp": self.timestamp,
        }


@dataclass
class ApprovalRequest:
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    task_id: str = ""
    step_id: str = ""
    action_summary: str = ""
    risk_level: RiskLevel = RiskLevel.HIGH
    details: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "taskId": self.task_id,
            "stepId": self.step_id,
            "actionSummary": self.action_summary,
            "riskLevel": self.risk_level.value,
            "details": self.details,
            "createdAt": self.created_at,
        }


@dataclass
class ExecutionResult:
    step_id: str
    ok: bool
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "stepId": self.step_id,
            "ok": self.ok,
            "message": self.message,
            "data": self.data,
            "error": self.error,
            "durationMs": self.duration_ms,
        }


@dataclass
class ExecutionError:
    code: str
    message: str
    recoverable: bool = False
    suggested_action: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "recoverable": self.recoverable,
            "suggestedAction": self.suggested_action,
            "details": self.details,
        }


@dataclass
class FinalResult:
    task_id: str
    status: TaskStatus
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    verification_evidence: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "status": self.status.value,
            "summary": self.summary,
            "data": self.data,
            "verificationEvidence": self.verification_evidence,
            "durationMs": self.duration_ms,
        }


@dataclass
class Task:
    intent: str = ""
    command: TaskCommand = TaskCommand.UNKNOWN
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    id: str = field(default_factory=lambda: str(uuid4()))
    status: TaskStatus = TaskStatus.PROPOSED
    steps: list[str] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    audit_trail: list[AuditEvent] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    language: LanguageCode = LanguageCode.ENGLISH
    context: TaskContext | None = None
    plan: Plan | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    verifications: list[VerificationResult] = field(default_factory=list)
    approval_request: ApprovalRequest | None = None
    execution_history: list[ExecutionResult] = field(default_factory=list)
    state_version: int = 1
    cancellation_requested: bool = False
    approval_hash: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def events(self) -> list[AuditEvent]:
        return self.audit_trail

    def add_event(self, event_type: str, message: str, **data: Any) -> None:
        self.audit_trail.append(AuditEvent(event_type, message, data=data))

    def transition_to(
        self,
        new_status: TaskStatus | str,
        reason: str = "",
        expected_version: int | None = None,
        force_admin: bool = False,
    ) -> None:
        """
        Authoritative task lifecycle state transition.
        Enforces:
        - Optimistic concurrency guard if expected_version is provided.
        - Terminal state immutability (COMPLETED, CANCELLED, FAILED).
        - Explicit allowed transition graph validation.
        - Automatic state_version increment and audit logging.
        """
        new_canon = canonical_status(new_status)
        curr_canon = canonical_status(self.status)

        if expected_version is not None and expected_version != self.state_version:
            raise ConcurrencyError(
                f"Concurrency conflict: expected version {expected_version}, but task is at version {self.state_version}"
            )

        if not force_admin and curr_canon in TERMINAL_STATUSES:
            raise IllegalStateTransitionError(
                f"Cannot transition terminal task from '{self.status.value}' to '{new_status}'"
            )

        allowed = ALLOWED_TRANSITIONS.get(curr_canon, set())
        if not force_admin and new_canon not in allowed and curr_canon != new_canon:
            raise IllegalStateTransitionError(
                f"Illegal lifecycle transition from '{self.status.value}' to '{new_status}'. Allowed targets: {[s.value for s in allowed]}"
            )

        prev_status = self.status
        self._in_transition = True
        try:
            self.status = new_status if isinstance(new_status, TaskStatus) else new_canon
            self.state_version += 1
            self.updated_at = datetime.now(timezone.utc).isoformat()
        finally:
            self._in_transition = False

        if new_canon == TaskStatus.CANCELLED:
            self.cancellation_requested = True

        self.add_event(
            "task_transition",
            reason or f"State transitioned from {prev_status} to {self.status}",
            from_status=prev_status.value if hasattr(prev_status, "value") else str(prev_status),
            to_status=self.status.value if hasattr(self.status, "value") else str(self.status),
            state_version=self.state_version,
            reason=reason,
        )

    def request_cancellation(self, reason: str = "User requested cancellation") -> None:
        """Durable cancellation request with safe state transition."""
        self.cancellation_requested = True
        curr_canon = canonical_status(self.status)
        if curr_canon not in TERMINAL_STATUSES:
            self.transition_to(TaskStatus.CANCELLED, reason=reason)

    def to_dict(self) -> dict[str, Any]:
        cmd_val = self.command.value if hasattr(self.command, "value") else str(self.command)
        risk_val = self.risk_level.value if hasattr(self.risk_level, "value") else str(self.risk_level)
        d: dict[str, Any] = {
            "id": self.id,
            "intent": self.intent,
            "command": cmd_val,
            "riskLevel": risk_val,
            "requiresApproval": self.requires_approval,
            "status": self.status.value,
            "steps": self.steps,
            "result": self.result,
            "error": self.error,
            "auditTrail": [event.to_dict() for event in self.audit_trail],
            "params": self.params,
            "language": self.language.value,
            "stateVersion": self.state_version,
            "cancellationRequested": self.cancellation_requested,
            "approvalHash": self.approval_hash or self.params.get("approval_hash"),
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
        if self.context:
            d["context"] = self.context.to_dict()
        if self.plan:
            d["plan"] = self.plan.to_dict()
        if self.approval_request:
            d["approvalRequest"] = self.approval_request.to_dict()
        if self.verifications:
            d["verifications"] = [v.to_dict() for v in self.verifications]
        return d


def task_from_dict(payload: dict[str, Any]) -> Task:
    task = Task(
        id=payload["id"],
        intent=payload["intent"],
        command=TaskCommand(payload["command"]),
        risk_level=RiskLevel(payload["riskLevel"]),
        requires_approval=bool(payload["requiresApproval"]),
        status=TaskStatus(payload["status"]),
        steps=list(payload.get("steps", [])),
        result=payload.get("result"),
        error=payload.get("error"),
        params=dict(payload.get("params", {})),
        language=LanguageCode.from_string(payload.get("language", "en")),
        state_version=int(payload.get("stateVersion", 1)),
        cancellation_requested=bool(payload.get("cancellationRequested", False)),
        approval_hash=payload.get("approvalHash") or payload.get("params", {}).get("approval_hash"),
        created_at=payload.get("createdAt") or datetime.now(timezone.utc).isoformat(),
        updated_at=payload.get("updatedAt") or datetime.now(timezone.utc).isoformat(),
    )
    for raw_event in payload.get("auditTrail", []):
        task.audit_trail.append(
            AuditEvent(
                type=raw_event["type"],
                message=raw_event["message"],
                created_at=raw_event["createdAt"],
                data=dict(raw_event.get("data", {})),
            )
        )
    return task


def command_from_intent(intent: str) -> TaskCommand:
    import re
    text = intent.lower().strip()
    prefix_match = re.match(r"^(?:hey\s+cortex|cortex|ok\s+cortex|hello\s+cortex|hi\s+cortex|please|can\s+you|could\s+you)\s*[,:]?\s*(.+)$", text, flags=re.IGNORECASE)
    if prefix_match:
        text = prefix_match.group(1).strip()
    if text.startswith(("calculate ", "compute ")) or (text.startswith(("what is ", "what's ")) and any(word in text for word in (" plus ", " minus ", " times ", " divided by ", "+", "-", "*", "/"))) or any(word in text for word in (" plus ", " minus ", " times ", " divided by ")):
        return TaskCommand.CALCULATE
    if text.startswith(("write note ", "write a note ", "create note ", "create a note ", "take a note ", "note ")):
        return TaskCommand.WRITE_NOTE
    if (
        text.startswith((
            "send message ", "send a message ", "text ", "message ",
            "prepare message ", "prepare a message ", "draft message ", "draft a message ",
            "create message ", "create a message ", "compose message ", "compose a message ",
            "prepare whatsapp ", "prepare a whatsapp ", "draft whatsapp ", "draft a whatsapp ",
            "send whatsapp ", "send a whatsapp "
        ))
        or (text.startswith(("send ", "prepare ", "draft ", "create ")) and any(m in text for m in ("message", "whatsapp", "sms")) and not any(e in text for e in ("mail", "email")))
        or (any(m in text for m in ("whatsapp", "ವಾಟ್ಸಾಪ್", "व्हाट्सएप", "வாட்ஸ்அப்", "వాట్సాప్")) and any(v in text for v in ("message", "send", "ಸಂದೇಶ", "ಕಳುಹಿಸಿ", "ಕಳಿಸಿ", "संदेश", "भेजें", "भेजो", "मैसेज", "செய்தி", "அனுப்பு", "సందేశం", "పంపు")))
    ):
        return TaskCommand.SEND_MESSAGE
    if any(word in text for word in ("shutdown", "shut down", "power off")):
        return TaskCommand.SHUTDOWN
    if any(word in text for word in ("restart", "reboot")):
        return TaskCommand.RESTART
    if "screenshot" in text or "screen shot" in text:
        return TaskCommand.SCREENSHOT
    if "clipboard" in text and any(word in text for word in ("copy", "write", "set", "update")):
        return TaskCommand.CLIPBOARD_WRITE
    if "clipboard" in text or "pasteboard" in text:
        return TaskCommand.CLIPBOARD_READ
    if any(word in text for word in ("notify", "notification", "alert")):
        return TaskCommand.NOTIFICATION
    if "remind" in text or "reminder" in text:
        return TaskCommand.REMINDER
    if text.startswith(("focus ", "switch to ", "bring up ", "activate ")):
        return TaskCommand.FOCUS_APP
    if any(phrase in text for phrase in ("what is on my screen", "what's on my screen", "read my screen", "describe my screen", "look at my screen", "analyze screen", "check screen", "see my screen")):
        return TaskCommand.SCREEN_VISION
    # ── Screen Intelligence & Autonomous Desktop Operator ──
    if any(phrase in text for phrase in ("observe screen", "inspect screen", "scan screen", "desktop perception", "read screen elements")):
        return TaskCommand.OBSERVE_SCREEN
    if any(phrase in text for phrase in ("find the ", "locate the ", "where is the ", "find element ", "find button ")) and any(k in text for k in ("button", "field", "box", "menu", "tab", "window", "element")):
        return TaskCommand.RESOLVE_UI_ELEMENT
    if (text.startswith(("click ", "tap ", "click on ", "tap on ", "click button ", "click element ", "press button ", "press the button ")) or "click on " in text) and not any(w in text for w in ("browser", "web", "menu")):
        return TaskCommand.CLICK_ELEMENT
    if text.startswith(("type into ", "type in ", "fill in ")) and not any(w in text for w in ("browser", "web")):
        return TaskCommand.TYPE_IN_ELEMENT
    if text.startswith(("open url ", "go to ", "visit ", "browse to ", "navigate to ")) or (("http://" in text or "https://" in text or ".com" in text or ".org" in text) and "open " in text):
        return TaskCommand.OPEN_URL
    if text.startswith(("click on web ", "browser click ", "click link ", "click element ", "web click ")):
        return TaskCommand.BROWSER_CLICK
    if text.startswith(("type in browser ", "browser type ", "fill field ", "enter in browser ")):
        return TaskCommand.BROWSER_TYPE
    if text.startswith(("scrape ", "scrape web ", "read web page ", "extract from web ")):
        return TaskCommand.BROWSER_SCRAPE
    # ── Phase 5: Mail Automation (must precede generic text typing) ─────────
    if any(phrase in text for phrase in (
        "summarize email", "summarize emails", "summarize my email", "summarize my emails",
        "summarize inbox", "summarize my inbox", "summarize unread email", "summarize unread emails",
        "email summary", "summary of my emails", "summary of my inbox", "summary of unread emails",
        "give me a summary of my email", "give me a summary of my emails", "give me a summary of my inbox"
    )):
        return TaskCommand.SUMMARIZE_MAIL
    if any(phrase in text for phrase in (
        "read email", "read emails", "read my email", "read my emails",
        "check email", "check my email", "check emails", "check my emails",
        "check inbox", "check my inbox", "read inbox", "read my inbox",
        "check unread email", "check unread emails", "read unread email", "read unread emails",
        "get my emails", "get recent emails", "show my emails", "show recent emails"
    )):
        return TaskCommand.READ_MAIL
    if text.startswith(("send email ", "send an email ", "send mail ", "send a mail ", "email to ")) or (text.startswith("email ") and (" saying " in text or " subject " in text or " with subject " in text)):
        return TaskCommand.SEND_MAIL
    if (
        re.search(r"\b(?:draft|write|compose|prepare)\s+(?:an?\s+)?(?:polite\s+|formal\s+|casual\s+|brief\s+|short\s+|quick\s+)?(?:draft\s+)?(?:email|mail)\b", text)
        or text.startswith((
            "draft email ", "draft an email ", "create draft email ", "create a draft email ",
            "write a draft email ", "write draft email ", "draft mail ", "draft a mail ",
            "prepare an email ", "compose email ", "compose an email ",
            "write a polite email", "write an email", "write email", "write mail", "write a mail"
        ))
    ):
        return TaskCommand.DRAFT_MAIL
    if (
        text.startswith(("type exactly ", "type text ", "enter text ", "type in ", "type into "))
        or (text.startswith("type ") and not re.search(r"\b(?:an?\s+)?(?:email|mail)\b", text))
        or (text.startswith("write ") and not re.search(r"\b(?:email|mail|note|message|letter)\b", text))
    ):
        return TaskCommand.TYPE_TEXT
    if text.startswith(("press ", "hit key ", "use shortcut ")):
        return TaskCommand.KEYSTROKE
    if text.startswith(("choose ", "select menu ", "click menu ")):
        return TaskCommand.MENU_ITEM
    if text.startswith(("close window", "close the window", "shut window")):
        return TaskCommand.CLOSE_WINDOW
    if text.startswith(("is running", "is app running", "inspect app", "check app")):
        return TaskCommand.INSPECT_APP
    if text.startswith(("close ", "exit ", "quit ")) or any(phrase in text for phrase in ("close app", "close application", "quit app", "quit application")):
        return TaskCommand.CLOSE_APP
    # ── File / Finder Listing & Inspection ──────────────────
    if (
        any(phrase in text for phrase in (
            "open finder and list", "list files in", "list my files in", "show files in", "show me files in",
            "list files", "show files", "show me files", "files in downloads", "files in documents", "files in desktop",
            "files in finder", "list my downloads", "list downloads", "show my downloads", "show downloads",
            "what files are in", "view files in", "browse files in"
        ))
        or (text.startswith("finder ") and "files" in text)
    ):
        return TaskCommand.SEARCH_FILES

    # ── Web Research / Safari Search ────────────────────────
    if (
        re.search(r"\b(?:search\s+for|research|look\s+up|google)\b.*\b(?:in\s+safari|using\s+safari|on\s+safari)\b", text)
        or re.search(r"\bopen\s+safari\s+(?:and\s+|to\s+)(?:search\s+for|research|google|look\s+up)\b", text)
        or text.startswith("research ")
    ):
        return TaskCommand.WEB_SEARCH

    if text.startswith("open ") or "launch " in text or "start " in text:
        return TaskCommand.OPEN_APP
    if text.startswith(("move file ", "rename file ", "move the file ")):
        return TaskCommand.MOVE_FILE
    if text.startswith(("create document ", "new document ", "make document ")):
        return TaskCommand.CREATE_DOCUMENT
    if text.startswith(("google ", "search ", "search the web for ", "look up ")):
        return TaskCommand.WEB_SEARCH

    # ── Phase 7: Personal Assistant, Files & Calendar ──────
    if any(phrase in text for phrase in ("daily briefing", "what's my day looking like", "what is my schedule today", "how does my day look")):
        return TaskCommand.DAILY_BRIEFING
    if any(phrase in text for phrase in ("email briefing", "inbox briefing", "what needs my attention", "what's important in my inbox", "which emails need a reply")):
        return TaskCommand.EMAIL_BRIEFING
    if any(phrase in text for phrase in ("find email", "search email", "search mail", "find emails from", "emails from", "emails about")):
        return TaskCommand.SEARCH_MAIL
    if text.startswith(("find file", "search file", "look for file", "locate file", "find the file")):
        return TaskCommand.SEARCH_FILES
    if text.startswith(("read file", "open file", "view file", "show file")):
        return TaskCommand.READ_FILE
    if any(phrase in text for phrase in ("what meetings do i have", "my calendar", "check calendar", "am i free", "my schedule")):
        return TaskCommand.CALENDAR_READ
    if text.startswith(("add task", "create task", "new task", "remind me to")):
        return TaskCommand.PERSONAL_TASK_CREATE
    if any(phrase in text for phrase in ("my tasks", "list tasks", "show tasks", "what are my tasks", "pending tasks")):
        return TaskCommand.PERSONAL_TASK_LIST

    # ── Multilingual & Indic Script Support ─────────────────
    # Greetings & Conversational Questions
    indic_greetings = (
        "ನಮಸ್ಕಾರ", "ನಮಸ್ತೆ", "ಹಲೋ", "ಶುಭೋದಯ", "ಶುಭ ಸಂಜೆ", "ಹೇಗಿದ್ದೀರಿ", "ಹೇಗಿದ್ದೀರಾ", "ನೀವು ಯಾರು", "ನಿಮ್ಮ ಹೆಸರೇನು", "ಏನು ಸಮಾಚಾರ", "ಏನು ಮಾಡಬಲ್ಲೆ",
        "नमस्ते", "नमस्कार", "प्रणाम", "हेलो", "सुप्रभात", "शुभ संध्या", "कैसे हो", "आप कैसे हैं", "आप कौन हैं", "तुम्हारा नाम क्या है", "क्या हाल है", "तुम क्या कर सकते हो",
        "வணக்கம்", "ஹலோ", "காலை வணக்கம்", "எப்படி இருக்கிறீர்கள்", "நீங்கள் யார்", "நலமா", "என்ன செய்ய முடியும்",
        "నమస్కారం", "హలో", "శుభోదయం", "ఎలా ఉన్నారు", "బాగున్నారా", "మీరు ఎవరు", "ఏమి చేయగలరు",
    )
    if any(g in text for g in indic_greetings):
        return TaskCommand.ASK_QUESTION

    # Mail actions in Indic languages
    if any(phrase in text for phrase in (
        "ಇಮೇಲ್ ಸಾರಾಂಶ", "ಮೇಲ್ ಸಾರಾಂಶ", "ಇನ್‌ಬಾಕ್ಸ್ ಸಾರಾಂಶ",
        "ईमेल सारांश", "ईमेल का सारांश", "मेल समरी", "इनबॉक्स सारांश",
        "மின்னஞ்சல் சுருக்கம்", "மெயில் சுருக்கம்",
        "ఇమెయిల్ సారాంశం", "మెయిల్ సారాంశం"
    )):
        return TaskCommand.SUMMARIZE_MAIL

    if any(phrase in text for phrase in (
        "ಇಮೇಲ್ ಓದು", "ಇಮೇಲ್ ನೋಡು", "ಮೇಲ್ ಚೆಕ್", "ಇನ್‌ಬಾಕ್ಸ್ ನೋಡು", "ಮೇಲ್ ಓದು", "ಮೇಲ್ ನೋಡು", "ನನ್ನ ಇಮೇಲ್",
        "ईमेल पढ़ो", "ईमेल देखो", "मेल चेक", "इनबॉक्स देखो", "मेल पढ़ो", "मेल देखो", "मेरा ईमेल",
        "மெயில் படி", "மின்னஞ்சல் படி", "மெயில் பார்", "இன்பாக்ஸ் பார்",
        "ఇమెయిల్ చదువు", "మెయిల్ చూడు", "ఇన్‌బాక్స్ చూడు", "మెయిల్ చదువు", "నా ఇమెయిల్"
    )):
        return TaskCommand.READ_MAIL

    if any(phrase in text for phrase in (
        "ಇಮೇಲ್ ಡ್ರಾಫ್ಟ್", "ಡ್ರಾಫ್ಟ್ ಇಮೇಲ್", "ಮೇಲ್ ಡ್ರಾಫ್ಟ್",
        "ईमेल ड्राफ्ट", "ड्राफ्ट ईमेल", "मेल ड्राफ्ट",
        "மின்னஞ்சல் வரைவு", "டிராஃப்ட்",
        "ఇమెయిల్ డ్రాఫ్ట్", "డ్రాఫ్ట్"
    )):
        return TaskCommand.DRAFT_MAIL

    if any(phrase in text for phrase in (
        "ಇಮೇಲ್ ಕಳುಹಿಸು", "ಇಮೇಲ್ ಕಳಿಸು", "ಮೇಲ್ ಕಳುಹಿಸು", "ಮೇಲ್ ಕಳಿಸು", "ಇಮೇಲ್ ಮಾಡು", "ಇಮೇಲ್ ಬರೆ",
        "ईमेल भेजो", "ईमेल भेजें", "मेल भेजो", "मेल भेजें", "ईमेल करो", "ईमेल लिखो", "ईमेल कर दो",
        "மின்னஞ்சல் அனுப்பு", "மெயில் அனுப்பு", "மின்னஞ்சல் அனுப்புங்கள்",
        "ఇమెయిల్ పంపు", "ఇమెయిల్ పంపించు", "ఇమెయిల్ పంపండి", "మెయిల్ పంపు", "మెయిల్ పంపండి", "ఇమెయిల్ రాయండి",
        "email maadu", "mail maadu", "baredhu kalisu", "mail kalisu",
        "email bhejo", "mail bhejo", "mail karo", "email karo", "mail likho", "email likh do",
        "email anuppu", "mail anuppu", "mail anupu", "mail pannu", "email pannu",
        "email pampu", "mail pampu", "email cheyyi", "mail cheyyi", "mail rayi",
    )) or (
        any(m in text for m in ("ఇమెయిల్", "మెయిల్", "ఈమెయిల్")) and any(v in text for v in ("పంపు", "పంపండి", "పంపించు", "రాయండి"))
    ) or (
        any(m in text for m in ("ಇಮೇಲ್", "ಮೇಲ್")) and any(v in text for v in ("ಕಳುಹಿಸು", "ಕಳುಹಿಸಿ", "ಕಳಿಸು", "ಮಾಡು", "ಬರೆ"))
    ) or (
        any(m in text for m in ("ईमेल", "मेल")) and any(v in text for v in ("भेजो", "भेजें", "करो", "लिखो", "भेजिए"))
    ) or (
        any(m in text for m in ("மின்னஞ்சல்", "மெயில்")) and any(v in text for v in ("அனுப்பு", "அனுப்புங்கள்", "எழுது"))
    ):
        return TaskCommand.SEND_MAIL

    # ── Phase 3: Translation ────────────────────────────────
    if text.startswith(("translate ", "translation of ", "how do you say ")) or (
        any(k in text for k in ("translate to ", "translation to ", "ಅನುವಾದ ಮಾಡು", "ಭಾಷಾಂತರಿಸು", "अनुवाद करो", "மொழிபெயர்", "అనువాదం చేయి"))
        and not any(e in text for e in ("email", "mail", "draft", "ಇಮೇಲ್", "ईमेल", "மின்னஞ்சல்", "ఇమెయిల్"))
    ):
        return TaskCommand.TRANSLATE

    # Screenshot in Indic languages
    if any(w in text for w in ("ಸ್ಕ್ರೀನ್‌ಶಾಟ್", "ಸ್ಕ್ರೀನ್ ಶಾಟ್", "स्क्रीनशॉट", "स्क्रीन शॉट", "ஸ்கிரீன்ஷாட்", "స్క్రీన్‌షాట్")):
        return TaskCommand.SCREENSHOT

    # App Open / Close in Indic languages
    if any(w in text for w in ("ಮುಚ್ಚು", "ಕ್ಲೋಸ್ ಮಾಡು", "बंद करो", "बंद करें", "क्लोज करो", "மூடு", "மூடவும்", "మూసివేయి", "మూసివేయండి")):
        return TaskCommand.CLOSE_APP

    if any(w in text for w in ("ತೆರೆ", "ಓಪನ್ ಮಾಡು", "ಚಾಲೂ ಮಾಡು", "ಪ್ರಾರಂಭಿಸು", "खोलो", "खोलें", "ओपन करो", "चालू करो", "திற", "திறக்கவும்", "தெరువు", "తెరవండి", "ఓపెన్ చేయి")):
        return TaskCommand.OPEN_APP

    # Calculate in Indic languages
    if any(w in text for w in ("ಲೆಕ್ಕ ಮಾಡು", "ಲೆಕ್ಕ ಹಾಕು", "ಕ್ಯಾಲ್ಕುಲೇಟ್", "गणना करो", "हिसाब करो", "கணக்கிடு", "లెక్కించు")):
        return TaskCommand.CALCULATE

    # Web search in Indic languages
    if any(w in text for w in ("ಹುಡುಕು", "ವೆಬ್‌ನಲ್ಲಿ ಹುಡುಕು", "सर्च करो", "खोजो", "वेब पर खोजो", "தேடு", "వెతుకు")):
        return TaskCommand.WEB_SEARCH

    # Question markers in Indic languages
    indic_q_markers = (
        "ಯಾರು", "ಏನು", "ಯಾವಾಗ", "ಎಲ್ಲಿ", "ಯಾಕೆ", "ಹೇಗೆ", "ಯಾವುದು", "ಎಷ್ಟು", "ಹೇಳಿ", "ತಿಳಿಸಿ",
        "क्या", "कौन", "कब", "कहाँ", "कहा", "क्यों", "कैसे", "कितना", "बताओ", "बताइए", "समझाओ",
        "யார்", "என்ன", "எப்போது", "எங்கே", "ஏன்", "எப்படி", "எவ்வளவு", "சொல்லுங்கள்",
        "ఎవరు", "ఏమిటి", "ఏంటి", "ఎప్పుడు", "ఎక్కడ", "ఎందుకు", "ఎలా", "చెప్పండి",
    )
    if any(m in text for m in indic_q_markers):
        return TaskCommand.ASK_QUESTION

    # Pure punctuation or symbols without semantic content is unknown / ambiguous (ML-09)
    if not re.search(r"[\w\u0C80-\u0CFF\u0900-\u097F\u0B80-\u0BFF\u0C00-\u0C7F]", text):
        return TaskCommand.UNKNOWN

    # English greeting & question classification
    greeting_words = ("hi", "hello", "hey", "greetings", "good morning", "good afternoon", "good evening", "namaste", "namaskara", "namaskar", "vanakkam", "namaskaram", "who are you", "what can you do")
    if text in greeting_words or any(text.startswith(w + " ") for w in greeting_words) or text.endswith("?") or text.startswith(("who ", "what ", "when ", "where ", "why ", "how ", "is ", "can ", "could ", "would ", "do ", "does ", "explain ", "tell me ", "define ", "describe ", "give me ", "suggest ", "brainstorm ", "compare ")):
        return TaskCommand.ASK_QUESTION

    # Any Indic script text that hasn't matched a hardware command is conversational
    if re.search(r"[\u0C80-\u0CFF\u0900-\u097F\u0B80-\u0BFF\u0C00-\u0C7F]", text):
        return TaskCommand.ASK_QUESTION

    return TaskCommand.UNKNOWN
