from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from gst_automation.db.models.orchestration.event import OrchestrationEvent


router = APIRouter(prefix="/orchestration", tags=["orchestration"])


@router.get("/events")
async def list_events(
    request: Request,
    job_id: str | None = None,
    correlation_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, object]]:
    db = request.app.state.db
    stmt = select(OrchestrationEvent).order_by(OrchestrationEvent.created_at.desc()).limit(limit)
    if job_id:
        try:
            parsed = uuid.UUID(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid job_id") from exc
        stmt = stmt.where(OrchestrationEvent.job_id == parsed)
    if correlation_id:
        stmt = stmt.where(OrchestrationEvent.correlation_id == correlation_id)

    async with db.session() as session:
        res = await session.execute(stmt)
        rows = list(res.scalars().all())
    return [
        {
            "id": str(r.id),
            "event_type": r.event_type,
            "schema_version": r.schema_version,
            "job_id": str(r.job_id) if r.job_id else None,
            "client_id": str(r.client_id) if r.client_id else None,
            "trace_id": r.trace_id,
            "correlation_id": r.correlation_id,
            "run_id": r.run_id,
            "actor": r.actor,
            "payload_json": r.payload_json,
            "metadata_json": r.metadata_json,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]

