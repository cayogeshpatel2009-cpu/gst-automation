# GST Automation Platform

Enterprise-grade GST automation platform (GSTR-2B downloads) with production-first architecture.

## Phase 1 (Foundation) included

- Settings + environment validation
- Database bootstrap (SQLAlchemy 2.x async) + Alembic migrations
- Structured JSON logging (structlog)
- Exception hierarchy
- Credential vault abstraction
- Storage path + file naming engine
- Immutable archive foundation (hashing + manifest + read-only mode)
- Docker foundation
- Test scaffold

## Quickstart (local)

1. Copy env:
   - `copy .env.example .env`
2. Start services:
   - `docker compose up -d`
3. Run migrations:
   - `python -m gst_automation.cli.db upgrade`
4. Run API:
   - `python -m gst_automation.cli.api`

## Operational verification (single-command)

- Full deterministic verification: `python -m gst_automation.validation full-check --client-master client_master.xlsx`
- Minimal runtime smoke: `python -m gst_automation.validation smoke-runtime`
- Runbook: `docs/OPERATIONS.md`

## PostgreSQL recovery (deterministic reset)

If you change `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` or any `DATABASE_*` URL, always re-initialize the volume:

- `docker compose down -v`
- `docker compose up -d`
- `python -m gst_automation.validation doctor db`

## Client onboarding (production)

Generate the Excel template, fill it with real client details, validate, and import securely (passwords go to Vault; DB stores only secret refs):

- Generate template: `python -m gst_automation.validation client-master template`
- Validate filled workbook (no DB writes): `python -m gst_automation.validation client-master validate client_master.xlsx`
- Import into DB + Vault: `python -m gst_automation.validation client-master import client_master.xlsx`
- Check onboarding status: `python -m gst_automation.validation onboarding-status`
- Check execution readiness: `python -m gst_automation.validation execution-readiness`

## Real execution proving

These commands assume workers are running (Celery workers + API stack):

- Prove one client end-to-end: `python -m gst_automation.validation prove gstr2b-one --client-id <UUID> --financial-year 2025-26 --period 2026-05`
- Snapshot selector/session reliability: `python -m gst_automation.validation prove reliability`
- Run overnight tick (only enqueues on days 15–20): `python -m gst_automation.validation prove overnight-tick --financial-year 2025-26 --period 2026-05`
- Evaluate production gates: `python -m gst_automation.validation prove gates --lookback-hours 24`
