from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

from gst_automation.celery_app.client import get_celery
from gst_automation.orchestration.services.dlq_replay_service import DlqReplayService


router = APIRouter(prefix="/orchestration/dlq", tags=["orchestration"])


@router.post("/{dlq_id}/replay")
async def replay_dlq(request: Request, dlq_id: str) -> dict[str, str]:
    try:
        parsed = uuid.UUID(dlq_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid dlq_id") from exc
    db = request.app.state.db
    celery = get_celery()
    async with db.session() as session:
        svc = DlqReplayService(session=session, celery=celery)
        job_id = await svc.replay(dlq_id=parsed, actor="api")
        await session.commit()
    return {"job_id": str(job_id)}

