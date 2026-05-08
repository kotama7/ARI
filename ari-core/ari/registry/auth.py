"""Bearer-token auth backed by sqlite.

Tokens are stored hashed (sha256). The plaintext is shown only once at
``ari registry token issue`` time.

Schema:
    CREATE TABLE tokens(
        id TEXT PRIMARY KEY,
        token_hash TEXT NOT NULL UNIQUE,
        user TEXT NOT NULL,
        created_at TEXT NOT NULL,
        revoked_at TEXT
    );
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TokenStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tokens(
                    id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    user TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT
                )
                """
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def issue(self, user: str) -> tuple[str, str]:
        """Return (id, plaintext_token). Plaintext is NOT stored."""
        plaintext = "ari_" + secrets.token_urlsafe(32)
        h = _hash(plaintext)
        token_id = secrets.token_hex(8)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO tokens(id, token_hash, user, created_at) VALUES (?, ?, ?, ?)",
                (token_id, h, user, _now()),
            )
        return token_id, plaintext

    def revoke(self, token_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (_now(), token_id),
            )
            return cur.rowcount > 0

    def authenticate(self, plaintext_token: str) -> Optional[str]:
        """Return the username for a valid (non-revoked) token, or None."""
        if not plaintext_token:
            return None
        h = _hash(plaintext_token)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT user FROM tokens WHERE token_hash=? AND revoked_at IS NULL",
                (h,),
            ).fetchone()
        return row[0] if row else None

    def list_users(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, user, created_at, revoked_at FROM tokens ORDER BY created_at DESC"
            ).fetchall()
        return [
            {"id": r[0], "user": r[1], "created_at": r[2], "revoked_at": r[3]}
            for r in rows
        ]
