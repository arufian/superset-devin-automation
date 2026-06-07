from __future__ import annotations

import json
import pytest
from src import tracker


class TestInitDb:
    def test_init_db_creates_tables(self, tmp_db):
        import sqlite3
        conn = sqlite3.connect(tmp_db)
        tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        conn.close()
        assert "jobs" in tables
        assert "issue_classifications" in tables
        assert "safety_events" in tables


class TestJobCrud:
    def test_create_and_get_job(self, tmp_db):
        job = tracker.create_job(
            issue_number=1,
            issue_url="https://github.com/test/repo/issues/1",
            issue_title="Fix bug",
            trigger_type="manual",
        )
        assert job["issue_number"] == 1
        assert job["status"] == "pending"
        assert job["id"] is not None

        fetched = tracker.get_job(job["id"])
        assert fetched is not None
        assert fetched["issue_title"] == "Fix bug"

    def test_get_nonexistent_job(self, tmp_db):
        assert tracker.get_job(99999) is None

    def test_update_job(self, tmp_db):
        job = tracker.create_job(
            issue_number=2,
            issue_url="https://github.com/test/repo/issues/2",
            issue_title="Another bug",
            trigger_type="webhook",
        )
        updated = tracker.update_job(job["id"], status="running", devin_session_id="sess-123")
        assert updated is not None
        assert updated["status"] == "running"
        assert updated["devin_session_id"] == "sess-123"

    def test_update_nonexistent_job(self, tmp_db):
        result = tracker.update_job(99999, status="failed")
        assert result is None

    def test_get_job_by_issue(self, tmp_db):
        tracker.create_job(
            issue_number=10,
            issue_url="url",
            issue_title="title",
            trigger_type="test",
        )
        result = tracker.get_job_by_issue(10)
        assert result is not None
        assert result["issue_number"] == 10

    def test_get_job_by_issue_returns_latest(self, tmp_db):
        tracker.create_job(issue_number=11, issue_url="u", issue_title="first", trigger_type="t")
        tracker.create_job(issue_number=11, issue_url="u", issue_title="second", trigger_type="t")
        result = tracker.get_job_by_issue(11)
        assert result["issue_title"] == "second"

    def test_get_job_by_issue_not_found(self, tmp_db):
        assert tracker.get_job_by_issue(99999) is None

    def test_create_job_with_metadata(self, tmp_db):
        job = tracker.create_job(
            issue_number=3,
            issue_url="url",
            issue_title="meta test",
            trigger_type="test",
            metadata={"key": "value"},
        )
        meta = json.loads(job["metadata"])
        assert meta["key"] == "value"


class TestClassificationCrud:
    def test_create_and_get_classification(self, tmp_db):
        record = tracker.create_classification(
            issue_number=5,
            issue_url="url",
            issue_title="Test issue",
            priority="priority:high",
            complexity="complexity:simple",
            priority_reason="reason1",
            complexity_reason="reason2",
            trigger_type="test",
        )
        assert record["priority"] == "priority:high"

        latest = tracker.get_latest_classification(5)
        assert latest is not None
        assert latest["complexity"] == "complexity:simple"

    def test_get_latest_returns_newest(self, tmp_db):
        tracker.create_classification(
            issue_number=6, issue_url="u", issue_title="t",
            priority="priority:low", complexity="complexity:simple",
            priority_reason="r", complexity_reason="r", trigger_type="t",
        )
        tracker.create_classification(
            issue_number=6, issue_url="u", issue_title="t",
            priority="priority:high", complexity="complexity:medium",
            priority_reason="r", complexity_reason="r", trigger_type="t",
        )
        latest = tracker.get_latest_classification(6)
        assert latest["priority"] == "priority:high"

    def test_get_latest_not_found(self, tmp_db):
        assert tracker.get_latest_classification(99999) is None


class TestSafetyEventCrud:
    def test_create_safety_event(self, tmp_db):
        event = tracker.create_safety_event(
            pr_number=100,
            pr_url="url",
            pr_title="Test PR",
            trigger_type="test",
            blocked=True,
            prompt_injection_count=1,
            malicious_code_count=2,
            findings=[{"rule": "test", "severity": "high"}],
        )
        assert event["pr_number"] == 100
        assert event["blocked"] == 1
        assert event["prompt_injection_count"] == 1


class TestListJobs:
    def test_list_active_jobs(self, tmp_db):
        tracker.create_job(issue_number=20, issue_url="u", issue_title="t", trigger_type="t")
        jobs = tracker.list_active_jobs()
        assert len(jobs) == 1
        assert jobs[0]["status"] == "pending"

    def test_list_jobs_all(self, tmp_db):
        tracker.create_job(issue_number=30, issue_url="u", issue_title="t", trigger_type="t")
        jobs = tracker.list_jobs()
        assert len(jobs) >= 1

    def test_list_jobs_filtered(self, tmp_db):
        tracker.create_job(issue_number=40, issue_url="u", issue_title="t", trigger_type="t")
        jobs = tracker.list_jobs(status="pending")
        assert all(j["status"] == "pending" for j in jobs)


class TestMetrics:
    def test_get_metrics_empty_db(self, tmp_db):
        m = tracker.get_metrics()
        assert m["total_jobs"] == 0
        assert m["issues_classified"] == 0
        assert m["safety_scans"] == 0

    def test_get_metrics_with_data(self, tmp_db):
        tracker.create_job(issue_number=50, issue_url="u", issue_title="t", trigger_type="t")
        tracker.create_classification(
            issue_number=50, issue_url="u", issue_title="t",
            priority="priority:low", complexity="complexity:simple",
            priority_reason="r", complexity_reason="r", trigger_type="t",
        )
        tracker.create_safety_event(
            pr_number=51, pr_url="u", pr_title="t", trigger_type="t",
            blocked=False, prompt_injection_count=0, malicious_code_count=0, findings=[],
        )
        m = tracker.get_metrics()
        assert m["total_jobs"] == 1
        assert m["issues_classified"] == 1
        assert m["safety_scans"] == 1


class TestHelpers:
    def test_metadata_dict_string(self):
        job = {"metadata": '{"key": "val"}'}
        result = tracker._metadata_dict(job)
        assert result == {"key": "val"}

    def test_metadata_dict_already_dict(self):
        job = {"metadata": {"key": "val"}}
        result = tracker._metadata_dict(job)
        assert result == {"key": "val"}

    def test_metadata_dict_invalid_json(self):
        job = {"metadata": "not json"}
        result = tracker._metadata_dict(job)
        assert result == {}

    def test_metadata_dict_none(self):
        job = {"metadata": None}
        result = tracker._metadata_dict(job)
        assert result == {}

    def test_count_auto_fixed_jobs(self):
        jobs = [
            {"status": "completed", "metadata": json.dumps({"policy": {"action": "fix_pr"}})},
            {"status": "completed", "metadata": json.dumps({"policy": {"action": "plan"}})},
            {"status": "failed", "metadata": json.dumps({"policy": {"action": "fix_pr"}})},
        ]
        assert tracker._count_auto_fixed_jobs(jobs) == 1

    def test_count_completed_jobs_with_policy_flag(self):
        jobs = [
            {"status": "completed", "metadata": json.dumps({"policy": {"auto_merge_enabled": True}})},
            {"status": "completed", "metadata": json.dumps({"policy": {"auto_merge_enabled": False}})},
        ]
        assert tracker._count_completed_jobs_with_policy_flag(jobs, "auto_merge_enabled") == 1
