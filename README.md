# Superset Devin Automation

Event-driven automation system that uses the Devin API to remediate engineering workflow issues in the [Apache Superset fork](https://github.com/arufian/superset).

## Architecture

```
┌─────────────────┐
│  GitHub Issue   │
│  labeled        │
│  devin:fix      │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  Trigger Layer (GitHub Actions or Webhook)              │
│  - Detects label event                                  │
│  - Extracts issue metadata                              │
└────────┬────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  Orchestration Layer (Python/FastAPI)                   │
│  - Creates job record (SQLite)                          │
│  - Builds context-rich prompt                           │
│  - Calls Devin API to create session                    │
│  - Comments on GitHub issue with session URL            │
└────────┬────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  Devin Session                                          │
│  - Clones repo                                          │
│  - Analyzes issue                                       │
│  - Creates branch + PR (or reports why it can't)        │
└────────┬────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  Observability                                          │
│  - Job tracker (SQLite)                                 │
│  - Metrics endpoint                                     │
│  - Dashboard UI                                         │
└─────────────────────────────────────────────────────────┘
```

### Design Principles

1. **Separation of concerns**: This project is the orchestration/governance layer. Devin is the remediation worker.
2. **Small, reviewable changes**: Each Devin session targets one issue with a focused scope.
3. **Observable**: Every action is tracked in SQLite with status updates.
4. **Fail-safe**: If Devin cannot safely proceed, it reports back instead of making risky changes.

## Quick Start

### Prerequisites

- Python 3.11+
- Docker (optional, for containerized deployment)
- GitHub account with access to the Superset fork
- Devin API credentials (service user with `ManageOrgSessions` permission)

### Installation

```bash
cd superset-devin-automation
pip install -e .
```

### Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

**Required environment variables:**

| Variable | Description |
|----------|-------------|
| `DEVIN_API_KEY` | Devin service user API key (prefix: `cog_`) |
| `DEVIN_ORG_ID` | Devin organization ID (prefix: `org-`) |
| `GITHUB_TOKEN` | GitHub personal access token with `repo` scope |
| `GITHUB_REPO` | Target repository (default: `arufian/superset`) |

**Optional:**

| Variable | Description | Default |
|----------|-------------|---------|
| `GITHUB_WEBHOOK_SECRET` | Secret for webhook signature verification | (empty) |
| `SIMULATION_MODE` | Run without calling Devin API | `false` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `DB_PATH` | SQLite database path | `data/jobs.db` |

### Run Locally

```bash
uvicorn src.main:app --reload --port 8000
```

Open http://localhost:8000 for the dashboard.

### Run with Docker

```bash
docker compose up --build
```

## Demo Steps

### Simulation Mode (No Live APIs Required)

1. Start in simulation mode:
   ```bash
   SIMULATION_MODE=true uvicorn src.main:app --reload
   ```

2. Trigger a manual scan:
   ```bash
   curl -X POST http://localhost:8000/scan
   ```

3. Or process a specific issue:
   ```bash
   curl -X POST http://localhost:8000/process/1
   ```

4. View the dashboard at http://localhost:8000

5. Check metrics:
   ```bash
   curl http://localhost:8000/metrics
   ```

### Live Mode (Full End-to-End)

1. Configure `.env` with real credentials

2. Start the automation:
   ```bash
   docker compose up
   ```

3. **Option A: Label an issue**
   - Go to https://github.com/arufian/superset/issues
   - Add the `devin:fix` label to an issue
   - If using GitHub Actions, the workflow triggers automatically
   - If using webhooks, ensure your webhook URL points to `/webhook/github`

4. **Option B: Scheduled scan**
   - Add the `devin:ready` label to issues
   - Wait for the scheduled scan (every 6 hours) or trigger manually:
     ```bash
     curl -X POST http://localhost:8000/scan
     ```

5. **Watch the automation work:**
   - Check the dashboard for job status
   - Devin will comment on the issue with a session URL
   - Devin creates a branch and PR (or reports why it can't)

## GitHub Actions Setup

### Repository Secrets

Add these secrets to your automation repository:

- `DEVIN_API_KEY`
- `DEVIN_ORG_ID`
- `GITHUB_TOKEN` (automatically provided, but ensure it has repo access)

### Repository Variables (Optional)

- `SIMULATION_MODE` - Set to `true` for testing
- `TARGET_REPO` - Override target repo (default: `arufian/superset`)

### Webhook Setup (Alternative to Actions)

If you prefer webhooks over GitHub Actions:

1. Deploy the automation service with a public URL (e.g., using ngrok for testing)
2. Go to https://github.com/arufian/superset/settings/hooks
3. Add webhook:
   - **Payload URL**: `https://your-domain.com/webhook/github`
   - **Content type**: `application/json`
   - **Secret**: Your `GITHUB_WEBHOOK_SECRET`
   - **Events**: Issues → Label events

## How Do I Know This Automation Is Working?

### 1. Dashboard

Visit the root URL (http://localhost:8000) for a real-time dashboard showing:
- Total jobs processed
- Success/failure rates
- Recent job history with links to Devin sessions

### 2. Metrics Endpoint

```bash
curl http://localhost:8000/metrics
```

Returns JSON with:
- `total_jobs`: Total automation runs
- `by_status`: Breakdown by status (completed, failed, running, etc.)
- `by_trigger`: Breakdown by trigger type (webhook, scheduled, manual)
- `recent_jobs`: Last 10 jobs with full details

### 3. GitHub Issue Comments

Every dispatched job comments on the issue with:
- Devin session URL
- Session ID
- Trigger type

### 4. Job Database

SQLite database (`data/jobs.db`) stores all job history. Query it directly:

```bash
sqlite3 data/jobs.db "SELECT * FROM jobs ORDER BY id DESC LIMIT 10;"
```

### 5. Devin Session List

Check your Devin dashboard for sessions tagged with `superset-automation`.

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard UI |
| `/webhook/github` | POST | GitHub webhook receiver |
| `/scan` | POST | Trigger scan of `devin:ready` issues |
| `/process/{issue_number}` | POST | Process specific issue |
| `/sync/{job_id}` | POST | Sync Devin session status |
| `/jobs` | GET | List all jobs |
| `/jobs/{job_id}` | GET | Get specific job |
| `/metrics` | GET | Get metrics summary |
| `/health` | GET | Health check |

## Demo Issues

The following issues were created in the Superset fork for demonstration:

1. **[#1](https://github.com/arufian/superset/issues/1)**: Replace deprecated `datetime.utcnow()` in `utils/dates.py`
2. **[#2](https://github.com/arufian/superset/issues/2)**: Add unit tests for `superset/utils/dates.py` edge cases
3. **[#3](https://github.com/arufian/superset/issues/3)**: Add type hints to `superset/utils/csv.py` public functions
4. **[#4](https://github.com/arufian/superset/issues/4)**: Document local development setup for new contributors

## Failure Handling

When Devin cannot complete a task:

1. **Devin reports back**: The session comments on the issue explaining why it can't proceed
2. **Job marked as failed**: The tracker updates status to `failed` or `devin_exited`
3. **Error logged**: Full error details stored in the job record
4. **Issue commented**: Automation posts a failure comment with error details

Common failure modes:
- Ambiguous issue requirements
- Risky changes that need human judgment
- Test failures that require investigation
- Permission issues with the repository

## Project Structure

```
superset-devin-automation/
├── src/
│   ├── main.py           # FastAPI app + endpoints
│   ├── config.py         # Settings management
│   ├── orchestrator.py   # Core workflow logic
│   ├── devin_client.py   # Devin API client
│   ├── github_client.py  # GitHub API client
│   ├── tracker.py        # SQLite job tracker
│   └── webhook.py        # Webhook signature verification
├── data/                 # SQLite database (gitignored)
├── .github/workflows/    # GitHub Actions workflows
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

## License

Apache 2.0 (same as Apache Superset)
