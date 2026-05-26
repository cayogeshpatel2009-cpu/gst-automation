from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from gst_automation.gst.selector_promotion import SelectorPromotionService


router = APIRouter(prefix="/gst/selectors", tags=["gst"])


class PromoteRequest(BaseModel):
    semantic_key: str = Field(min_length=1, max_length=128)
    selectors: list[str] = Field(min_length=1)
    activate: bool = False


@router.get("/observed/{observation_id}")
async def observed_selectors(request: Request, observation_id: str) -> list[dict[str, object]]:
    settings = request.app.state.settings
    db = request.app.state.db
    oid = uuid.UUID(observation_id)
    async with db.session() as session:
        rows = await SelectorPromotionService(settings=settings).list_observed(session, observation_id=oid)
    return [{"selector": r.selector, "count": r.count, "score": r.score, "reasons": r.reasons} for r in rows]


@router.post("/promote")
async def promote_selector(request: Request, payload: PromoteRequest) -> dict[str, object]:
    settings = request.app.state.settings
    db = request.app.state.db
    async with db.session() as session:
        sid = await SelectorPromotionService(settings=settings).promote(
            session,
            semantic_key=payload.semantic_key,
            selectors=payload.selectors,
            activate=payload.activate,
        )
        await session.commit()
    return {"id": str(sid)}

