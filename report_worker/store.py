from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, path: str):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS worker_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS worker_status (
                    worker_id TEXT PRIMARY KEY,
                    capabilities_json TEXT NOT NULL,
                    last_heartbeat TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    report_text TEXT NOT NULL,
                    instructions TEXT NOT NULL DEFAULT '',
                    mode TEXT NOT NULL,
                    ai_provider TEXT,
                    ai_model TEXT,
                    fallback_allowed INTEGER NOT NULL DEFAULT 1,
                    fallback_provider TEXT,
                    status TEXT NOT NULL,
                    output_json TEXT,
                    provider_json TEXT,
                    locked_by TEXT,
                    locked_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def create_worker_token(self, name: str) -> str:
        token = f"rw_{secrets.token_urlsafe(32)}"
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO worker_tokens(name, token_hash, created_at) VALUES (?, ?, ?)",
                (name, token_hash(token), now()),
            )
        return token

    def valid_worker_token(self, token: str) -> bool:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM worker_tokens WHERE token_hash = ? AND revoked = 0",
                (token_hash(token),),
            ).fetchone()
        return row is not None

    def heartbeat(self, worker_id: str, capabilities: dict[str, Any]) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO worker_status(worker_id, capabilities_json, last_heartbeat)
                VALUES (?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    capabilities_json=excluded.capabilities_json,
                    last_heartbeat=excluded.last_heartbeat
                """,
                (worker_id, json.dumps(capabilities, ensure_ascii=False), now()),
            )

    def create_job(self, job: dict[str, Any]) -> dict[str, Any]:
        job_id = secrets.token_hex(12)
        timestamp = now()
        values = (
            job_id,
            job["report_text"],
            job.get("instructions", ""),
            job.get("mode", "fast"),
            job.get("ai_provider"),
            job.get("ai_model"),
            int(job.get("fallback_allowed", True)),
            job.get("fallback_provider"),
            "queued",
            timestamp,
            timestamp,
        )
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO jobs(
                    id, report_text, instructions, mode, ai_provider, ai_model,
                    fallback_allowed, fallback_provider, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            self._event(connection, job_id, "queued", "تمت إضافة التقرير إلى الطابور", {})
        return self.get_job(job_id)

    def claim(self, worker_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            timestamp = now()
            updated = connection.execute(
                """
                UPDATE jobs SET status='claimed', locked_by=?, locked_at=?, updated_at=?
                WHERE id=? AND status='queued'
                """,
                (worker_id, timestamp, timestamp, row["id"]),
            )
            if updated.rowcount != 1:
                return None
            self._event(
                connection, row["id"], "claimed", "استلم العامل المحلي المهمة", {}
            )
            claimed = connection.execute(
                "SELECT * FROM jobs WHERE id=?", (row["id"],)
            ).fetchone()
            return self._row(claimed)

    def add_event(
        self, job_id: str, status: str, message: str, metadata: dict[str, Any]
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                "UPDATE jobs SET status=?, updated_at=? WHERE id=?",
                (status, now(), job_id),
            )
            self._event(connection, job_id, status, message, metadata)

    def finish(
        self, job_id: str, status: str, output: dict[str, Any], provider: dict[str, Any]
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                UPDATE jobs SET status=?, output_json=?, provider_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    status,
                    json.dumps(output, ensure_ascii=False),
                    json.dumps(provider, ensure_ascii=False),
                    now(),
                    job_id,
                ),
            )
            self._event(connection, job_id, status, f"انتقلت المهمة إلى {status}", {})

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            job = self._row(row)
            events = connection.execute(
                "SELECT * FROM job_events WHERE job_id=? ORDER BY id", (job_id,)
            ).fetchall()
        job["events"] = [
            {
                **dict(event),
                "metadata": json.loads(event["metadata_json"]),
            }
            for event in events
        ]
        return job

    def _event(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        status: str,
        message: str,
        metadata: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO job_events(job_id, status, message, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_id, status, message, json.dumps(metadata, ensure_ascii=False), now()),
        )

    def _row(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["fallback_allowed"] = bool(result["fallback_allowed"])
        result["output"] = json.loads(result.pop("output_json")) if result["output_json"] else None
        result["provider"] = (
            json.loads(result.pop("provider_json")) if result["provider_json"] else None
        )
        return result
