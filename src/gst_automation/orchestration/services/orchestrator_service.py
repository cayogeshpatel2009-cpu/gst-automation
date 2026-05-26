from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.orchestration.dto import JobCreate
from gst_automation.orchestration.router import QueueRouter
from gst_automation.orchestration.services.audit_service import AuditService
from gst_automation.orchestration.services.job_service import JobService
from gst_automation.orchestration.services.transition_service import TransitionService
from gst_automation.orchestration.events import EventContext
from gst_automation.orchestration.ids import new_correlation_id, new_run_id, new_trace_id


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class OrchestratorService:
    """Orchestrates durable jobs onto Celery queues (no business logic)."""

    session: AsyncSession
    celery: Celery
    router: QueueRouter = QueueRouter()

    async def create_and_enqueue(self, create: JobCreate, *, actor: str) -> uuid.UUID:
        job_svc = JobService(self.session)
        audit = AuditService(self.session)
        job = await job_svc.create_job(create, actor=actor)

        # Durable transition: pending -> queued
        routed_queue = self.router.route(kind=job.kind, requested_queue=create.queue, priority=create.priority)
        ctx = EventContext(actor=actor, trace_id=new_trace_id(), correlation_id=new_correlation_id(), run_id=new_run_id())
        ts = TransitionService(self.session)
        await ts.transition(
            job_id=job.id,
            to_state="queued",
            reason_code="job_enqueued",
            reason_details={"queue": routed_queue, "priority": job.priority},
            ctx=ctx,
            next_run_at=job.next_run_at,
        )
        await audit.record(
            event_type="job.queued",
            actor=actor,
            client_id=create.client_id,
            details={"job_id": str(job.id), "queue": routed_queue, "priority": job.priority},
        )
        await self.session.flush()

        eta_seconds = 0
        if job.next_run_at:
            eta_seconds = max(int((job.next_run_at - datetime.now(UTC)).total_seconds()), 0)

        self.celery.send_task(
            "gst_automation.celery_app.tasks.job_runner.run_job",
            args=[str(job.id)],
            queue=routed_queue,
            priority=job.priority,
            countdown=eta_seconds,
        )
        logger.info("job.enqueued", job_id=str(job.id), queue=routed_queue, priority=job.priority)
        return job.id
