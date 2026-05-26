from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.exceptions import GstAutomationError
from gst_automation.db.models.orchestration.job import Job
from gst_automation.orchestration.events import EventContext, EventPublisher
from gst_automation.orchestration.fsm import JobStateMachine
from gst_automation.orchestration.repositories.transition_repo import TransitionRepo
from gst_automation.observability.metrics import JOB_TRANSITIONS_TOTAL


class ConcurrencyConflict(GstAutomationError):
    """Raised when optimistic concurrency detects a competing writer."""


@dataclass(frozen=True, slots=True)
class TransitionService:
    """Atomic job state transitions with FSM validation + immutable transition history + events."""

    session: AsyncSession
    fsm: JobStateMachine = JobStateMachine()

    async def transition(
        self,
        *,
        job_id: uuid.UUID,
        to_state: str,
        reason_code: str,
        reason_details: dict[str, object],
        ctx: EventContext,
        expected_version: int | None = None,
        next_run_at: datetime | None = None,
    ) -> Job:
        # Lock row for consistent from_state/version read.
        res = await self.session.execute(select(Job).where(Job.id == job_id).with_for_update())
        job = res.scalar_one_or_none()
        if job is None:
            raise GstAutomationError(f"Job not found: {job_id}")

        if expected_version is not None and job.version != expected_version:
            raise ConcurrencyConflict("Job version mismatch")

        from_state = job.state
        self.fsm.assert_allowed(from_state=from_state, to_state=to_state)

        now = datetime.now(UTC)
        # Optimistic concurrency: version increments on every state change.
        stmt = (
            update(Job)
            .where(Job.id == job_id)
            .where(Job.version == job.version)
            .values(
                state=to_state,
                version=job.version + 1,
                updated_at=now,
                state_updated_at=now,
                next_run_at=next_run_at,
            )
        )
        result = await self.session.execute(stmt)
        if (result.rowcount or 0) != 1:
            raise ConcurrencyConflict("Competing job transition detected")

        # Append immutable transition row and outbox event.
        t_repo = TransitionRepo(self.session)
        await t_repo.append(
            job_id=job_id,
            from_state=from_state,
            to_state=to_state,
            reason_code=reason_code,
            reason_details=reason_details,
            actor=ctx.actor,
            trace_id=ctx.trace_id,
            correlation_id=ctx.correlation_id,
            run_id=ctx.run_id,
        )

        publisher = EventPublisher(self.session)
        await publisher.publish(
            event_type=f"job.{to_state}",
            job_id=job_id,
            client_id=job.client_id,
            payload={"from_state": from_state, "to_state": to_state, "reason_code": reason_code},
            metadata={"reason_details": reason_details},
            ctx=ctx,
        )
        JOB_TRANSITIONS_TOTAL.labels(from_state=from_state, to_state=to_state, reason_code=reason_code).inc()

        # Refresh in-memory job snapshot.
        job.state = to_state
        job.version = job.version + 1
        job.updated_at = now
        job.state_updated_at = now
        job.next_run_at = next_run_at
        return job
