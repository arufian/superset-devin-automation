from __future__ import annotations

import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    devin_api_key: str = os.environ.get("DEVIN_API_KEY", "")
    devin_org_id: str = os.environ.get("DEVIN_ORG_ID", "")
    devin_base_url: str = "https://api.devin.ai"
    github_token: str = os.environ.get("GITHUB_TOKEN", "")
    github_repo: str = os.environ.get("GITHUB_REPO", "arufian/superset")
    github_webhook_secret: str = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    trigger_label: str = "devin:fix"
    scan_label: str = "devin:ready"
    db_path: str = os.environ.get("DB_PATH", "data/jobs.db")
    simulation_mode: bool = os.environ.get("SIMULATION_MODE", "false").lower() == "true"
    log_level: str = os.environ.get("LOG_LEVEL", "INFO")

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
