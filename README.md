# Superset Devin Automation

No-host GitHub Actions automation for governed Devin remediation in the [Apache Superset fork](https://github.com/arufian/superset).

This project does **not** require hosting for the take-home demo. GitHub Actions is the runner. Actions receive issue, comment, PR, schedule, or manual-dispatch events; the Python automation classifies work, applies policy, starts Devin sessions, and records metrics in a SQLite artifact.

FastAPI/webhook mode still exists for local exploration, but it is optional.

## No-Host Architecture

```text
GitHub event or workflow_dispatch
        ↓
GitHub Actions runner
        ↓
python -m src.actions ...
        ↓
Classification, policy, safety scan, persistence
        ↓
Devin API session
        ↓
Devin GitHub integration comment/PR, workflow labels, security issue, or report
        ↓
Actions logs, summary, and uploaded SQLite artifact
```

No server. No public URL. No `GITHUB_WEBHOOK_SECRET` needed.

## What It Does

- Issue opened: classify priority and complexity, add labels.
- Issue labeled `devin:fix`: classify, apply policy matrix, dispatch Devin for a focused PR/report.
- Issue labeled `devin:plan`: dispatch Devin in plan-only mode.
- Comment `run that plan`: dispatch Devin to implement the approved plan.
- PR opened/synchronized/reopened: scan diff for prompt-injection and malicious-code risk; block by failing the workflow.
- Scheduled/manual recovery: process `devin:ready`, sync sessions, mark stale jobs, classify missed issues, scan open PRs, emit metrics.

In the hosted GitHub Actions demo, workflow-authored comments are disabled with `AUTOMATION_COMMENTS_ENABLED=false`. GitHub-visible issue and PR writeups should come from Devin's official GitHub integration (`devin-ai-integration`) when Devin acts inside its session. The workflow may still add routing labels as `github-actions[bot]`. User-owned GitHub tokens are blocked from visible writes by default so automation cannot accidentally comment, label, or open issues as a personal account.

## Policy Matrix

| Priority | Complexity | Action |
|---|---|---|
| low | simple | Devin fixes, PR created, auto-merge candidate if enabled and safety passes |
| low | medium | Devin fixes, PR created, auto-merge candidate if enabled and safety passes |
| medium | simple | Devin fixes, PR created, human review recommended |
| medium | medium | Devin fixes, PR created, human review required |
| medium | very-complex | Devin creates PR, human approval required |
| high | simple | Devin creates PR, human approval required |
| high | medium | Devin creates PR, human approval required |
| high | very-complex | Devin creates plan first, waits for `run that plan`, then implements after approval |

Default is conservative:

- `AUTO_MERGE_ENABLED=false`
- PR safety findings fail the PR workflow
- high-priority work requires human review
- high-priority and very-complex work uses plan-first routing

## Take-Home Demo Setup

Push this automation repo to GitHub, then set repository secrets:

| Secret | Value |
|---|---|
| `DEVIN_API_KEY` | Devin service user token |
| `DEVIN_ORG_ID` | Devin organization id |
| `GH_PAT` | Optional read token for local/cross-repo experiments; do not use for visible write automation |

Set repository variables:

| Variable | Value |
|---|---|
| `TARGET_REPO` | `arufian/superset` |
| `SIMULATION_MODE` | `false` |
| `AUTO_MERGE_ENABLED` | `false` |

If workflows live directly in `arufian/superset`, `GH_PAT` can be skipped and GitHub's built-in `github.token` can work. If workflows live in this automation repo and target another repo, use `GH_PAT`.

Minimum `GH_PAT` permissions for read-only local/cross-repo experiments:

- Issues: read-only
- Pull requests: read
- Contents: read
- Metadata: read

Visible writes must use GitHub Actions' built-in `github.token` in the target repo, or a GitHub App installation token. User-owned tokens such as `github_pat_...`, `ghp_...`, `gho_...`, and `ghu_...` are refused for comments, labels, issue creation, and label removal unless `ALLOW_USER_TOKEN_WRITES=true` is explicitly set for an intentional local/manual run.

If scheduled scan fails with `403 Forbidden` on visible writes, do not switch to a personal PAT. Instead:

- move the workflows into the target repo and use `${{ github.token }}`
- or provide a GitHub App installation token whose bot identity should own the visible write

The built-in `github.token` only writes to the workflow repo. When this automation repo targets a different repo, use the cross-repo mode for read-only discovery or provide a GitHub App installation token for visible writes.

## Run Without Hosting

Use GitHub Actions tab.

### Manual Issue Demo

Run workflow: `Devin Automation - Issue Governance`

Inputs:

```text
issue_number: 1
action: classify | fix | plan | implement_plan
```

Common demo:

1. `action=classify`
2. `action=fix`
3. For plan path: `action=plan`, then `action=implement_plan`

### PR Safety Demo

Run workflow: `Devin Automation - PR Safety Scan`

No input needed. Manual run scans every open pull request. Pull request open/update events scan the changed PR automatically.

If unsafe diff content is found, workflow fails and records the safety event. Workflow-authored PR comments stay disabled in the hosted demo so visible writeups come from Devin.

### Scheduled Recovery Demo

Run workflow: `Devin Automation - Scheduled Scan`

It processes ready issues, syncs jobs, scans PRs, and writes an Actions summary.

## Event-Driven No-Host Mode

For automatic issue/PR triggers, place these workflows in the target repo or keep checkout pointed at this automation repo:

- `.github/workflows/issue-label-trigger.yml`
- `.github/workflows/pr-safety-scan.yml`
- `.github/workflows/scheduled-scan.yml`

Then use normal GitHub events:

- create issue
- add `devin:fix`
- add `devin:plan`
- comment `run that plan`
- open/update PR

GitHub Actions handles events directly. Still no hosting.

## Local CLI

Local runs do not need server either:

```bash
cd superset-devin-automation
pip install -e .
SIMULATION_MODE=true python -m src.actions classify-issue 1
SIMULATION_MODE=true python -m src.actions process-issue 1
SIMULATION_MODE=true python -m src.actions process-issue 1 --action plan
```

Live local run needs `.env` or exported env vars:

```bash
DEVIN_API_KEY=cog_...
DEVIN_ORG_ID=org-...
GITHUB_TOKEN=github_pat_...
GITHUB_REPO=arufian/superset
SIMULATION_MODE=false
python -m src.actions process-issue 1
```

Local live runs with a user-owned token can read issues and PRs. They will refuse visible writes by default to avoid comments or labels appearing from your account. For an intentional manual write test only, add `ALLOW_USER_TOKEN_WRITES=true`.

## Optional Local Dashboard

FastAPI exists for local inspection only:

```bash
uvicorn src.main:app --reload --port 8000
```

Useful local endpoints:

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Dashboard UI |
| `/classify/{issue_number}` | POST | Classify one issue |
| `/process/{issue_number}` | POST | Dispatch Devin |
| `/process/{issue_number}?action=plan` | POST | Force plan-only |
| `/process/{issue_number}?action=implement_plan` | POST | Implement approved plan |
| `/pr/{pr_number}/safety` | POST | Scan PR diff |
| `/metrics` | GET | Metrics summary |

`/webhook/github` is optional. It requires hosting or a tunnel and `GITHUB_WEBHOOK_SECRET`, so it is not the recommended take-home path.

## PR Safety Scan

Scanner checks added diff lines for:

- prompt-injection attempts
- hidden prompt exfiltration
- agent/reviewer manipulation
- hardcoded tokens
- private keys
- `eval` / `exec`
- `shell=True`
- curl-pipe-shell
- environment exfiltration
- risky workflow permissions
- base64 payload execution

Findings cause:

- `security:blocked`
- `devin:auto-merge-blocked`
- PR warning comment when workflow comments are enabled
- security review issue
- failed GitHub Actions check

## Observability

SQLite stores job, classification, and safety scan history in `data/jobs.db`. GitHub Actions uploads this DB as artifact.

Metrics include:

- issues classified
- priority distribution
- complexity distribution
- Devin sessions started
- active/completed/failed/stale jobs
- plans waiting for approval
- PRs blocked by safety scans
- prompt-injection and malicious-code findings
- latest job status

## Core Files

- `src/actions.py`: no-host GitHub Actions CLI
- `src/classifier.py`: issue classification
- `src/policy.py`: policy matrix
- `src/safety.py`: PR diff scanner
- `src/orchestrator.py`: routing, Devin dispatch, recovery
- `src/tracker.py`: SQLite persistence and metrics
- `src/github_client.py`: GitHub API adapter
- `src/devin_client.py`: Devin API adapter
