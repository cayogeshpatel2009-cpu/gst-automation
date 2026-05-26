from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select

from gst_automation.db.models.orchestration.job import Job
from gst_automation.db.models.browser.browser_artifact import BrowserArtifact
from gst_automation.db.models.browser.browser_context import BrowserContextRecord
from gst_automation.validation.browser_health import BrowserHealthService
from gst_automation.validation.cleanup_invariants import CleanupInvariantScanner
from gst_automation.validation.retention import RetentionService
from gst_automation.validation.replay_integrity import ReplayIntegrityValidator
from gst_automation.validation.timeline import TimelineService
from gst_automation.validation.real_site_policy import RealSitePolicy
from gst_automation.gst.forensics import GstForensicsPackager


router = APIRouter(prefix="/validation", tags=["validation"])


@router.get("/jobs/active")
async def active_portal_smoke_jobs(request: Request, limit: int = 50) -> list[dict[str, object]]:
    """Operator view: active (non-completed) portal_smoke jobs."""
    db = request.app.state.db
    async with db.session() as session:
        res = await session.execute(
            select(Job)
            .where(Job.kind == "portal_smoke")
            .where(Job.state != "completed")
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
        rows = list(res.scalars().all())
    return [
        {
            "job_id": str(r.id),
            "state": r.state,
            "queue": r.queue,
            "priority": r.priority,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
            "next_run_at": r.next_run_at.isoformat() if r.next_run_at else None,
        }
        for r in rows
    ]


@router.get("/jobs/{job_id}/contexts")
async def job_contexts(request: Request, job_id: str) -> list[dict[str, object]]:
    db = request.app.state.db
    jid = uuid.UUID(job_id)
    async with db.session() as session:
        res = await session.execute(
            select(BrowserContextRecord).where(BrowserContextRecord.job_id == jid).order_by(BrowserContextRecord.created_at.desc())
        )
        rows = list(res.scalars().all())
    return [
        {
            "context_id": str(r.id),
            "browser_id": str(r.browser_id),
            "state": r.state,
            "created_at": r.created_at.isoformat(),
            "closed_at": r.closed_at.isoformat() if r.closed_at else None,
            "artifacts_dir": r.artifacts_dir,
        }
        for r in rows
    ]


@router.get("/jobs/{job_id}/artifacts")
async def job_artifacts(request: Request, job_id: str, limit: int = 200) -> list[dict[str, object]]:
    db = request.app.state.db
    jid = uuid.UUID(job_id)
    async with db.session() as session:
        res = await session.execute(
            select(BrowserArtifact)
            .where(BrowserArtifact.job_id == jid)
            .order_by(BrowserArtifact.created_at.desc())
            .limit(limit)
        )
        rows = list(res.scalars().all())
    return [
        {
            "id": str(r.id),
            "context_id": str(r.context_id),
            "kind": r.kind,
            "relpath": r.relpath,
            "sha256_hex": r.sha256_hex,
            "byte_size": r.byte_size,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/artifacts/file")
async def get_artifact_file(request: Request, relpath: str) -> FileResponse:
    settings = request.app.state.settings
    root = Path(settings.browser_artifacts_dir).resolve()
    target = (root / relpath).resolve()
    if root not in target.parents and target != root:
        raise HTTPException(status_code=400, detail="invalid relpath")
    if not target.exists():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path=str(target))


@router.get("/jobs/{job_id}/timeline")
async def job_timeline(request: Request, job_id: str) -> list[dict[str, object]]:
    settings = request.app.state.settings
    db = request.app.state.db
    jid = uuid.UUID(job_id)
    async with db.session() as session:
        events = await TimelineService(settings=settings).build_for_job(session, job_id=jid)
    return [{"ts_ms": e.ts_ms, "kind": e.kind, "details": e.details} for e in events]


@router.post("/jobs/{job_id}/forensics-package")
async def package_forensics(request: Request, job_id: str) -> dict[str, object]:
    settings = request.app.state.settings
    db = request.app.state.db
    jid = uuid.UUID(job_id)
    async with db.session() as session:
        res = await GstForensicsPackager(artifacts_root=Path(settings.browser_artifacts_dir)).package_job(session, job_id=jid)
        await session.commit()
    return {"ok": True, "relpath": res.relpath}


@router.post("/cleanup/scan")
async def cleanup_scan(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    db = request.app.state.db
    async with db.session() as session:
        report = await CleanupInvariantScanner(settings=settings).scan(session)
        await session.commit()
    return {"status": report.status, "findings": report.findings}


@router.post("/retention/enforce")
async def retention_enforce(request: Request, dry_run: bool = True) -> dict[str, object]:
    settings = request.app.state.settings
    db = request.app.state.db
    async with db.session() as session:
        res = await RetentionService(settings=settings).enforce(session, dry_run=dry_run)
        await session.commit()
    return {"dry_run": dry_run, "deleted": res.deleted, "kept": res.kept, "errors": res.errors}


@router.get("/browser/health")
async def browser_health(request: Request) -> list[dict[str, object]]:
    db = request.app.state.db
    async with db.session() as session:
        rows = await BrowserHealthService().snapshot(session)
        await session.commit()
    return [{"browser_id": str(r.browser_id), "score": r.score, "details": r.details} for r in rows]


@router.post("/replay-integrity/{job_id}")
async def replay_integrity(request: Request, job_id: str) -> list[dict[str, object]]:
    settings = request.app.state.settings
    db = request.app.state.db
    jid = uuid.UUID(job_id)
    async with db.session() as session:
        results = await ReplayIntegrityValidator(settings=settings).validate_job(session, job_id=jid)
        await session.commit()
    return [{"status": r.status, "issues": r.issues} for r in results]


@router.get("/real-site/allowlist")
async def real_site_allowlist(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    policy = RealSitePolicy(settings=settings)
    return {"allowlisted_prefixes": policy.allowlisted_prefixes()}
