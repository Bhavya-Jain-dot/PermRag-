"""SQLite persistence for users, managed roles, and the query audit trail."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .auth import hash_password, verify_password


DEFAULT_ROLES = ("sales", "engineering", "hr", "finance", "admin")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        connection = self.connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS roles (
                    name TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    username TEXT NOT NULL,
                    role TEXT NOT NULL,
                    query TEXT NOT NULL,
                    retrieved_chunk_ids TEXT NOT NULL,
                    retrieved_sources TEXT NOT NULL,
                    restricted_chunks_excluded INTEGER NOT NULL,
                    answer TEXT NOT NULL,
                    flagged INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            for role in DEFAULT_ROLES:
                connection.execute("INSERT OR IGNORE INTO roles (name, created_at) VALUES (?, ?)", (role, self._now()))
                connection.execute(
                    "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                    (role, hash_password(role), role),
                )
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def role_names(self) -> set[str]:
        connection = self.connect()
        try:
            return {str(row["name"]) for row in connection.execute("SELECT name FROM roles ORDER BY name")}
        finally:
            connection.close()

    def roles(self) -> list[str]:
        return sorted(self.role_names())

    def create_role(self, role: str) -> None:
        connection = self.connect()
        try:
            connection.execute("INSERT INTO roles (name, created_at) VALUES (?, ?)", (role, self._now()))
            connection.commit()
        finally:
            connection.close()

    def delete_role(self, role: str) -> None:
        connection = self.connect()
        try:
            in_use = connection.execute("SELECT 1 FROM users WHERE role = ? LIMIT 1", (role,)).fetchone()
            if in_use:
                raise ValueError("Delete or reassign users with this role first.")
            connection.execute("DELETE FROM roles WHERE name = ?", (role,))
            connection.commit()
        finally:
            connection.close()

    def users(self) -> list[dict[str, str]]:
        connection = self.connect()
        try:
            rows = connection.execute("SELECT username, role FROM users ORDER BY username").fetchall()
            return [{"username": str(row["username"]), "role": str(row["role"])} for row in rows]
        finally:
            connection.close()

    def current_user(self, username: str) -> dict[str, str] | None:
        connection = self.connect()
        try:
            row = connection.execute("SELECT username, role FROM users WHERE username = ?", (username,)).fetchone()
        finally:
            connection.close()
        return {"username": str(row["username"]), "role": str(row["role"])} if row else None

    def create_user(self, username: str, password: str, role: str) -> None:
        if role not in self.role_names():
            raise ValueError("Select an existing role.")
        connection = self.connect()
        try:
            connection.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, hash_password(password), role),
            )
            connection.commit()
        finally:
            connection.close()

    def delete_user(self, username: str) -> None:
        connection = self.connect()
        try:
            connection.execute("DELETE FROM users WHERE username = ?", (username,))
            connection.commit()
        finally:
            connection.close()

    def authenticate(self, username: str, password: str) -> dict[str, str] | None:
        connection = self.connect()
        try:
            row = connection.execute(
                "SELECT username, password_hash, role FROM users WHERE username = ?", (username.strip().lower(),)
            ).fetchone()
        finally:
            connection.close()
        if row and verify_password(password, str(row["password_hash"])):
            return {"username": str(row["username"]), "role": str(row["role"])}
        return None

    def log_query(
        self, *, username: str, role: str, query: str, retrieved_chunk_ids: list[str],
        retrieved_sources: list[str], restricted_chunks_excluded: int, answer: str, flagged: bool,
    ) -> None:
        connection = self.connect()
        try:
            connection.execute(
                """
                INSERT INTO audit_log (
                    timestamp, username, role, query, retrieved_chunk_ids, retrieved_sources,
                    restricted_chunks_excluded, answer, flagged
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (self._now(), username, role, query, json.dumps(retrieved_chunk_ids), json.dumps(retrieved_sources),
                 restricted_chunks_excluded, answer, int(flagged)),
            )
            connection.commit()
        finally:
            connection.close()

    def audit_rows(self, limit: int = 100) -> list[dict[str, object]]:
        connection = self.connect()
        try:
            rows = connection.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (min(max(limit, 1), 500),)
            ).fetchall()
        finally:
            connection.close()
        return [
            {
                "id": row["id"], "timestamp": row["timestamp"], "username": row["username"], "role": row["role"],
                "query": row["query"], "retrieved_chunk_ids": json.loads(row["retrieved_chunk_ids"]),
                "retrieved_sources": json.loads(row["retrieved_sources"]),
                "restricted_chunks_excluded": row["restricted_chunks_excluded"], "answer": row["answer"],
                "flagged": bool(row["flagged"]),
            }
            for row in rows
        ]
