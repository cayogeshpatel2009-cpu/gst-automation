from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from gst_automation.gst.operator_checkpoints import OperatorCheckpointService


router = APIRouter(prefix="/operator", tags=["operator"])


class ResolveCheckpoint(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")
    resolved_by: str = Field(min_length=1, max_length=128)


@router.get("/checkpoints")
async def list_pending_checkpoints(request: Request, limit: int = 50) -> list[dict[str, object]]:
    db = request.app.state.db
    async with db.session() as session:
        rows = await OperatorCheckpointService(session).list_pending(limit=limit)
    return [
        {
            "id": str(r.id),
            "job_id": str(r.job_id),
            "context_id": str(r.context_id) if r.context_id else None,
            "kind": r.kind,
            "status": r.status,
            "instructions": r.instructions,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/checkpoints/{checkpoint_id}/resolve")
async def resolve_checkpoint(request: Request, checkpoint_id: str, payload: ResolveCheckpoint) -> dict[str, object]:
    db = request.app.state.db
    cid = uuid.UUID(checkpoint_id)
    async with db.session() as session:
        ok = await OperatorCheckpointService(session).resolve(
            checkpoint_id=cid, status=payload.status, resolved_by=payload.resolved_by
        )
        await session.commit()
    return {"ok": ok}

