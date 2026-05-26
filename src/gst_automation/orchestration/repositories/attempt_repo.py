from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.orchestration.job_attempt import JobAttempt


@dataclass(frozen=True, slots=True)
class AttemptRepo:
    session: AsyncSession

    async def next_attempt_no(self, job_id: uuid.UUID) -> int:
        res = await self.session.execute(
            select(func.coalesce(func.max(JobAttempt.attempt_no), 0)).where(JobAttempt.job_id == job_id)
        )
        return int(res.scalar_one()) + 1

    async def start_attempt(self, attempt: JobAttempt) -> JobAttempt:
        self.session.add(attempt)
        await self.session.flush()
        return attempt

    async def finish_attempt(
        self,
        *,
        attempt_id: uuid.UUID,
        status: str,
        error_class: str | None,
        error_message: str | None,
        error_details_json: str | None,
    ) -> None:
        stmt = (
            update(JobAttempt)
            .where(JobAttempt.id == attempt_id)
            .values(
                status=status,
                finished_at=datetime.now(UTC),
                error_class=error_class,
                error_message=error_message,
                error_details_json=error_details_json,
            )
        )
        await self.session.execute(stmt)

