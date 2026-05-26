from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from gst_automation.db.models.browser.browser_context import BrowserContextRecord
from gst_automation.db.models.browser.browser_instance import BrowserInstance


router = APIRouter(prefix="/browser", tags=["browser"])


@router.get("/instances")
async def list_instances(request: Request, limit: int = 50) -> list[dict[str, object]]:
    db = request.app.state.db
    async with db.session() as session:
        res = await session.execute(
            select(BrowserInstance).order_by(BrowserInstance.created_at.desc()).limit(limit)
        )
        rows = list(res.scalars().all())
    return [
        {
            "id": str(r.id),
            "worker_name": r.worker_name,
            "worker_generation": r.worker_generation,
            "state": r.state,
            "browser_type": r.browser_type,
            "created_at": r.created_at.isoformat(),
            "last_heartbeat_at": r.last_heartbeat_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/contexts")
async def list_contexts(request: Request, limit: int = 50) -> list[dict[str, object]]:
    db = request.app.state.db
    async with db.session() as session:
        res = await session.execute(
            select(BrowserContextRecord).order_by(BrowserContextRecord.created_at.desc()).limit(limit)
        )
        rows = list(res.scalars().all())
    return [
        {
            "id": str(r.id),
            "browser_id": str(r.browser_id),
            "job_id": str(r.job_id),
            "state": r.state,
            "worker_name": r.worker_name,
            "worker_generation": r.worker_generation,
            "created_at": r.created_at.isoformat(),
            "closed_at": r.closed_at.isoformat() if r.closed_at else None,
        }
        for r in rows
    ]

