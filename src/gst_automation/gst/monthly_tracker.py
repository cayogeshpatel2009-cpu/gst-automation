from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.gst.monthly_tracker import GstMonthlyExecution


@dataclass(frozen=True, slots=True)
class MonthlyTrackerService:
    session: AsyncSession

    async def get(self, *, client_id: uuid.UUID, period: str) -> GstMonthlyExecution | None:
        res = await self.session.execute(
            select(GstMonthlyExecution).where(GstMonthlyExecution.client_id == client_id).where(GstMonthlyExecution.period == period)
        )
        return res.scalars().first()

    async def upsert(
        self,
        *,
        client_id: uuid.UUID,
        period: str,
        status: str,
        job_id: uuid.UUID | None,
        details: dict[str, object] | None = None,
    ) -> GstMonthlyExecution:
        row = await self.get(client_id=client_id, period=period)
        payload = json.dumps(details or {}, sort_keys=True, separators=(",", ":"))
        if row is None:
            row = GstMonthlyExecution(
                client_id=client_id,
                period=period,
                status=status,
                job_id=job_id,
                details_json=payload,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            self.session.add(row)
            try:
                await self.session.flush()
            except IntegrityError:
                # Lost the race; refetch.
                row = await self.get(client_id=client_id, period=period)
                if row is None:
                    raise
        else:
            row.status = status
            row.job_id = job_id
            row.details_json = payload
            row.updated_at = datetime.now(UTC)
            await self.session.flush()
        return row

