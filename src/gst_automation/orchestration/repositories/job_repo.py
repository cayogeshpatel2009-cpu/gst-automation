from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.exceptions import StorageError
from gst_automation.db.models.orchestration.job import Job


@dataclass(frozen=True, slots=True)
class JobRepo:
    session: AsyncSession

    async def create(self, *, job: Job) -> Job:
        self.session.add(job)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise StorageError("Job create failed (idempotency conflict?)") from exc
        return job

    async def get(self, job_id: uuid.UUID) -> Job | None:
        res = await self.session.execute(select(Job).where(Job.id == job_id))
        return res.scalar_one_or_none()

    async def set_state(
        self,
        *,
        job_id: uuid.UUID,
        from_states: set[str],
        to_state: str,
        next_run_at: datetime | None = None,
    ) -> bool:
        stmt = (
            update(Job)
            .where(Job.id == job_id)
            .where(Job.state.in_(from_states))
            .values(state=to_state, updated_at=datetime.now(UTC), next_run_at=next_run_at)
        )
        result = await self.session.execute(stmt)
        return (result.rowcount or 0) == 1

    async def find_runnable(
        self, *, now: datetime, limit: int = 200, states: set[str] | None = None
    ) -> list[Job]:
        target_states = states or {"queued", "retrying"}
        stmt = (
            select(Job)
            .where(Job.state.in_(target_states))
            .where((Job.next_run_at.is_(None)) | (Job.next_run_at <= now))
            .order_by(Job.priority.asc(), Job.created_at.asc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
