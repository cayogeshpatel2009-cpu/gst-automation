from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.exceptions import GstAutomationError
from gst_automation.core.logging import get_logger
from gst_automation.db.models.orchestration.job import Job
from gst_automation.db.models.orchestration.job_attempt import JobAttempt
from gst_automation.db.models.orchestration.job_lease import JobLease
from gst_automation.orchestration.dto import JobCreate
from gst_automation.orchestration.events import EventContext
from gst_automation.orchestration.ids import new_correlation_id, new_run_id, new_trace_id
from gst_automation.orchestration.repositories.attempt_repo import AttemptRepo
from gst_automation.orchestration.repositories.job_repo import JobRepo
from gst_automation.orchestration.repositories.lease_repo import LeaseRepo
from gst_automation.orchestration.repositories.worker_repo import WorkerRepo
from gst_automation.orchestration.services.audit_service import AuditService
from gst_automation.orchestration.services.transition_service import TransitionService


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class JobService:
    """Core job lifecycle service (DB durable, idempotent, audited)."""

    session: AsyncSession

    async def create_job(self, create: JobCreate, *, actor: str) -> Job:
        repo = JobRepo(self.session)
        audit = AuditService(self.session)
        # A job gets a stable trace/correlation/run at first creation; subsequent transitions reuse it.
        ctx = EventContext(
            actor=actor, trace_id=new_trace_id(), correlation_id=new_correlation_id(), run_id=new_run_id()
        )
        job = Job(
            client_id=create.client_id,
            kind=create.kind,
            payload_json=create.payload_json(),
            state="pending",
            queue=create.queue,
            priority=create.priority,
            idempotency_key=create.idempotency_key,
            next_run_at=datetime.now(UTC),
        )
        await repo.create(job=job)
        ts = TransitionService(self.session)
        # Create -> pending is implicit; first persisted transition is pending->queued when enqueued.
        await audit.record(
            event_type="job.created",
            actor=actor,
            client_id=create.client_id,
            details={"job_id": str(job.id), "kind": job.kind, "queue": job.queue, "priority": job.priority},
        )
        logger.info("job.created", job_id=str(job.id), kind=job.kind, queue=job.queue, priority=job.priority)
        return job

    async def acquire_lease(
        self,
        *,
        job_id: uuid.UUID,
        worker_name: str,
        ttl_seconds: int = 60,
        actor: str,
    ) -> tuple[JobLease, JobAttempt]:
        job_repo = JobRepo(self.session)
        lease_repo = LeaseRepo(self.session)
        attempt_repo = AttemptRepo(self.session)
        audit = AuditService(self.session)
        # Attempt ids become the primary correlation surface for execution.

        job = await job_repo.get(job_id)
        if job is None:
            raise GstAutomationError(f"Job not found: {job_id}")

        lease_token = f"lease_{uuid.uuid4()}"
        worker_generation = await WorkerRepo(self.session).get_generation(worker_name=worker_name)
        lease = await lease_repo.upsert(
            job_id=job_id,
            worker_name=worker_name,
            worker_generation=worker_generation,
            lease_token=lease_token,
            ttl_seconds=ttl_seconds,
        )

        attempt_no = await attempt_repo.next_attempt_no(job_id)
        attempt = JobAttempt(
            job_id=job_id,
            attempt_no=attempt_no,
            status="running",
            worker_name=worker_name,
            lease_token=lease_token,
            trace_id=new_trace_id(),
            correlation_id=new_correlation_id(),
            run_id=new_run_id(),
        )
        await attempt_repo.start_attempt(attempt)

        ctx = EventContext(
            actor=actor,
            trace_id=attempt.trace_id,
            correlation_id=attempt.correlation_id,
            run_id=attempt.run_id,
        )

        ts = TransitionService(self.session)
        await ts.transition(
            job_id=job_id,
            to_state="leased",
            reason_code="lease_acquired",
            reason_details={"worker_name": worker_name},
            ctx=ctx,
            next_run_at=None,
        )

        await audit.record(
            event_type="job.leased",
            actor=actor,
            client_id=job.client_id,
            details={"job_id": str(job_id), "worker_name": worker_name, "lease_token": lease_token},
        )
        return lease, attempt

    async def heartbeat_lease(self, *, job_id: uuid.UUID, lease_token: str, ttl_seconds: int = 60) -> bool:
        repo = LeaseRepo(self.session)
        token = await repo.heartbeat(job_id=job_id, lease_token=lease_token, ttl_seconds=ttl_seconds)
        return token is not None

    async def complete_job(
        self,
        *,
        job_id: uuid.UUID,
        attempt_id: uuid.UUID,
        lease_token: str,
        fencing_token: int,
        actor: str,
        ctx: EventContext | None = None,
    ) -> None:
        job_repo = JobRepo(self.session)
        attempt_repo = AttemptRepo(self.session)
        lease_repo = LeaseRepo(self.session)
        audit = AuditService(self.session)

        current_fence = await lease_repo.get_fencing_token(job_id=job_id, lease_token=lease_token)
        if current_fence is None or current_fence != fencing_token:
            raise GstAutomationError("Fencing token mismatch (stale worker cannot commit)")
        ident = await lease_repo.get_worker_identity(job_id=job_id, lease_token=lease_token)
        if ident is None:
            raise GstAutomationError("Lease missing (stale worker cannot commit)")
        lease_worker_name, lease_generation = ident
        current_generation = await WorkerRepo(self.session).get_generation(worker_name=lease_worker_name)
        if current_generation != lease_generation:
            raise GstAutomationError("Worker generation mismatch (stale worker cannot commit)")

        job = await job_repo.get(job_id)
        use_ctx = ctx or EventContext(
            actor=actor, trace_id=new_trace_id(), correlation_id=new_correlation_id(), run_id=new_run_id()
        )
        ts = TransitionService(self.session)
        await ts.transition(
            job_id=job_id,
            to_state="completed",
            reason_code="job_succeeded",
            reason_details={},
            ctx=use_ctx,
        )
        await attempt_repo.finish_attempt(
            attempt_id=attempt_id,
            status="completed",
            error_class=None,
            error_message=None,
            error_details_json=None,
        )
        await lease_repo.clear(job_id=job_id, lease_token=lease_token)
        await audit.record(
            event_type="job.completed",
            actor=actor,
            client_id=job.client_id if job else None,
            details={"job_id": str(job_id), "attempt_id": str(attempt_id)},
        )

    async def schedule_retry(
        self,
        *,
        job_id: uuid.UUID,
        attempt_id: uuid.UUID,
        lease_token: str,
        fencing_token: int,
        backoff_seconds: int,
        actor: str,
        ctx: EventContext | None = None,
    ) -> datetime:
        job_repo = JobRepo(self.session)
        attempt_repo = AttemptRepo(self.session)
        lease_repo = LeaseRepo(self.session)
        audit = AuditService(self.session)

        current_fence = await lease_repo.get_fencing_token(job_id=job_id, lease_token=lease_token)
        if current_fence is None or current_fence != fencing_token:
            raise GstAutomationError("Fencing token mismatch (stale worker cannot schedule retry)")
        ident = await lease_repo.get_worker_identity(job_id=job_id, lease_token=lease_token)
        if ident is None:
            raise GstAutomationError("Lease missing (stale worker cannot schedule retry)")
        lease_worker_name, lease_generation = ident
        current_generation = await WorkerRepo(self.session).get_generation(worker_name=lease_worker_name)
        if current_generation != lease_generation:
            raise GstAutomationError("Worker generation mismatch (stale worker cannot schedule retry)")

        job = await job_repo.get(job_id)
        retry_at = datetime.now(UTC) + timedelta(seconds=backoff_seconds)
        use_ctx = ctx or EventContext(
            actor=actor, trace_id=new_trace_id(), correlation_id=new_correlation_id(), run_id=new_run_id()
        )
        ts = TransitionService(self.session)
        await ts.transition(
            job_id=job_id,
            to_state="retrying",
            reason_code="retry_scheduled",
            reason_details={"retry_at": retry_at.isoformat()},
            ctx=use_ctx,
            next_run_at=retry_at,
        )
        await attempt_repo.finish_attempt(
            attempt_id=attempt_id,
            status="retrying",
            error_class=None,
            error_message=None,
            error_details_json=None,
        )
        await lease_repo.clear(job_id=job_id, lease_token=lease_token)
        await audit.record(
            event_type="job.retry_scheduled",
            actor=actor,
            client_id=job.client_id if job else None,
            details={"job_id": str(job_id), "attempt_id": str(attempt_id), "retry_at": retry_at.isoformat()},
        )
        return retry_at
