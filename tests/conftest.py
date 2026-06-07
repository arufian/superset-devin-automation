from __future__ import annotations

import os
import pytest

# Ensure tests never hit real APIs
os.environ.setdefault("DEVIN_API_KEY", "test-key")
os.environ.setdefault("DEVIN_ORG_ID", "test-org")
os.environ.setdefault("GITHUB_TOKEN", "test-token")
os.environ.setdefault("GITHUB_REPO", "test-owner/test-repo")
os.environ.setdefault("SIMULATION_MODE", "true")
os.environ.setdefault("DB_PATH", ":memory:")


@pytest.fixture()
def tmp_db(tmp_path):
    """Provide a temporary SQLite database path and patch settings."""
    from src.config import settings

    original = settings.db_path
    db_path = str(tmp_path / "test_jobs.db")
    settings.db_path = db_path

    from src import tracker
    tracker.init_db()

    yield db_path

    settings.db_path = original
