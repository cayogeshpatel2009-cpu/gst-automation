from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from sqlalchemy import select

from gst_automation.db.models.gst.dom_snapshot import GstDomSnapshot
from gst_automation.db.models.gst.portal_profile import GstPortalProfile
from gst_automation.db.models.gst.session_health import GstSessionHealth
from gst_automation.db.models.gst.observation import GstObservationSession, GstWorkflowGraph
from gst_automation.stability.gst_readiness_report import GstReadinessAnalyzer
from gst_automation.gst.reliability import SelectorReliabilityService, SessionReliabilityService


router = APIRouter(prefix="/gst", tags=["gst"])


@router.get("/profiles")
async def list_profiles(request: Request, limit: int = 50) -> list[dict[str, object]]:
    db = request.app.state.db
    async with db.session() as session:
        res = await session.execute(select(GstPortalProfile).order_by(GstPortalProfile.created_at.desc()).limit(limit))
        rows = list(res.scalars().all())
    return [
        {
            "id": str(r.id),
            "job_id": str(r.job_id),
            "context_id": str(r.context_id),
            "url": r.url,
            "title": r.title,
            "redirect_count": r.redirect_count,
            "dom_fingerprint_sha256": r.dom_fingerprint_sha256,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/dom-snapshots")
async def list_dom_snapshots(request: Request, limit: int = 50) -> list[dict[str, object]]:
    db = request.app.state.db
    async with db.session() as session:
        res = await session.execute(select(GstDomSnapshot).order_by(GstDomSnapshot.created_at.desc()).limit(limit))
        rows = list(res.scalars().all())
    return [
        {
            "id": str(r.id),
            "job_id": str(r.job_id),
            "context_id": str(r.context_id),
            "url": r.url,
            "dom_fingerprint_sha256": r.dom_fingerprint_sha256,
            "artifact_relpath": r.artifact_relpath,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/sessions")
async def list_session_health(request: Request, limit: int = 50) -> list[dict[str, object]]:
    db = request.app.state.db
    async with db.session() as session:
        res = await session.execute(select(GstSessionHealth).order_by(GstSessionHealth.created_at.desc()).limit(limit))
        rows = list(res.scalars().all())
    return [
        {
            "id": str(r.id),
            "job_id": str(r.job_id),
            "context_id": str(r.context_id),
            "state": r.state,
            "score": r.score,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/observations")
async def list_observations(request: Request, limit: int = 50) -> list[dict[str, object]]:
    db = request.app.state.db
    async with db.session() as session:
        res = await session.execute(
            select(GstObservationSession).order_by(GstObservationSession.created_at.desc()).limit(limit)
        )
        rows = list(res.scalars().all())
    return [
        {
            "id": str(r.id),
            "job_id": str(r.job_id),
            "context_id": str(r.context_id),
            "status": r.status,
            "start_url": r.start_url,
            "operator_checkpoint_id": str(r.operator_checkpoint_id) if r.operator_checkpoint_id else None,
            "steps_total": r.steps_total,
            "downloads_total": r.downloads_total,
            "selectors_total": r.selectors_total,
            "created_at": r.created_at.isoformat(),
            "ended_at": r.ended_at.isoformat() if r.ended_at else None,
        }
        for r in rows
    ]


@router.get("/observations/{observation_id}/graph")
async def get_observation_graph(request: Request, observation_id: str) -> dict[str, object] | None:
    db = request.app.state.db
    oid = uuid.UUID(observation_id)
    async with db.session() as session:
        res = await session.execute(
            select(GstWorkflowGraph).where(GstWorkflowGraph.observation_id == oid).order_by(GstWorkflowGraph.created_at.desc()).limit(1)
        )
        row = res.scalars().first()
    if row is None:
        return None
    return {"id": str(row.id), "observation_id": str(row.observation_id), "graph_json": row.graph_json, "created_at": row.created_at.isoformat()}


@router.get("/readiness-report")
async def gst_readiness_report(request: Request, lookback_hours: int = 24) -> dict[str, object]:
    db = request.app.state.db
    async with db.session() as session:
        rep = await GstReadinessAnalyzer().analyze(session, lookback_hours=lookback_hours)
    return {"score": rep.score, "details": rep.details}


@router.get("/selector-reliability")
async def selector_reliability(request: Request, lookback_minutes: int = 24 * 60) -> list[dict[str, object]]:
    db = request.app.state.db
    async with db.session() as session:
        rows = await SelectorReliabilityService().snapshot(session, lookback_minutes=lookback_minutes)
    return [
        {
            "selector_key": r.selector_key,
            "samples": r.samples,
            "ok": r.ok,
            "fallback": r.fallback,
            "fail": r.fail,
            "fallback_rate": r.fallback_rate,
            "fail_rate": r.fail_rate,
            "p95_latency_ms": r.p95_latency_ms,
            "score": r.score,
        }
        for r in rows
    ]


@router.get("/session-reliability")
async def session_reliability(request: Request, lookback_minutes: int = 24 * 60) -> dict[str, object]:
    db = request.app.state.db
    async with db.session() as session:
        return await SessionReliabilityService().snapshot(session, lookback_minutes=lookback_minutes)
