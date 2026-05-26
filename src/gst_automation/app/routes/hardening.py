from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Request
from sqlalchemy import select

from gst_automation.db.models.gst.execution import GstExecutionReport
from gst_automation.db.models.gst.operator_checkpoint import OperatorCheckpoint
from gst_automation.db.models.orchestration.job import Job
from gst_automation.gst.execution_validator import GstExecutionValidator
from gst_automation.gst.selector_drift import SelectorDriftDetector
from gst_automation.gst.forensics import GstForensicsPackager


router = APIRouter(prefix="/hardening", tags=["hardening"])


@router.post("/validate/gstr2b/{job_id}")
async def validate_gstr2b_job(request: Request, job_id: str, client_id: str, period: str) -> dict[str, object]:
    db = request.app.state.db
    jid = uuid.UUID(job_id)
    cid = uuid.UUID(client_id)
    async with db.session() as session:
        row = await GstExecutionValidator().validate_job(
            session,
            job_id=jid,
            client_id=cid,
            period=period,
            require_email_sent=False,
            artifacts_root=Path(request.app.state.settings.browser_artifacts_dir),
        )
        await session.commit()
    return {"id": str(row.id), "status": row.status, "score": row.score, "created_at": row.created_at.isoformat()}


@router.get("/reports/gstr2b")
async def list_gstr2b_reports(request: Request, limit: int = 50) -> list[dict[str, object]]:
    db = request.app.state.db
    async with db.session() as session:
        res = await session.execute(
            select(GstExecutionReport).order_by(GstExecutionReport.created_at.desc()).limit(limit)
        )
        rows = list(res.scalars().all())
    return [
        {
            "id": str(r.id),
            "job_id": str(r.job_id),
            "client_id": str(r.client_id),
            "period": r.period,
            "status": r.status,
            "score": r.score,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/selectors/drift")
async def selector_drift_snapshot(
    request: Request, lookback_minutes: int = 60, min_samples: int = 20, top_n: int = 50
) -> list[dict[str, object]]:
    db = request.app.state.db
    async with db.session() as session:
        snaps = await SelectorDriftDetector().snapshot(
            session, lookback_minutes=lookback_minutes, min_samples=min_samples, top_n=top_n
        )
    return [
        {
            "key": s.key,
            "fail_rate": s.fail_rate,
            "fallback_rate": s.fallback_rate,
            "p95_latency_ms": s.p95_latency_ms,
            "samples": s.samples,
        }
        for s in snaps
    ]


@router.post("/selectors/drift/anomalies")
async def selector_drift_record_anomalies(request: Request) -> dict[str, object]:
    db = request.app.state.db
    async with db.session() as session:
        raised = await SelectorDriftDetector().record_anomalies(session)
        await session.commit()
    return {"raised": int(raised)}


@router.post("/forensics/gstr2b/{job_id}")
async def package_gstr2b_forensics(request: Request, job_id: str) -> dict[str, object]:
    db = request.app.state.db
    settings = request.app.state.settings
    async with db.session() as session:
        res = await GstForensicsPackager(artifacts_root=Path(settings.browser_artifacts_dir)).package_job(
            session, job_id=uuid.UUID(job_id)
        )
        await session.commit()
    return {"relpath": res.relpath, "context_id": str(res.context_id)}


@router.get("/incidents/gstr2b")
async def list_gstr2b_incidents(request: Request, limit: int = 50) -> list[dict[str, object]]:
    db = request.app.state.db
    async with db.session() as session:
        res = await session.execute(
            select(Job)
            .where(Job.kind == "gstr2b_download")
            .where(Job.state != "completed")
            .order_by(Job.state_updated_at.desc())
            .limit(limit)
        )
        jobs = list(res.scalars().all())
    return [
        {
            "job_id": str(j.id),
            "client_id": str(j.client_id) if j.client_id else None,
            "state": j.state,
            "queue": j.queue,
            "priority": j.priority,
            "state_updated_at": j.state_updated_at.isoformat(),
        }
        for j in jobs
    ]


@router.get("/checkpoints/gst-auth-refresh")
async def list_auth_refresh_checkpoints(request: Request, limit: int = 50) -> list[dict[str, object]]:
    db = request.app.state.db
    async with db.session() as session:
        res = await session.execute(
            select(OperatorCheckpoint)
            .where(OperatorCheckpoint.kind == "gst_auth_refresh")
            .order_by(OperatorCheckpoint.created_at.desc())
            .limit(limit)
        )
        rows = list(res.scalars().all())
    return [
        {
            "id": str(r.id),
            "job_id": str(r.job_id),
            "context_id": str(r.context_id),
            "status": r.status,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
