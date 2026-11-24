from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.core.contracts import (
    Task,
    TaskStatus,
    TaskCommand,
    RiskLevel,
    LanguageCode,
    AuditEvent,
    ActionAttempt,
    ActionAttemptStatus,
    canonical_status,
    TERMINAL_STATUSES,
    ConcurrencyError,
    MailDeliveryStatus,
)

SENSITIVE_KEY_PATTERNS = {
    "secret", "api_key", "apikey", "password", "token", "session",
    "authorization", "auth", "private_key", "credential", "full_body",
}


def is_sensitive_key(key: Any) -> bool:
    k = str(key).lower().replace("-", "_").strip()
    return any(p in k for p in SENSITIVE_KEY_PATTERNS) or k in {"body", "mail_body"}


def recursive_sanitize(val: Any, depth: int = 0) -> Any:
    if depth > 10:
        return "[MAX_DEPTH]"
    if isinstance(val, dict):
        sanitized = {}
        for k, v in val.items():
            if is_sensitive_key(k):
                sanitized[str(k)] = "[REDACTED]"
            else:
                sanitized[str(k)] = recursive_sanitize(v, depth + 1)
        return sanitized
    elif isinstance(val, (list, tuple, set)):
        return [recursive_sanitize(item, depth + 1) for item in val]
    elif isinstance(val, (str, int, float, bool)) or val is None:
        return val
    else:
        if hasattr(val, "to_dict") and callable(val.to_dict):
            return recursive_sanitize(val.to_dict(), depth + 1)
        return str(val)


class MigrationError(RuntimeError):
    """Raised when database migration fails."""
    pass


class TaskStore:
    """
    Authoritative Relational SQLite Persistence for Cortex Agent.
    Enforces:
    - Versioned, atomic migrations via schema_migrations
    - Foreign key constraints (PRAGMA foreign_keys = ON)
    - WAL journaling for high concurrency
    - Relational entities: tasks, task_steps, approvals, action_attempts, audit_events, artifacts
    - Preservation of existing encrypted memories table
    - Short, parameterized transactions
    """

    CURRENT_SCHEMA_VERSION = 3

    def __init__(self, db_path: str = "cortex-memory.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = 0
        self._init_connection_and_migrate()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def _connect(self) -> sqlite3.Connection:
        """Alias for _get_connection for test compatibility."""
        return self._get_connection()

    def clear_mail_send_attempts(self) -> None:
        """Clears all mail send attempts (used by test cleanup)."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM mail_send_attempts;")
            conn.commit()

    def _init_connection_and_migrate(self) -> None:
        with self._get_connection() as conn:
            # 1. Ensure migrations tracking table exists
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            # 2. Check current version
            cur = conn.execute("SELECT MAX(version) FROM schema_migrations;")
            row = cur.fetchone()
            current_ver = row[0] if (row and row[0] is not None) else 0

            # 3. Apply migrations up to CURRENT_SCHEMA_VERSION
            if current_ver < 1:
                self._apply_migration_1(conn)
            if current_ver < 2:
                self._apply_migration_2(conn)
            if current_ver < 3:
                self._apply_migration_3(conn)

            # Ensure capability-level durable WhatsApp attempts table exists
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS whatsapp_send_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    body TEXT,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    initiated_at TEXT NOT NULL,
                    completed_at TEXT,
                    observed_outcome TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    error_message TEXT,
                    metadata_json TEXT
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_whatsapp_attempts_task_id ON whatsapp_send_attempts(task_id);")

            # Ensure durable Mail send attempts table exists
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mail_send_attempts (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    approval_id TEXT,
                    payload_hash TEXT NOT NULL,
                    recipient_hash TEXT NOT NULL,
                    subject_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    verified_at TEXT,
                    provider_message_id TEXT,
                    verification_details TEXT
                );
                """
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_mail_attempts_payload ON mail_send_attempts(payload_hash);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mail_attempts_task_id ON mail_send_attempts(task_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mail_attempts_status ON mail_send_attempts(status);")

    def _apply_migration_1(self, conn: sqlite3.Connection) -> None:
        """Migration 1: Core Relational Task, Approval, Attempt, and Audit tables."""
        try:
            # Tasks table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    intent TEXT NOT NULL,
                    command TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    requires_approval INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    state_version INTEGER NOT NULL DEFAULT 1,
                    cancellation_requested INTEGER NOT NULL DEFAULT 0,
                    approval_hash TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    language TEXT NOT NULL DEFAULT 'en',
                    steps_json TEXT NOT NULL DEFAULT '[]',
                    params_json TEXT NOT NULL DEFAULT '{}'
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);")

            # Task Steps table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_steps (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    step_order INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_steps_task_id ON task_steps(task_id);")

            # Approvals table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    metadata_json TEXT
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_task_id ON approvals(task_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_hash ON approvals(payload_hash);")

            # Action Attempts table (idempotency, side-effect intent logging)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS action_attempts (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    step_id TEXT,
                    action_type TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    evidence_json TEXT
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_action_attempts_task_id ON action_attempts(task_id);")

            # Audit Events table (structured metadata-first logging)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    task_id TEXT,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_task_id ON audit_events(task_id);")

            # Artifacts table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                    artifact_type TEXT NOT NULL,
                    storage_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    integrity_hash TEXT
                );
                """
            )

            # Record migration version
            conn.execute("INSERT INTO schema_migrations (version) VALUES (1);")
        except Exception as e:
            raise MigrationError(f"Failed to apply migration 1: {e}") from e

    def _apply_migration_2(self, conn: sqlite3.Connection) -> None:
        """Migration 2: Screen Observations and Recovery Checkpoints for Desktop Operator."""
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS screen_observations (
                    context_id TEXT PRIMARY KEY,
                    task_id TEXT,
                    app_name TEXT NOT NULL,
                    window_title TEXT,
                    elements_count INTEGER NOT NULL DEFAULT 0,
                    modal_dialog INTEGER NOT NULL DEFAULT 0,
                    screenshot_path TEXT,
                    facts_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_screen_obs_task ON screen_observations(task_id);")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recovery_checkpoints (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    step_index INTEGER NOT NULL,
                    state_hash TEXT NOT NULL,
                    context_id TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_recovery_checkpoints_task ON recovery_checkpoints(task_id);")
            conn.execute("INSERT INTO schema_migrations (version) VALUES (2);")
        except Exception as e:
            raise MigrationError(f"Failed to apply migration 2: {e}") from e

    def _apply_migration_3(self, conn: sqlite3.Connection) -> None:
        """Migration 3: Mail Send Attempts table for persistent duplicate-send protection (Phase P7.2)."""
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mail_send_attempts (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    approval_id TEXT,
                    payload_hash TEXT NOT NULL,
                    recipient_hash TEXT NOT NULL,
                    subject_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    verified_at TEXT,
                    provider_message_id TEXT,
                    verification_details TEXT
                );
                """
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_mail_attempts_payload ON mail_send_attempts(payload_hash);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mail_attempts_task_id ON mail_send_attempts(task_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mail_attempts_status ON mail_send_attempts(status);")
            conn.execute("INSERT INTO schema_migrations (version) VALUES (3);")
        except Exception as e:
            raise MigrationError(f"Failed to apply migration 3: {e}") from e

    def backup(self, destination: Path | None = None) -> Path:
        """Create a point-in-time SQLite backup safely."""
        dest = destination or self.db_path.with_suffix(f".backup-{int(datetime.now().timestamp())}.sqlite3")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as src_conn:
            with sqlite3.connect(str(dest)) as dst_conn:
                src_conn.backup(dst_conn)
        return dest

    # ── Task CRUD ─────────────────────────────────────────────────────────────

    def save_task(self, task: Task, expected_version: int | None = None) -> None:
        """
        Persist or update a task with atomic SQLite optimistic state versioning.
        Rejects stale writes, equal-version conflicts, and transitions violating expected_version.
        """
        with self._get_connection() as conn:
            params_json = json.dumps(task.params, sort_keys=True)
            steps_json = json.dumps(task.steps)
            cmd_val = task.command.value if hasattr(task.command, "value") else str(task.command)
            risk_val = task.risk_level.value if hasattr(task.risk_level, "value") else str(task.risk_level)
            lang_val = task.language.value if hasattr(task.language, "value") else str(task.language)

            cur = conn.execute(
                """
                INSERT INTO tasks (
                    id, intent, command, risk_level, requires_approval, status,
                    state_version, cancellation_requested, approval_hash,
                    created_at, updated_at, result, error, language, steps_json, params_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    intent = excluded.intent,
                    command = excluded.command,
                    risk_level = excluded.risk_level,
                    requires_approval = excluded.requires_approval,
                    status = excluded.status,
                    state_version = excluded.state_version,
                    cancellation_requested = excluded.cancellation_requested,
                    approval_hash = excluded.approval_hash,
                    updated_at = excluded.updated_at,
                    result = excluded.result,
                    error = excluded.error,
                    language = excluded.language,
                    steps_json = excluded.steps_json,
                    params_json = excluded.params_json
                WHERE (
                    (? IS NOT NULL AND tasks.state_version = ? AND excluded.state_version > tasks.state_version)
                    OR
                    (? IS NULL AND tasks.state_version < excluded.state_version)
                    OR
                    (? IS NULL AND tasks.state_version = excluded.state_version AND tasks.intent = excluded.intent AND tasks.status = excluded.status)
                );
                """,
                (
                    task.id,
                    task.intent,
                    cmd_val,
                    risk_val,
                    1 if task.requires_approval else 0,
                    task.status.value,
                    task.state_version,
                    1 if task.cancellation_requested else 0,
                    task.approval_hash or task.params.get("approval_hash"),
                    task.created_at,
                    task.updated_at,
                    str(task.result) if task.result is not None else None,
                    str(task.error) if task.error is not None else None,
                    lang_val,
                    steps_json,
                    params_json,
                    expected_version,
                    expected_version,
                    expected_version,
                    expected_version,
                ),
            )
            if cur.rowcount == 0:
                row = conn.execute("SELECT state_version FROM tasks WHERE id = ?", (task.id,)).fetchone()
                persisted_ver = row["state_version"] if row else None
                raise ConcurrencyError(
                    f"Concurrency conflict: cannot save task '{task.id}' at state_version {task.state_version} "
                    f"(persisted version in database is {persisted_ver}, expected_version was {expected_version})"
                )

    def get_task(self, task_id: str) -> Task | None:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_task(row)

    def list_active_tasks(self) -> list[Task]:
        """Fetch all incomplete/active tasks for startup recovery and inspection."""
        with self._get_connection() as conn:
            terminal_vals = [s.value for s in TERMINAL_STATUSES]
            placeholders = ",".join("?" for _ in terminal_vals)
            cur = conn.execute(
                f"SELECT * FROM tasks WHERE status NOT IN ({placeholders}) ORDER BY created_at ASC;",
                terminal_vals,
            )
            return [self._row_to_task(r) for r in cur.fetchall()]

    def list_all_tasks(self, limit: int = 200) -> list[Task]:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,))
            return [self._row_to_task(r) for r in cur.fetchall()]

    def delete_task(self, task_id: str) -> bool:
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return cur.rowcount > 0

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        params = json.loads(row["params_json"]) if row["params_json"] else {}
        steps = json.loads(row["steps_json"]) if row["steps_json"] else []
        task = Task(
            id=row["id"],
            intent=row["intent"],
            command=TaskCommand(row["command"]) if row["command"] in TaskCommand._value2member_map_ else TaskCommand.UNKNOWN,
            risk_level=RiskLevel(row["risk_level"]) if row["risk_level"] in RiskLevel._value2member_map_ else RiskLevel.LOW,
            requires_approval=bool(row["requires_approval"]),
            status=canonical_status(row["status"]),
            steps=steps,
            result=row["result"],
            error=row["error"],
            params=params,
            language=LanguageCode.from_string(row["language"]),
            state_version=row["state_version"],
            cancellation_requested=bool(row["cancellation_requested"]),
            approval_hash=row["approval_hash"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        return task

    # ── Action Attempts (Pre-execution intent logging) ─────────────────────────

    def record_action_attempt(self, attempt: ActionAttempt) -> None:
        """Persist an action attempt BEFORE initiating an external side-effect."""
        with self._get_connection() as conn:
            evidence_json = json.dumps(attempt.evidence or {}, default=str)
            conn.execute(
                """
                INSERT INTO action_attempts (
                    id, task_id, step_id, action_type, payload_hash, status, started_at, completed_at, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    attempt.id,
                    attempt.task_id,
                    attempt.step_id,
                    attempt.action_type,
                    attempt.payload_hash,
                    attempt.status.value,
                    attempt.started_at,
                    attempt.completed_at,
                    evidence_json,
                ),
            )

    def update_action_attempt(
        self,
        attempt_id: str,
        status: ActionAttemptStatus | str,
        evidence: dict[str, Any] | None = None,
        completed_at: str | None = None,
    ) -> None:
        stat_val = status.value if hasattr(status, "value") else str(status)
        now_iso = completed_at or datetime.now(timezone.utc).isoformat()
        evidence_json = json.dumps(evidence or {}, default=str)
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE action_attempts
                SET status = ?, completed_at = ?, evidence_json = ?
                WHERE id = ?;
                """,
                (stat_val, now_iso, evidence_json, attempt_id),
            )

    def get_action_attempts(self, task_id: str) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM action_attempts WHERE task_id = ? ORDER BY started_at ASC;",
                (task_id,),
            )
            results = []
            for r in cur.fetchall():
                results.append({
                    "id": r["id"],
                    "taskId": r["task_id"],
                    "stepId": r["step_id"],
                    "actionType": r["action_type"],
                    "payloadHash": r["payload_hash"],
                    "status": r["status"],
                    "startedAt": r["started_at"],
                    "completedAt": r["completed_at"],
                    "evidence": json.loads(r["evidence_json"]) if r["evidence_json"] else {},
                })
            return results

    # ── WhatsApp Capability Send Attempts (Pre-execution durable attempt logging) ──

    def record_whatsapp_send_attempt(self, attempt: Any) -> None:
        """Persist a capability-level WhatsApp send attempt before external actions."""
        with self._get_connection() as conn:
            metadata_json = json.dumps(getattr(attempt, "metadata", {}) or {}, default=str)
            conn.execute(
                """
                INSERT OR REPLACE INTO whatsapp_send_attempts (
                    attempt_id, task_id, recipient, phone, body, payload_hash, status,
                    initiated_at, completed_at, observed_outcome, retry_count, error_message, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    attempt.attempt_id,
                    getattr(attempt, "task_id", ""),
                    getattr(attempt, "recipient", ""),
                    getattr(attempt, "phone", ""),
                    getattr(attempt, "body", ""),
                    getattr(attempt, "payload_hash", ""),
                    getattr(attempt, "status", "created"),
                    getattr(attempt, "initiated_at", datetime.now(timezone.utc).isoformat()),
                    getattr(attempt, "completed_at", None),
                    getattr(attempt, "observed_outcome", "pending"),
                    getattr(attempt, "retry_count", 0),
                    getattr(attempt, "error_message", ""),
                    metadata_json,
                ),
            )

    def update_whatsapp_send_attempt(
        self,
        attempt_id: str,
        status: str,
        observed_outcome: str,
        error_message: str = "",
        completed_at: str | None = None,
    ) -> None:
        now_iso = completed_at or datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE whatsapp_send_attempts
                SET status = ?, observed_outcome = ?, error_message = ?, completed_at = ?
                WHERE attempt_id = ?;
                """,
                (status, observed_outcome, error_message, now_iso, attempt_id),
            )

    def get_whatsapp_send_attempt(self, attempt_id: str) -> dict[str, Any] | None:
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM whatsapp_send_attempts WHERE attempt_id = ?;",
                (attempt_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "attemptId": row["attempt_id"],
                "taskId": row["task_id"],
                "recipient": row["recipient"],
                "phone": row["phone"],
                "body": row["body"],
                "payloadHash": row["payload_hash"],
                "status": row["status"],
                "initiatedAt": row["initiated_at"],
                "completedAt": row["completed_at"],
                "observedOutcome": row["observed_outcome"],
                "retryCount": row["retry_count"],
                "errorMessage": row["error_message"],
                "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            }

    def list_whatsapp_send_attempts(self, task_id: str | None = None) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            if task_id:
                cur = conn.execute(
                    "SELECT * FROM whatsapp_send_attempts WHERE task_id = ? ORDER BY initiated_at ASC;",
                    (task_id,),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM whatsapp_send_attempts ORDER BY initiated_at ASC;",
                )
            results = []
            for row in cur.fetchall():
                results.append({
                    "attemptId": row["attempt_id"],
                    "taskId": row["task_id"],
                    "recipient": row["recipient"],
                    "phone": row["phone"],
                    "body": row["body"],
                    "payloadHash": row["payload_hash"],
                    "status": row["status"],
                    "initiatedAt": row["initiated_at"],
                    "completedAt": row["completed_at"],
                    "observedOutcome": row["observed_outcome"],
                    "retryCount": row["retry_count"],
                    "errorMessage": row["error_message"],
                    "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
                })
            return results

    # ── Mail Send Attempts (Durable SQLite Idempotency — Phase P7.2) ──────────

    def record_mail_send_attempt(
        self,
        task_id: str,
        payload_hash: str,
        recipient: str,
        subject: str,
        approval_id: str | None = None,
        status: str = MailDeliveryStatus.NOT_ATTEMPTED.value,
        verification_details: str | None = None,
    ) -> str:
        """
        Persists a mail send attempt before invocation.
        Binds to exact approved payload hash, preventing duplicate dispatch across restarts.
        """
        import hashlib
        attempt_id = str(uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        rec_hash = hashlib.sha256(recipient.lower().strip().encode("utf-8")).hexdigest()
        subj_hash = hashlib.sha256(subject.strip().encode("utf-8")).hexdigest()

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO mail_send_attempts (
                    id, task_id, approval_id, payload_hash, recipient_hash, subject_hash,
                    status, attempt_count, created_at, updated_at, verification_details
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(payload_hash) DO UPDATE SET
                    attempt_count = mail_send_attempts.attempt_count + 1,
                    updated_at = excluded.updated_at,
                    task_id = excluded.task_id,
                    approval_id = COALESCE(excluded.approval_id, mail_send_attempts.approval_id),
                    verification_details = COALESCE(excluded.verification_details, mail_send_attempts.verification_details);
                """,
                (attempt_id, task_id, approval_id, payload_hash, rec_hash, subj_hash, status, now_iso, now_iso, verification_details),
            )
        return attempt_id

    def update_mail_send_attempt(
        self,
        attempt_id_or_hash: str,
        status: str,
        provider_message_id: str | None = None,
        verification_details: str | None = None,
        verified_at: str | None = None,
    ) -> None:
        """Atomically updates the delivery lifecycle status of a mail send attempt."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE mail_send_attempts
                SET status = ?,
                    provider_message_id = COALESCE(?, provider_message_id),
                    verification_details = COALESCE(?, verification_details),
                    verified_at = COALESCE(?, verified_at),
                    updated_at = ?
                WHERE id = ? OR payload_hash = ?;
                """,
                (status, provider_message_id, verification_details, verified_at, now_iso, attempt_id_or_hash, attempt_id_or_hash),
            )

    def get_mail_send_attempt_by_hash(self, payload_hash: str) -> dict[str, Any] | None:
        """Retrieves a durable send attempt by its cryptographic payload hash."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM mail_send_attempts WHERE payload_hash = ?;",
                (payload_hash,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "taskId": row["task_id"],
                "approvalId": row["approval_id"],
                "payloadHash": row["payload_hash"],
                "recipientHash": row["recipient_hash"],
                "subjectHash": row["subject_hash"],
                "status": row["status"],
                "attemptCount": row["attempt_count"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
                "verifiedAt": row["verified_at"],
                "providerMessageId": row["provider_message_id"],
                "verificationDetails": row["verification_details"],
            }

    def get_mail_send_attempt(self, attempt_id: str) -> dict[str, Any] | None:
        """Retrieves a durable send attempt by primary key."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM mail_send_attempts WHERE id = ?;",
                (attempt_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "taskId": row["task_id"],
                "approvalId": row["approval_id"],
                "payloadHash": row["payload_hash"],
                "recipientHash": row["recipient_hash"],
                "subjectHash": row["subject_hash"],
                "status": row["status"],
                "attemptCount": row["attempt_count"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
                "verifiedAt": row["verified_at"],
                "providerMessageId": row["provider_message_id"],
                "verificationDetails": row["verification_details"],
            }

    def list_mail_send_attempts(self, task_id: str | None = None) -> list[dict[str, Any]]:
        """Lists mail send attempts, optionally filtered by task_id."""
        with self._get_connection() as conn:
            if task_id:
                cur = conn.execute(
                    "SELECT * FROM mail_send_attempts WHERE task_id = ? ORDER BY created_at ASC;",
                    (task_id,),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM mail_send_attempts ORDER BY created_at ASC;",
                )
            results = []
            for row in cur.fetchall():
                results.append({
                    "id": row["id"],
                    "taskId": row["task_id"],
                    "approvalId": row["approval_id"],
                    "payloadHash": row["payload_hash"],
                    "recipientHash": row["recipient_hash"],
                    "subjectHash": row["subject_hash"],
                    "status": row["status"],
                    "attemptCount": row["attempt_count"],
                    "createdAt": row["created_at"],
                    "updatedAt": row["updated_at"],
                    "verifiedAt": row["verified_at"],
                    "providerMessageId": row["provider_message_id"],
                    "verificationDetails": row["verification_details"],
                })
            return results

    def check_mail_send_duplicate(self, payload_hash: str) -> tuple[bool, str, dict[str, Any] | None]:
        """
        Inspects durable SQLite state to prevent duplicate sends across restarts.
        Returns: (is_duplicate: bool, reason: str, existing_attempt: dict | None)
        """
        attempt = self.get_mail_send_attempt_by_hash(payload_hash)
        if not attempt:
            return False, "", None

        status = attempt.get("status")
        if status == MailDeliveryStatus.SENT_VERIFIED.value:
            return True, "Duplicate send prevented: this exact email has already been sent and verified in the Sent mailbox.", attempt
        if status in (MailDeliveryStatus.SEND_ATTEMPTED.value, MailDeliveryStatus.DELIVERY_UNCONFIRMED.value):
            return True, "Duplicate send prevented: a prior send attempt is in-flight or unconfirmed. Retries without verification are prohibited.", attempt
        if status == MailDeliveryStatus.BLOCKED.value:
            return True, "Duplicate send prevented: send attempt was previously blocked by safety policy.", attempt

        return False, "", attempt

    def reserve_mail_send_attempt(
        self,
        task_id: str,
        payload_hash: str,
        recipient: str,
        subject: str,
        approval_id: str | None = None,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """
        Atomically inspects and reserves a mail send attempt within a single transaction.
        Eliminates check-then-act race conditions under concurrent requests.
        Returns: (reserved: bool, reason: str, attempt: dict | None)
        """
        import hashlib
        rec_hash = hashlib.sha256(recipient.lower().strip().encode("utf-8")).hexdigest()
        subj_hash = hashlib.sha256(subject.strip().encode("utf-8")).hexdigest()
        now_iso = datetime.now(timezone.utc).isoformat()
        attempt_id = str(uuid4())

        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM mail_send_attempts WHERE payload_hash = ?;", (payload_hash,))
            row = cur.fetchone()
            if row:
                attempt = {
                    "id": row["id"],
                    "taskId": row["task_id"],
                    "approvalId": row["approval_id"],
                    "payloadHash": row["payload_hash"],
                    "recipientHash": row["recipient_hash"],
                    "subjectHash": row["subject_hash"],
                    "status": row["status"],
                    "attemptCount": row["attempt_count"],
                    "createdAt": row["created_at"],
                    "updatedAt": row["updated_at"],
                    "verifiedAt": row["verified_at"],
                    "providerMessageId": row["provider_message_id"],
                    "verificationDetails": row["verification_details"],
                }
                status = row["status"]
                if status == MailDeliveryStatus.SENT_VERIFIED.value:
                    return False, "Duplicate send prevented: this exact email has already been sent and verified in the Sent mailbox.", attempt
                if status in (MailDeliveryStatus.SEND_ATTEMPTED.value, MailDeliveryStatus.DELIVERY_UNCONFIRMED.value):
                    return False, "Duplicate send prevented: a prior send attempt is in-flight or unconfirmed. Retries without verification are prohibited.", attempt
                if status == MailDeliveryStatus.BLOCKED.value:
                    return False, "Duplicate send prevented: send attempt was previously blocked by safety policy.", attempt
                if status == MailDeliveryStatus.NOT_ATTEMPTED.value:
                    conn.execute(
                        "UPDATE mail_send_attempts SET status = ?, attempt_count = attempt_count + 1, updated_at = ?, task_id = ?, approval_id = COALESCE(?, approval_id) WHERE id = ?;",
                        (MailDeliveryStatus.SEND_ATTEMPTED.value, now_iso, task_id, approval_id, row["id"]),
                    )
                    attempt["status"] = MailDeliveryStatus.SEND_ATTEMPTED.value
                    attempt["attemptCount"] += 1
                    attempt["updatedAt"] = now_iso
                    return True, "Send attempt successfully reserved.", attempt
                return False, f"Send attempt in state '{status}' cannot be reserved.", attempt

            try:
                conn.execute(
                    """
                    INSERT INTO mail_send_attempts (
                        id, task_id, approval_id, payload_hash, recipient_hash, subject_hash,
                        status, attempt_count, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?);
                    """,
                    (attempt_id, task_id, approval_id, payload_hash, rec_hash, subj_hash, MailDeliveryStatus.SEND_ATTEMPTED.value, now_iso, now_iso),
                )
                new_attempt = {
                    "id": attempt_id,
                    "taskId": task_id,
                    "approvalId": approval_id,
                    "payloadHash": payload_hash,
                    "recipientHash": rec_hash,
                    "subjectHash": subj_hash,
                    "status": MailDeliveryStatus.SEND_ATTEMPTED.value,
                    "attemptCount": 1,
                    "createdAt": now_iso,
                    "updatedAt": now_iso,
                    "verifiedAt": None,
                    "providerMessageId": None,
                    "verificationDetails": None,
                }
                return True, "Send attempt successfully reserved.", new_attempt
            except Exception:
                return self.reserve_mail_send_attempt(task_id, payload_hash, recipient, subject, approval_id)

    def reauthorize_mail_send_attempt(
        self,
        payload_hash: str,
        reason: str,
        authorized_by: str = "user",
    ) -> tuple[bool, str]:
        """
        Reauthorizes a previously BLOCKED send attempt, transitioning it back to NOT_ATTEMPTED
        with an auditable event record.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        task_id = None
        attempt_id = None
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM mail_send_attempts WHERE payload_hash = ?;", (payload_hash,))
            row = cur.fetchone()
            if not row:
                return False, "No send attempt found matching payload hash."
            if row["status"] != MailDeliveryStatus.BLOCKED.value:
                return False, f"Attempt is in status '{row['status']}', not BLOCKED. Only BLOCKED attempts can be reauthorized."

            task_id = row["task_id"]
            attempt_id = row["id"]
            conn.execute(
                "UPDATE mail_send_attempts SET status = ?, updated_at = ? WHERE id = ?;",
                (MailDeliveryStatus.NOT_ATTEMPTED.value, now_iso, attempt_id),
            )

        self.record_audit_event(
            "mail_send_reauthorized",
            task_id=task_id,
            metadata={
                "payload_hash": payload_hash,
                "reason": reason,
                "authorized_by": authorized_by,
                "attempt_id": attempt_id,
            },
        )
        return True, f"Send attempt successfully reauthorized: {reason}"

    # ── Approvals (Cryptographic 15-minute binding) ────────────────────────────

    def record_approval(
        self,
        task_id: str,
        payload_hash: str,
        expires_in_seconds: int = 900,  # 15 minutes
        metadata: dict[str, Any] | None = None,
    ) -> str:
        approval_id = str(uuid4())
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=expires_in_seconds)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO approvals (
                    id, task_id, payload_hash, status, created_at, expires_at, metadata_json
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?);
                """,
                (
                    approval_id,
                    task_id,
                    payload_hash,
                    now.isoformat(),
                    expires.isoformat(),
                    json.dumps(metadata or {}),
                ),
            )
        return approval_id

    def consume_approval(self, task_id: str, payload_hash: str) -> tuple[bool, str]:
        """
        Atomically check and consume approval.
        Returns: (success: bool, reason: str)
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT id, status, expires_at, payload_hash
                FROM approvals
                WHERE task_id = ? AND payload_hash = ?
                ORDER BY created_at DESC LIMIT 1;
                """,
                (task_id, payload_hash),
            )
            row = cur.fetchone()
            if not row:
                return False, "No approval record found matching payload hash."
            if row["status"] == "consumed":
                return False, "Approval already consumed (replay detected)."
            if row["status"] != "pending":
                return False, f"Approval is not active (status: {row['status']})."
            if row["expires_at"] < now_iso:
                conn.execute("UPDATE approvals SET status = 'expired' WHERE id = ?;", (row["id"],))
                return False, "Approval has expired."

            # Atomically mark consumed
            conn.execute(
                "UPDATE approvals SET status = 'consumed', consumed_at = ? WHERE id = ?;",
                (now_iso, row["id"]),
            )
            return True, "Approval consumed successfully."

    # ── Structured Audit Events (Metadata-first, no credentials) ──────────────

    def record_audit_event(
        self,
        event_type: str,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Record a structured audit event. Sanitizes any passwords, keys, or raw email bodies.
        """
        event_id = str(uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        self._seq += 1

        safe_metadata = recursive_sanitize(metadata or {})

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (id, task_id, event_type, timestamp, seq, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (event_id, task_id, event_type, now_iso, self._seq, json.dumps(safe_metadata)),
            )
        return event_id

    def get_audit_events(self, task_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            if task_id:
                cur = conn.execute(
                    "SELECT * FROM audit_events WHERE task_id = ? ORDER BY seq ASC LIMIT ?;",
                    (task_id, limit),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM audit_events ORDER BY seq DESC LIMIT ?;",
                    (limit,),
                )
            results = []
            for r in cur.fetchall():
                results.append({
                    "id": r["id"],
                    "taskId": r["task_id"],
                    "eventType": r["event_type"],
                    "timestamp": r["timestamp"],
                    "seq": r["seq"],
                    "metadata": json.loads(r["metadata_json"]) if r["metadata_json"] else {},
                })
            return results

    # ── Screen Observations & Recovery Checkpoints (Milestone 8) ────────────

    def record_screen_observation(
        self,
        context_id: str,
        task_id: str | None,
        app_name: str,
        window_title: str | None,
        elements_count: int,
        modal_dialog: bool,
        screenshot_path: str | None,
        facts: list[dict[str, Any]] | None = None,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO screen_observations (
                    context_id, task_id, app_name, window_title,
                    elements_count, modal_dialog, screenshot_path, facts_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    context_id,
                    task_id,
                    app_name,
                    window_title,
                    elements_count,
                    1 if modal_dialog else 0,
                    screenshot_path,
                    json.dumps(facts or []),
                    now_iso,
                ),
            )

    def get_screen_observation(self, context_id: str) -> dict[str, Any] | None:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM screen_observations WHERE context_id = ?;", (context_id,))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "contextId": row["context_id"],
                "taskId": row["task_id"],
                "appName": row["app_name"],
                "windowTitle": row["window_title"],
                "elementsCount": row["elements_count"],
                "modalDialog": bool(row["modal_dialog"]),
                "screenshotPath": row["screenshot_path"],
                "facts": json.loads(row["facts_json"]) if row["facts_json"] else [],
                "createdAt": row["created_at"],
            }

    def record_recovery_checkpoint(
        self,
        task_id: str,
        step_index: int,
        state_hash: str,
        context_id: str | None = None,
        status: str = "in_progress",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        checkpoint_id = str(uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO recovery_checkpoints (
                    id, task_id, step_index, state_hash, context_id, status, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    checkpoint_id,
                    task_id,
                    step_index,
                    state_hash,
                    context_id,
                    status,
                    now_iso,
                    json.dumps(metadata or {}),
                ),
            )
        return checkpoint_id

    def get_latest_checkpoint(self, task_id: str) -> dict[str, Any] | None:
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM recovery_checkpoints WHERE task_id = ? ORDER BY created_at DESC LIMIT 1;",
                (task_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "taskId": row["task_id"],
                "stepIndex": row["step_index"],
                "stateHash": row["state_hash"],
                "contextId": row["context_id"],
                "status": row["status"],
                "createdAt": row["created_at"],
                "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            }
