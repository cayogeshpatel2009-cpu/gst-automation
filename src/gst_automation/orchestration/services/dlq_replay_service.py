from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.orchestration.dto import JobCreate
from gst_automation.orchestration.repositories.dlq_repo import DlqRepo
from gst_automation.orchestration.services.orchestrator_service import OrchestratorService


@dataclass(frozen=True, slots=True)
class DlqReplayService:
    session: AsyncSession
    celery: Celery

    async def replay(self, *, dlq_id: uuid.UUID, actor: str) -> uuid.UUID:
        repo = DlqRepo(self.session)
        row = await repo.get(dlq_id)
        if row is None:
            raise RuntimeError("DLQ entry not found")
        payload = json.loads(row.payload_json)
        create = JobCreate(kind=row.job_kind, payload=payload, queue="downloads", priority=2, idempotency_key=None)
        orchestrator = OrchestratorService(session=self.session, celery=self.celery)
        return await orchestrator.create_and_enqueue(create, actor=actor)

