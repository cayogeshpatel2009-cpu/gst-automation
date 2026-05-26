from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from gst_automation.db.models.portal.selector_def import PortalSelectorDef
from gst_automation.db.models.portal.session_blob import PortalSessionBlob


router = APIRouter(prefix="/portal", tags=["portal"])


@router.get("/selectors")
async def list_selectors(request: Request, limit: int = 50) -> list[dict[str, object]]:
    db = request.app.state.db
    async with db.session() as session:
        res = await session.execute(
            select(PortalSelectorDef).order_by(PortalSelectorDef.created_at.desc()).limit(limit)
        )
        rows = list(res.scalars().all())
    return [{"key": r.key, "version": r.version, "active": bool(r.active), "created_at": r.created_at.isoformat()} for r in rows]


@router.get("/sessions")
async def list_sessions(request: Request, limit: int = 50) -> list[dict[str, object]]:
    db = request.app.state.db
    async with db.session() as session:
        res = await session.execute(
            select(PortalSessionBlob).order_by(PortalSessionBlob.created_at.desc()).limit(limit)
        )
        rows = list(res.scalars().all())
    return [
        {
            "id": str(r.id),
            "client_id": str(r.client_id) if r.client_id else None,
            "profile": r.profile,
            "created_at": r.created_at.isoformat(),
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
        }
        for r in rows
    ]

