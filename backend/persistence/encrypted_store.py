from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet


class EncryptedMemoryStore:
    def __init__(self, db_path: str = "cortex-memory.sqlite3", key: bytes | None = None) -> None:
        self.db_path = Path(db_path)
        self.key = key or os.getenv("CORTEX_MEMORY_KEY", "").encode() or Fernet.generate_key()
        self.fernet = Fernet(self.key)
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    ciphertext BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def put(self, memory_id: str, kind: str, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, sort_keys=True).encode()
        ciphertext = self.fernet.encrypt(raw)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO memories (id, kind, ciphertext) VALUES (?, ?, ?)",
                (memory_id, kind, ciphertext),
            )

    def get(self, memory_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT ciphertext FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if not row:
            return None
        try:
            return json.loads(self.fernet.decrypt(row[0]).decode())
        except Exception:
            return None

    def update(self, memory_id: str, payload: dict[str, Any]) -> bool:
        """Update payload of an existing memory."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT kind FROM memories WHERE id = ?", (memory_id,)).fetchone()
            if not row:
                return False
            raw = json.dumps(payload, sort_keys=True).encode()
            ciphertext = self.fernet.encrypt(raw)
            conn.execute(
                "UPDATE memories SET ciphertext = ? WHERE id = ?",
                (ciphertext, memory_id),
            )
            return True

    def delete(self, memory_id: str) -> bool:
        """Delete an individual memory by id."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            return cur.rowcount > 0

    def clear(self, kind: str | None = None) -> int:
        """Clear memories, optionally filtered by kind."""
        with sqlite3.connect(self.db_path) as conn:
            if kind:
                cur = conn.execute("DELETE FROM memories WHERE kind = ?", (kind,))
            else:
                cur = conn.execute("DELETE FROM memories")
            return cur.rowcount

    def list(self, kind: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT id, kind, ciphertext, created_at FROM memories"
        params: tuple[str, ...] = ()
        if kind:
            query += " WHERE kind = ?"
            params = (kind,)
        query += " ORDER BY created_at DESC"
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
        items = []
        for row in rows:
            try:
                decrypted = json.loads(self.fernet.decrypt(row[2]).decode())
                items.append({
                    "id": row[0],
                    "kind": row[1],
                    "payload": decrypted,
                    "createdAt": row[3],
                })
            except Exception:
                continue
        return items
