from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.orchestration.job_transition import JobTransition


@dataclass(frozen=True, slots=True)
class TransitionRepo:
    session: AsyncSession

    async def next_seq(self, job_id: uuid.UUID) -> int:
        res = await self.session.execute(
            select(func.coalesce(func.max(JobTransition.seq_no), 0)).where(JobTransition.job_id == job_id)
        )
        return int(res.scalar_one()) + 1

    async def append(
        self,
        *,
        job_id: uuid.UUID,
        from_state: str,
        to_state: str,
        reason_code: str,
        reason_details: dict[str, object],
        actor: str,
        trace_id: str,
        correlation_id: str,
        run_id: str,
    ) -> JobTransition:
        seq = await self.next_seq(job_id)
        row = JobTransition(
            job_id=job_id,
            seq_no=seq,
            from_state=from_state,
            to_state=to_state,
            reason_code=reason_code,
            reason_details_json=json.dumps(reason_details, sort_keys=True, separators=(",", ":")),
            actor=actor,
            trace_id=trace_id,
            correlation_id=correlation_id,
            run_id=run_id,
            created_at=datetime.now(UTC),
        )
        self.session.add(row)
        await self.session.flush()
        return row

