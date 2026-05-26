from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

from gst_automation.orchestration.repositories.job_repo import JobRepo


router = APIRouter(prefix="/orchestration", tags=["orchestration"])


@router.get("/jobs/{job_id}")
async def get_job(request: Request, job_id: str) -> dict[str, object]:
    try:
        parsed = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid job_id") from exc
    db = request.app.state.db
    async with db.session() as session:
        repo = JobRepo(session)
        job = await repo.get(parsed)
        if job is None:
            raise HTTPException(status_code=404, detail="not found")
        return {
            "id": str(job.id),
            "kind": job.kind,
            "client_id": str(job.client_id) if job.client_id else None,
            "state": job.state,
            "queue": job.queue,
            "priority": job.priority,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "next_run_at": job.next_run_at.isoformat() if job.next_run_at else None,
        }

