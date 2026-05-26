# GST Automation — Operations (Deterministic)

This document is the operator runbook for local/staging/production startup and recovery.

## Deterministic startup order (local)

1) Ensure `.env` is present
- Copy once: `copy .env.example .env`

2) Start infrastructure (Docker)
- Start Docker Desktop
- Start only infra first: `docker compose up -d postgres redis`
- Verify healthy: `docker compose ps`

3) Run DB migrations
- `python -m gst_automation.cli.db upgrade`

4) Verify system readiness (single command)
- `python -m gst_automation.validation full-check --client-master client_master.xlsx`

5) Start API (interactive)
- `python -m gst_automation.cli.api`

6) Start workers (interactive)
- Downloads worker: `celery -A gst_automation.cli.worker:celery_app worker -Q downloads,critical -l INFO -P solo -c 1`
- Monitoring worker: `celery -A gst_automation.cli.worker:celery_app worker -Q monitoring,maintenance -l INFO -P solo -c 1`
- Beat: `celery -A gst_automation.cli.worker:celery_app beat -l INFO`

## Deterministic onboarding flow (operator)

1) Generate template
- `python -m gst_automation.validation client-master template`

2) Validate filled workbook (no writes)
- `python -m gst_automation.validation client-master validate client_master.xlsx`

3) Import into DB
- `python -m gst_automation.validation client-master import client_master.xlsx`

4) Verify client list
- `curl http://127.0.0.1:8000/clients`

## Troubleshooting (common infra failures)

### Docker works, but compose shows nothing
- You are likely not in the project folder, or the compose project wasn’t started.
- Run from repo root: `docker compose ps`
- Start infra: `docker compose up -d postgres redis`

### Postgres connection timeout/refused
- Confirm port exposure: `docker compose ps` (should show `0.0.0.0:5432->5432/tcp`)
- Validate config: `python -m gst_automation.validation doctor env` then `python -m gst_automation.validation doctor db`

### Migrations fail after changing POSTGRES_* or DATABASE_*
- Reset volumes deterministically:
  - `docker compose down -v`
  - `docker compose up -d postgres redis`
  - `python -m gst_automation.cli.db upgrade`

### Redis connection failures
- Confirm port exposure: `docker compose ps` (should show `0.0.0.0:6379->6379/tcp`)
- Validate config: `python -m gst_automation.validation doctor env`

## Operational verification utilities

- Full deterministic verification: `python -m gst_automation.validation full-check --client-master client_master.xlsx`
- Minimal runtime smoke: `python -m gst_automation.validation smoke-runtime`
- Environment diagnostics: `python -m gst_automation.validation doctor env`
- DB diagnostics: `python -m gst_automation.validation doctor db`
- Schema diagnostics: `python -m gst_automation.validation doctor schema`

