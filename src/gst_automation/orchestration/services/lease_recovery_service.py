from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.orchestration.job import Job
from gst_automation.db.models.orchestration.job_lease import JobLease
from gst_automation.orchestration.repositories.job_repo import JobRepo
from gst_automation.orchestration.services.transition_service import TransitionService
from gst_automation.orchestration.events import EventContext
from gst_automation.orchestration.ids import new_correlation_id, new_run_id, new_trace_id


@dataclass(frozen=True, slots=True)
class LeaseRecoveryService:
    session: AsyncSession

    async def find_expired_job_ids(self, *, limit: int = 200) -> list[uuid.UUID]:
        now = datetime.now(UTC)
        res = await self.session.execute(
            select(JobLease.job_id).where(JobLease.expires_at < now).limit(limit)
        )
        return [r[0] for r in res.all()]

    async def reclaim_expired_job(self, *, job_id: uuid.UUID) -> bool:
        # Requeue any job that was leased/running but lost its lease.
        ctx = EventContext(actor="watchdog", trace_id=new_trace_id(), correlation_id=new_correlation_id(), run_id=new_run_id())
        ts = TransitionService(self.session)
        await ts.transition(
            job_id=job_id,
            to_state="queued",
            reason_code="lease_expired_recovered",
            reason_details={},
            ctx=ctx,
            next_run_at=datetime.now(UTC),
        )
        return True
