from __future__ import annotations

from fastapi import APIRouter, Request

from gst_automation.celery_app.client import get_celery
from gst_automation.orchestration.dto import JobCreate
from gst_automation.orchestration.services.orchestrator_service import OrchestratorService


router = APIRouter(prefix="/orchestration", tags=["orchestration"])


@router.post("/jobs")
async def create_job(request: Request, payload: JobCreate) -> dict[str, str]:
    db = request.app.state.db
    celery = get_celery()
    async with db.session() as session:
        svc = OrchestratorService(session=session, celery=celery)
        job_id = await svc.create_and_enqueue(payload, actor="api")
        await session.commit()
    return {"job_id": str(job_id)}

