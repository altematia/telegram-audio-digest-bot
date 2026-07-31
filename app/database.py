from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Recording:
    id: int
    chat_id: int
    user_id: int
    source_name: str
    transcript: str


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS recordings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    source_name TEXT NOT NULL,
                    transcript TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS generated_outputs (
                    recording_id INTEGER NOT NULL,
                    format_key TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (recording_id, format_key),
                    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS recordings_created_at_idx
                    ON recordings(created_at);

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def claim_owner(self, user_id: int) -> int:
        """Atomically claim an unconfigured bot for its first Telegram user."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO app_settings (key, value) VALUES ('owner_user_id', ?)",
                (str(user_id),),
            )
            row = connection.execute(
                "SELECT value FROM app_settings WHERE key = 'owner_user_id'"
            ).fetchone()
        if row is None:
            raise RuntimeError("Could not read owner_user_id")
        return int(row["value"])

    def get_owner(self) -> int | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM app_settings WHERE key = 'owner_user_id'"
            ).fetchone()
        return int(row["value"]) if row is not None else None

    def add_recording(
        self, *, chat_id: int, user_id: int, source_name: str, transcript: str
    ) -> int:
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO recordings (chat_id, user_id, source_name, transcript, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (chat_id, user_id, source_name, transcript, created_at),
            )
            return int(cursor.lastrowid)

    def get_recording(self, recording_id: int) -> Recording | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, chat_id, user_id, source_name, transcript
                FROM recordings WHERE id = ?
                """,
                (recording_id,),
            ).fetchone()
        if row is None:
            return None
        return Recording(
            id=int(row["id"]),
            chat_id=int(row["chat_id"]),
            user_id=int(row["user_id"]),
            source_name=str(row["source_name"]),
            transcript=str(row["transcript"]),
        )

    def get_output(self, recording_id: int, format_key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT content FROM generated_outputs
                WHERE recording_id = ? AND format_key = ?
                """,
                (recording_id, format_key),
            ).fetchone()
        return str(row["content"]) if row is not None else None

    def save_output(self, recording_id: int, format_key: str, content: str) -> None:
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO generated_outputs (recording_id, format_key, content, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(recording_id, format_key)
                DO UPDATE SET content = excluded.content, created_at = excluded.created_at
                """,
                (recording_id, format_key, content, created_at),
            )

    def purge_older_than(self, days: int) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM recordings WHERE created_at < ?", (cutoff,)
            )
            return max(cursor.rowcount, 0)
