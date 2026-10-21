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
        return json.loads(self.fernet.decrypt(row[0]).decode())

    def list(self, kind: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT id, kind, ciphertext, created_at FROM memories"
        params: tuple[str, ...] = ()
        if kind:
            query += " WHERE kind = ?"
            params = (kind,)
        query += " ORDER BY created_at DESC"
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "id": row[0],
                "kind": row[1],
                "payload": json.loads(self.fernet.decrypt(row[2]).decode()),
                "createdAt": row[3],
            }
            for row in rows
        ]
