# GST Automation — Production Readiness Checklist

Use this checklist before enabling real GST automation runs.

## Environment

- [ ] `.env` present and loaded (`python -m gst_automation.validation doctor env`)
- [ ] `DATABASE_URL` and `DATABASE_MIGRATION_URL` point to the intended Postgres
- [ ] `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` point to the intended Redis
- [ ] Logging configured (`LOG_FORMAT=json` recommended for production)

## Infrastructure

- [ ] Docker Desktop / container runtime healthy (local)
- [ ] Postgres reachable (`python -m gst_automation.validation doctor db`)
- [ ] Redis reachable (`python -m gst_automation.validation full-check` or runtime smoke)
- [ ] Ports/firewalls correct for API/DB/Redis

## Migrations / Schema

- [ ] Migrations apply cleanly (`python -m gst_automation.cli.db upgrade`)
- [ ] DB revision matches head (`python -m gst_automation.validation doctor schema`)
- [ ] Required tables present (reported by `doctor schema`)
- [ ] Backup/restore plan exists for Postgres (snapshot + tested restore)

## Runtime

- [ ] API boots without tracebacks (`python -m gst_automation.validation smoke-runtime`)
- [ ] API health endpoints respond (`/health/live`, `/health/ready`)
- [ ] Celery app loads (`celery -A gst_automation.cli.worker:celery_app report`)
- [ ] Workers connect to broker and can be shut down cleanly (`celery inspect ping`, `celery control shutdown`)

## Onboarding

- [ ] Client master template generated and validated
- [ ] `client-master validate` returns `ok: true`
- [ ] `client-master import` returns `ok: true` and creates/updates expected records
- [ ] API `/clients` returns expected clients

## Test hygiene

- [ ] Pytest collects without crashes (`pytest --collect-only`)
- [ ] Any collection warnings reviewed and classified

## Monitoring / Operations

- [ ] Structured logs shipped/retained (stdout capture or log shipper)
- [ ] Basic runtime monitoring in place (API process, worker process, Redis/Postgres availability)
- [ ] Operator runbook available (`docs/OPERATIONS.md`)

