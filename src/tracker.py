from __future__ import annotations

import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from src.config import settings


def _connect() -> sqlite3.Connection:
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def _db() -> Generator[sqlite3.Connection, None, None]:
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with _db() as conn:
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

            CREATE TABLE IF NOT EXISTS issue_classifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_number INTEGER NOT NULL,
                issue_url TEXT NOT NULL,
                issue_title TEXT NOT NULL,
                priority TEXT NOT NULL,
                complexity TEXT NOT NULL,
                priority_reason TEXT NOT NULL,
                complexity_reason TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_classifications_issue ON issue_classifications(issue_number);
            CREATE INDEX IF NOT EXISTS idx_classifications_priority ON issue_classifications(priority);
            CREATE INDEX IF NOT EXISTS idx_classifications_complexity ON issue_classifications(complexity);

            CREATE TABLE IF NOT EXISTS safety_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pr_number INTEGER NOT NULL,
                pr_url TEXT NOT NULL,
                pr_title TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                blocked INTEGER NOT NULL,
                prompt_injection_count INTEGER NOT NULL,
                malicious_code_count INTEGER NOT NULL,
                findings TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_safety_events_pr ON safety_events(pr_number);
            CREATE INDEX IF NOT EXISTS idx_safety_events_blocked ON safety_events(blocked);
        """)
        conn.commit()


def create_job(
    issue_number: int,
    issue_url: str,
    issue_title: str,
    trigger_type: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with _db() as conn:
        cur = conn.execute(
            """INSERT INTO jobs (issue_number, issue_url, issue_title, trigger_type, status, created_at, updated_at, metadata)
               VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (issue_number, issue_url, issue_title, trigger_type, now, now, json.dumps(metadata or {})),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


def update_job(job_id: int, **kwargs: Any) -> dict[str, Any] | None:
    kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
    if "metadata" in kwargs and isinstance(kwargs["metadata"], dict):
        kwargs["metadata"] = json.dumps(kwargs["metadata"])
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [job_id]
    with _db() as conn:
        conn.execute(f"UPDATE jobs SET {sets} WHERE id = ?", vals)
        conn.commit()
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def get_job(job_id: int) -> dict[str, Any] | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def get_job_by_issue(issue_number: int) -> dict[str, Any] | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE issue_number = ? ORDER BY id DESC LIMIT 1",
            (issue_number,),
        ).fetchone()
        return dict(row) if row else None


def create_classification(
    issue_number: int,
    issue_url: str,
    issue_title: str,
    priority: str,
    complexity: str,
    priority_reason: str,
    complexity_reason: str,
    trigger_type: str,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with _db() as conn:
        cur = conn.execute(
            """INSERT INTO issue_classifications (
                issue_number, issue_url, issue_title, priority, complexity,
                priority_reason, complexity_reason, trigger_type, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                issue_number,
                issue_url,
                issue_title,
                priority,
                complexity,
                priority_reason,
                complexity_reason,
                trigger_type,
                now,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM issue_classifications WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
        return dict(row)


def get_latest_classification(issue_number: int) -> dict[str, Any] | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM issue_classifications WHERE issue_number = ? ORDER BY id DESC LIMIT 1",
            (issue_number,),
        ).fetchone()
        return dict(row) if row else None


def create_safety_event(
    pr_number: int,
    pr_url: str,
    pr_title: str,
    trigger_type: str,
    blocked: bool,
    prompt_injection_count: int,
    malicious_code_count: int,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with _db() as conn:
        cur = conn.execute(
            """INSERT INTO safety_events (
                pr_number, pr_url, pr_title, trigger_type, blocked,
                prompt_injection_count, malicious_code_count, findings, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pr_number,
                pr_url,
                pr_title,
                trigger_type,
                int(blocked),
                prompt_injection_count,
                malicious_code_count,
                json.dumps(findings),
                now,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM safety_events WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


def list_active_jobs(limit: int = 100) -> list[dict[str, Any]]:
    with _db() as conn:
        rows = conn.execute(
            """SELECT * FROM jobs
               WHERE status IN ('pending', 'dispatching', 'dispatched', 'running', 'plan_dispatched')
               ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_jobs(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with _db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY id DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_metrics() -> dict[str, Any]:
    with _db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        by_status = {}
        for row in conn.execute("SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status").fetchall():
            by_status[row["status"]] = row["cnt"]
        by_trigger = {}
        for row in conn.execute("SELECT trigger_type, COUNT(*) as cnt FROM jobs GROUP BY trigger_type").fetchall():
            by_trigger[row["trigger_type"]] = row["cnt"]
        by_priority = {}
        for row in conn.execute("SELECT priority, COUNT(*) as cnt FROM issue_classifications GROUP BY priority").fetchall():
            by_priority[row["priority"]] = row["cnt"]
        by_complexity = {}
        for row in conn.execute("SELECT complexity, COUNT(*) as cnt FROM issue_classifications GROUP BY complexity").fetchall():
            by_complexity[row["complexity"]] = row["cnt"]
        classifications_total = conn.execute("SELECT COUNT(*) FROM issue_classifications").fetchone()[0]
        safety_total = conn.execute("SELECT COUNT(*) FROM safety_events").fetchone()[0]
        safety_blocked = conn.execute("SELECT COUNT(*) FROM safety_events WHERE blocked = 1").fetchone()[0]
        prompt_injection_total = conn.execute(
            "SELECT COALESCE(SUM(prompt_injection_count), 0) FROM safety_events"
        ).fetchone()[0]
        malicious_code_total = conn.execute(
            "SELECT COALESCE(SUM(malicious_code_count), 0) FROM safety_events"
        ).fetchone()[0]
        recent = conn.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT 10"
        ).fetchall()
        all_jobs = conn.execute("SELECT status, metadata FROM jobs").fetchall()
        latest_safety = conn.execute(
            "SELECT * FROM safety_events ORDER BY id DESC LIMIT 10"
        ).fetchall()
    recent_jobs = [dict(r) for r in recent]
    auto_fixed = _count_auto_fixed_jobs([dict(r) for r in all_jobs])
    auto_merged = _count_completed_jobs_with_policy_flag([dict(r) for r in all_jobs], "auto_merge_enabled")
    return {
        "total_jobs": total,
        "by_status": by_status,
        "by_trigger": by_trigger,
        "issues_classified": classifications_total,
        "priority_distribution": by_priority,
        "complexity_distribution": by_complexity,
        "devin_sessions_started": by_status.get("dispatched", 0)
        + by_status.get("running", 0)
        + by_status.get("completed", 0)
        + by_status.get("plan_dispatched", 0)
        + by_status.get("devin_exited", 0),
        "active_jobs": by_status.get("pending", 0)
        + by_status.get("dispatching", 0)
        + by_status.get("dispatched", 0)
        + by_status.get("running", 0),
        "completed_jobs": by_status.get("completed", 0),
        "failed_jobs": by_status.get("failed", 0) + by_status.get("devin_exited", 0),
        "auto_fixed_issues": auto_fixed,
        "auto_merged_prs": auto_merged,
        "prs_blocked_by_safety_scans": safety_blocked,
        "prompt_injection_findings": prompt_injection_total,
        "malicious_code_findings": malicious_code_total,
        "safety_scans": safety_total,
        "plan_workflows_waiting_for_approval": by_status.get("plan_dispatched", 0),
        "latest_job_status": recent_jobs[0]["status"] if recent_jobs else None,
        "recent_jobs": recent_jobs,
        "recent_safety_events": [dict(r) for r in latest_safety],
    }


def _count_auto_fixed_jobs(jobs: list[dict[str, Any]]) -> int:
    count = 0
    for job in jobs:
        if job.get("status") != "completed":
            continue
        meta = parse_job_metadata(job)
        action = meta.get("policy", {}).get("action", "")
        if action in {"fix_pr", "fix_pr_human_review", "implement_plan"}:
            count += 1
    return count


def _count_completed_jobs_with_policy_flag(jobs: list[dict[str, Any]], flag: str) -> int:
    count = 0
    for job in jobs:
        if job.get("status") != "completed":
            continue
        meta = parse_job_metadata(job)
        policy = meta.get("policy", {})
        if policy.get(flag):
            count += 1
    return count


def parse_job_metadata(job: dict[str, Any]) -> dict[str, Any]:
    raw_meta = job.get("metadata") or "{}"
    if isinstance(raw_meta, dict):
        return raw_meta
    try:
        return json.loads(raw_meta)
    except json.JSONDecodeError:
        return {}
