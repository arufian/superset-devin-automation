from __future__ import annotations

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import settings


def _connect() -> sqlite3.Connection:
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_number INTEGER NOT NULL,
            issue_url TEXT NOT NULL,
            issue_title TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            devin_session_id TEXT,
            devin_session_url TEXT,
            devin_status TEXT,
            devin_status_detail TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata TEXT DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_issue ON jobs(issue_number);
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
    """)
    conn.commit()
    conn.close()


def create_job(
    issue_number: int,
    issue_url: str,
    issue_title: str,
    trigger_type: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO jobs (issue_number, issue_url, issue_title, trigger_type, status, created_at, updated_at, metadata)
           VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)""",
        (issue_number, issue_url, issue_title, trigger_type, now, now, json.dumps(metadata or {})),
    )
    conn.commit()
    job_id = cur.lastrowid
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return dict(row)


def update_job(job_id: int, **kwargs: Any) -> dict[str, Any] | None:
    kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
    if "metadata" in kwargs and isinstance(kwargs["metadata"], dict):
        kwargs["metadata"] = json.dumps(kwargs["metadata"])
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [job_id]
    conn = _connect()
    conn.execute(f"UPDATE jobs SET {sets} WHERE id = ?", vals)
    conn.commit()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_job(job_id: int) -> dict[str, Any] | None:
    conn = _connect()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_job_by_issue(issue_number: int) -> dict[str, Any] | None:
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM jobs WHERE issue_number = ? ORDER BY id DESC LIMIT 1",
        (issue_number,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_jobs(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    conn = _connect()
    if status:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY id DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_metrics() -> dict[str, Any]:
    conn = _connect()
    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    by_status = {}
    for row in conn.execute("SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status").fetchall():
        by_status[row["status"]] = row["cnt"]
    by_trigger = {}
    for row in conn.execute("SELECT trigger_type, COUNT(*) as cnt FROM jobs GROUP BY trigger_type").fetchall():
        by_trigger[row["trigger_type"]] = row["cnt"]
    recent = conn.execute(
        "SELECT * FROM jobs ORDER BY id DESC LIMIT 10"
    ).fetchall()
    conn.close()
    return {
        "total_jobs": total,
        "by_status": by_status,
        "by_trigger": by_trigger,
        "recent_jobs": [dict(r) for r in recent],
    }
