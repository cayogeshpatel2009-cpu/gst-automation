from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.orchestration.dead_letter import DeadLetterJob


@dataclass(frozen=True, slots=True)
class DlqRepo:
    session: AsyncSession

    async def add(self, dlq: DeadLetterJob) -> DeadLetterJob:
        self.session.add(dlq)
        await self.session.flush()
        return dlq

    async def get(self, dlq_id: uuid.UUID) -> DeadLetterJob | None:
        res = await self.session.execute(select(DeadLetterJob).where(DeadLetterJob.id == dlq_id))
        return res.scalar_one_or_none()
