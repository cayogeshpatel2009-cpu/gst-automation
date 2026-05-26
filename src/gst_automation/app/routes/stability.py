from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from sqlalchemy import select

from gst_automation.db.models.stability.readiness import ReadinessGateResult
from gst_automation.db.models.stability.scoring import StabilityScore
from gst_automation.db.models.stability.soak import SoakCampaign, SoakSnapshot
from gst_automation.stability.readiness import ReadinessGateService
from gst_automation.stability.replay_diff import ReplayDiffEngine
from gst_automation.stability.scoring_service import StabilityScoreService
from gst_automation.stability.certification import CertificationService


router = APIRouter(prefix="/stability", tags=["stability"])


@router.get("/scores")
async def list_scores(request: Request, limit: int = 50) -> list[dict[str, object]]:
    db = request.app.state.db
    async with db.session() as session:
        res = await session.execute(select(StabilityScore).order_by(StabilityScore.created_at.desc()).limit(limit))
        rows = list(res.scalars().all())
    return [
        {"id": str(r.id), "scope": r.scope, "scope_id": str(r.scope_id) if r.scope_id else None, "score": r.score, "created_at": r.created_at.isoformat()}
        for r in rows
    ]


@router.post("/scores/compute")
async def compute_score(request: Request, window_minutes: int = 60) -> dict[str, object]:
    db = request.app.state.db
    async with db.session() as session:
        row = await StabilityScoreService().compute(session, window_minutes=window_minutes)
        await session.commit()
    return {"id": str(row.id), "score": row.score, "created_at": row.created_at.isoformat()}


@router.get("/soak/campaigns")
async def list_campaigns(request: Request, limit: int = 50) -> list[dict[str, object]]:
    db = request.app.state.db
    async with db.session() as session:
        res = await session.execute(select(SoakCampaign).order_by(SoakCampaign.started_at.desc()).limit(limit))
        rows = list(res.scalars().all())
    return [
        {
            "id": str(r.id),
            "status": r.status,
            "duration_seconds": r.duration_seconds,
            "rate_per_minute": r.rate_per_minute,
            "chaos_percent": r.chaos_percent,
            "started_at": r.started_at.isoformat(),
            "ended_at": r.ended_at.isoformat() if r.ended_at else None,
        }
        for r in rows
    ]


@router.get("/soak/campaigns/{campaign_id}/snapshots")
async def list_campaign_snapshots(request: Request, campaign_id: str, limit: int = 200) -> list[dict[str, object]]:
    db = request.app.state.db
    cid = uuid.UUID(campaign_id)
    async with db.session() as session:
        res = await session.execute(
            select(SoakSnapshot)
            .where(SoakSnapshot.campaign_id == cid)
            .order_by(SoakSnapshot.created_at.desc())
            .limit(limit)
        )
        rows = list(res.scalars().all())
    return [{"id": str(r.id), "created_at": r.created_at.isoformat(), "snapshot_json": r.snapshot_json} for r in rows]


@router.post("/replay/diff")
async def replay_diff(request: Request, left_job_id: str, right_job_id: str) -> dict[str, object]:
    settings = request.app.state.settings
    db = request.app.state.db
    l = uuid.UUID(left_job_id)
    r = uuid.UUID(right_job_id)
    async with db.session() as session:
        engine = ReplayDiffEngine(settings=settings)
        result = await engine.diff_jobs(session, left_job_id=l, right_job_id=r)
        report = await engine.record_report(session, left_job_id=l, right_job_id=r, result=result)
        await session.commit()
    return {"id": str(report.id), "status": report.status, "diff_json": report.diff_json}


@router.post("/readiness/evaluate")
async def readiness_evaluate(request: Request) -> dict[str, object]:
    db = request.app.state.db
    async with db.session() as session:
        row = await ReadinessGateService().evaluate(session)
        await session.commit()
    return {"id": str(row.id), "gate_name": row.gate_name, "status": row.status, "score": row.score, "created_at": row.created_at.isoformat()}


@router.get("/readiness/latest")
async def readiness_latest(request: Request, gate_name: str = "pre_gst_readiness") -> dict[str, object] | None:
    db = request.app.state.db
    async with db.session() as session:
        res = await session.execute(
            select(ReadinessGateResult)
            .where(ReadinessGateResult.gate_name == gate_name)
            .order_by(ReadinessGateResult.created_at.desc())
            .limit(1)
        )
        row = res.scalars().first()
    if row is None:
        return None
    return {"id": str(row.id), "gate_name": row.gate_name, "status": row.status, "score": row.score, "created_at": row.created_at.isoformat(), "report_json": row.report_json}


@router.post("/certify/{job_id}")
async def certify_job(request: Request, job_id: str) -> list[dict[str, object]]:
    settings = request.app.state.settings
    db = request.app.state.db
    jid = uuid.UUID(job_id)
    async with db.session() as session:
        rows = await CertificationService(settings=settings).certify_job(session, job_id=jid)
        await session.commit()
    return [{"context_id": str(r.context_id), "status": r.status, "sha256": r.report_sha256_hex} for r in rows]


@router.get("/gst/readiness")
async def gst_readiness_hint(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "gst_probe_allowlist_configured": bool(getattr(settings, "gst_probe_allowlist", "")),
        "gst_probe_base_url_configured": bool(getattr(settings, "gst_probe_base_url", "")),
        "gst_probe_allowlist": getattr(settings, "gst_probe_allowlist", ""),
        "gst_probe_base_url": getattr(settings, "gst_probe_base_url", ""),
    }
