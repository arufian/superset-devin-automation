from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse

from src.config import settings
from src import tracker, orchestrator, webhook

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tracker.init_db()
    logger.info("Database initialized at %s", settings.db_path)
    logger.info("Simulation mode: %s", settings.simulation_mode)
    logger.info("Target repo: %s", settings.github_repo)
    yield


app = FastAPI(
    title="Superset Devin Automation",
    description="Event-driven Devin automation for Superset engineering workflows",
    version="0.1.0",
    lifespan=lifespan,
)


@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if settings.github_webhook_secret and not webhook.verify_webhook_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    event_type = request.headers.get("X-GitHub-Event", "")

    logger.info("Received GitHub event: %s", event_type)

    if event_type == "issues":
        issue = webhook.extract_issue_from_webhook(payload)
        if issue:
            logger.info("Trigger label detected on issue #%d", issue["number"])
            background_tasks.add_task(orchestrator.process_issue, issue, "webhook_label")
            return {"status": "dispatched", "issue": issue["number"]}

    return {"status": "ignored", "event": event_type}


@app.post("/scan")
async def trigger_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(orchestrator.scan_ready_issues)
    return {"status": "scan_started", "label": settings.scan_label}


@app.post("/process/{issue_number}")
async def process_issue(issue_number: int, background_tasks: BackgroundTasks):
    from src import github_client
    try:
        issue = github_client.get_issue(issue_number)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Issue not found: {e}")

    background_tasks.add_task(orchestrator.process_issue, issue, "manual_trigger")
    return {"status": "dispatched", "issue": issue_number}


@app.post("/sync/{job_id}")
async def sync_job(job_id: int):
    job = tracker.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = orchestrator.sync_session_status(job)
    if result:
        return {"status": "synced", "job": result}
    return {"status": "no_change", "job": job}


@app.get("/jobs")
async def list_jobs(status: str | None = None, limit: int = 50):
    jobs = tracker.list_jobs(status=status, limit=limit)
    return {"jobs": jobs, "count": len(jobs)}


@app.get("/jobs/{job_id}")
async def get_job(job_id: int):
    job = tracker.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/metrics")
async def metrics():
    return tracker.get_metrics()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "simulation_mode": settings.simulation_mode,
        "target_repo": settings.github_repo,
        "devin_configured": bool(settings.devin_api_key and settings.devin_org_id),
        "github_configured": bool(settings.github_token),
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    metrics_data = tracker.get_metrics()
    jobs = tracker.list_jobs(limit=20)

    status_emoji = {
        "pending": "⏳",
        "dispatching": "🚀",
        "dispatched": "✅",
        "running": "🔄",
        "completed": "🎉",
        "failed": "❌",
        "devin_exited": "⚠️",
    }

    rows = ""
    for job in jobs:
        emoji = status_emoji.get(job["status"], "❓")
        session_link = ""
        if job.get("devin_session_url"):
            session_link = f'<a href="{job["devin_session_url"]}" target="_blank">Session</a>'
        rows += f"""
        <tr>
            <td>{job["id"]}</td>
            <td><a href="{job["issue_url"]}" target="_blank">#{job["issue_number"]}</a></td>
            <td>{job["issue_title"][:60]}</td>
            <td>{emoji} {job["status"]}</td>
            <td>{job.get("devin_status", "-")}</td>
            <td>{job["trigger_type"]}</td>
            <td>{session_link}</td>
            <td>{job["created_at"][:19]}</td>
        </tr>"""

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Superset Devin Automation</title>
        <style>
            body {{ font-family: -apple-system, sans-serif; margin: 40px; background: #f5f5f5; }}
            h1 {{ color: #333; }}
            .metrics {{ display: flex; gap: 20px; margin: 20px 0; }}
            .metric {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
            .metric h3 {{ margin: 0; color: #666; font-size: 14px; }}
            .metric .value {{ font-size: 32px; font-weight: bold; color: #333; }}
            table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #eee; }}
            th {{ background: #f8f8f8; font-weight: 600; }}
            a {{ color: #0066cc; }}
            .sim-banner {{ background: #ff9800; color: white; padding: 10px; border-radius: 4px; margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        <h1>Superset Devin Automation Dashboard</h1>
        {"<div class='sim-banner'>SIMULATION MODE ACTIVE - No real Devin sessions will be created</div>" if settings.simulation_mode else ""}

        <div class="metrics">
            <div class="metric">
                <h3>Total Jobs</h3>
                <div class="value">{metrics_data["total_jobs"]}</div>
            </div>
            <div class="metric">
                <h3>Completed</h3>
                <div class="value">{metrics_data["by_status"].get("completed", 0)}</div>
            </div>
            <div class="metric">
                <h3>Running</h3>
                <div class="value">{metrics_data["by_status"].get("running", 0) + metrics_data["by_status"].get("dispatched", 0)}</div>
            </div>
            <div class="metric">
                <h3>Failed</h3>
                <div class="value">{metrics_data["by_status"].get("failed", 0)}</div>
            </div>
        </div>

        <h2>Recent Jobs</h2>
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Issue</th>
                    <th>Title</th>
                    <th>Status</th>
                    <th>Devin</th>
                    <th>Trigger</th>
                    <th>Session</th>
                    <th>Created</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>

        <h2>API Endpoints</h2>
        <ul>
            <li><code>POST /webhook/github</code> - GitHub webhook receiver</li>
            <li><code>POST /scan</code> - Trigger manual scan of devin:ready issues</li>
            <li><code>POST /process/{{issue_number}}</code> - Process specific issue</li>
            <li><code>POST /sync/{{job_id}}</code> - Sync Devin session status</li>
            <li><code>GET /jobs</code> - List all jobs</li>
            <li><code>GET /jobs/{{job_id}}</code> - Get specific job</li>
            <li><code>GET /metrics</code> - Get metrics summary</li>
            <li><code>GET /health</code> - Health check</li>
        </ul>
    </body>
    </html>
    """
    return html
