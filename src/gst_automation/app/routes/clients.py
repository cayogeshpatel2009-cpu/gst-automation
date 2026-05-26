from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Request
from pydantic import BaseModel
from sqlalchemy import select

from gst_automation.clients.import_pipeline import ClientImportPipeline
from gst_automation.clients.readiness import build_readiness_report
from gst_automation.core.settings import Settings
from gst_automation.db.models.client import Client
from gst_automation.db.models.clients.client_config import ClientConfig


router = APIRouter(prefix="/clients", tags=["clients"])


class ImportResult(BaseModel):
    ok: bool
    created: int
    updated: int
    row_errors: list[dict[str, object]]
    preview: list[dict[str, object]]
    summary: dict[str, object]


@router.get("")
async def list_clients(request: Request, limit: int = 100) -> list[dict[str, object]]:
    db = request.app.state.db
    async with db.session() as session:
        res = await session.execute(select(Client).order_by(Client.created_at.desc()).limit(limit))
        clients = list(res.scalars().all())
        cfg_res = await session.execute(select(ClientConfig))
        cfgs = {c.client_id: c for c in cfg_res.scalars().all()}
    out = []
    for c in clients:
        cfg = cfgs.get(c.id)
        out.append(
            {
                "id": str(c.id),
                "gstin": c.gstin,
                "display_name": c.display_name,
                "status": c.status,
                "active": bool(cfg.active) if cfg else None,
                "priority": int(cfg.priority) if cfg else None,
                "folder_root": cfg.folder_root if cfg else None,
                "financial_year": cfg.financial_year if cfg else None,
                "preferred_run_window": int(cfg.preferred_run_window) if cfg else None,
                "tags": cfg.tags if cfg else None,
            }
        )
    return out


@router.post("/import")
async def import_clients(
    request: Request,
    dry_run: bool = True,
    file: UploadFile = File(...),
) -> ImportResult:
    settings: Settings = request.app.state.settings
    db = request.app.state.db
    tmp = Path(settings.work_dir) / "imports"
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / (file.filename or "client_master.xlsx")
    data = await file.read()
    path.write_bytes(data)

    async with db.session() as session:
        rep = await ClientImportPipeline(settings=settings).import_xlsx(session, path=path, dry_run=dry_run)
        if not dry_run and rep.ok:
            await session.commit()
    return ImportResult(
        ok=rep.ok,
        created=rep.created,
        updated=rep.updated,
        row_errors=rep.row_errors,
        preview=rep.preview,
        summary=rep.summary,
    )


@router.get("/onboarding-status")
async def onboarding_status(request: Request) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    db = request.app.state.db
    async with db.session() as session:
        rep = await build_readiness_report(session, settings=settings)
    # Onboarding status is the same report; operators can filter by onboarding_ok.
    return rep.to_dict()


@router.get("/execution-readiness")
async def execution_readiness(request: Request) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    db = request.app.state.db
    async with db.session() as session:
        rep = await build_readiness_report(session, settings=settings)
    return rep.to_dict()


@router.get("/missing-sessions")
async def missing_sessions(request: Request) -> list[dict[str, object]]:
    settings: Settings = request.app.state.settings
    db = request.app.state.db
    async with db.session() as session:
        rep = await build_readiness_report(session, settings=settings)
    out = []
    for r in rep.rows:
        if r.active and r.missing_sessions:
            out.append({"client_id": r.client_id, "gstin": r.gstin, "client_name": r.client_name})
    return out


@router.get("/missing-selectors")
async def missing_selectors(request: Request) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    db = request.app.state.db
    async with db.session() as session:
        rep = await build_readiness_report(session, settings=settings)
    global_missing: set[str] = set()
    per_client: list[dict[str, object]] = []
    for r in rep.rows:
        if r.missing_selectors:
            per_client.append(
                {"client_id": r.client_id, "gstin": r.gstin, "client_name": r.client_name, "missing": r.missing_selectors}
            )
            global_missing.update(r.missing_selectors)
    return {"missing_any": sorted(global_missing), "per_client": per_client}


@router.get("/failed-imports")
async def failed_imports(request: Request) -> list[dict[str, object]]:
    settings: Settings = request.app.state.settings
    db = request.app.state.db
    async with db.session() as session:
        rep = await build_readiness_report(session, settings=settings)
    out: list[dict[str, object]] = []
    for r in rep.rows:
        if not r.onboarding_ok:
            out.append({"client_id": r.client_id, "gstin": r.gstin, "client_name": r.client_name, "blockers": r.blockers})
    return out
