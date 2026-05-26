from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.orchestration.retry_history import RetryHistory


@dataclass(frozen=True, slots=True)
class RetryRepo:
    session: AsyncSession

    async def add(
        self,
        *,
        job_id: uuid.UUID,
        attempt_id: uuid.UUID | None,
        classification: str,
        backoff_seconds: int,
        jitter_seconds: int,
        reason: str,
    ) -> datetime:
        scheduled = datetime.now(UTC) + timedelta(seconds=backoff_seconds + jitter_seconds)
        row = RetryHistory(
            job_id=job_id,
            attempt_id=attempt_id,
            classification=classification,
            backoff_seconds=backoff_seconds,
            jitter_seconds=jitter_seconds,
            scheduled_at=scheduled,
            reason=reason,
        )
        self.session.add(row)
        await self.session.flush()
        return scheduled

