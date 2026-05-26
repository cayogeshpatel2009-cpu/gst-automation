from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from celery import Celery
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.db.models.orchestration.job import Job
from gst_automation.db.models.validation.validation_run import ValidationRun, ValidationRunJob
from gst_automation.orchestration.dto import JobCreate, JobPriority
from gst_automation.orchestration.services.orchestrator_service import OrchestratorService
from gst_automation.validation.dto import PortalSmokePayload


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ValidationRunService:
    session: AsyncSession
    celery: Celery

    async def create_run(
        self,
        *,
        run_kind: str,
        scenario: str,
        config: dict[str, object],
    ) -> uuid.UUID:
        run = ValidationRun(
            run_kind=run_kind,
            scenario=scenario,
            status="running",
            config_json=json.dumps(config, sort_keys=True, separators=(",", ":")),
            summary_json="{}",
            jobs_total=0,
            jobs_completed=0,
            jobs_failed=0,
        )
        self.session.add(run)
        await self.session.flush()
        return run.id

    async def attach_job(self, *, run_id: uuid.UUID, job_id: uuid.UUID) -> None:
        row = ValidationRunJob(run_id=run_id, job_id=job_id)
        self.session.add(row)
        await self.session.execute(
            ValidationRun.__table__.update()
            .where(ValidationRun.id == run_id)
            .values(jobs_total=ValidationRun.jobs_total + 1)
        )

    async def enqueue_portal_smoke(
        self,
        *,
        run_id: uuid.UUID,
        payload: PortalSmokePayload,
        queue: str = "downloads",
        priority: int = JobPriority.P2_DOWNLOAD,
        actor: str = "validation_cli",
    ) -> uuid.UUID:
        create = JobCreate(kind="portal_smoke", queue=queue, priority=priority, payload=payload.model_dump())
        orch = OrchestratorService(session=self.session, celery=self.celery)
        job_id = await orch.create_and_enqueue(create, actor=actor)
        await self.attach_job(run_id=run_id, job_id=job_id)
        return job_id

    async def refresh_run_counters(self, *, run_id: uuid.UUID) -> dict[str, int]:
        res = await self.session.execute(
            select(
                func.count(Job.id),
                func.sum(func.case((Job.state == "completed", 1), else_=0)),
                func.sum(func.case((Job.state.in_(["failed", "dead_letter"]), 1), else_=0)),
            )
            .select_from(ValidationRunJob)
            .join(Job, Job.id == ValidationRunJob.job_id)
            .where(ValidationRunJob.run_id == run_id)
        )
        total, completed, failed = res.one()
        out = {"total": int(total or 0), "completed": int(completed or 0), "failed": int(failed or 0)}
        await self.session.execute(
            ValidationRun.__table__.update()
            .where(ValidationRun.id == run_id)
            .values(jobs_total=out["total"], jobs_completed=out["completed"], jobs_failed=out["failed"])
        )
        return out

    async def maybe_finish_run(self, *, run_id: uuid.UUID, grace_seconds: int = 0) -> None:
        counts = await self.refresh_run_counters(run_id=run_id)
        if counts["total"] > 0 and counts["completed"] + counts["failed"] >= counts["total"]:
            ended = datetime.now(UTC) + timedelta(seconds=grace_seconds)
            await self.session.execute(
                ValidationRun.__table__.update()
                .where(ValidationRun.id == run_id)
                .values(status="finished", ended_at=ended)
            )
            logger.info("validation.run_finished", run_id=str(run_id), **counts)

