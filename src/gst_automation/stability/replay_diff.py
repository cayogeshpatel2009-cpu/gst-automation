from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.stability.replay_cert import ReplayDiffReport
from gst_automation.validation.timeline import TimelineService
from gst_automation.core.settings import Settings


@dataclass(frozen=True, slots=True)
class ReplayDiffResult:
    status: str
    diff: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReplayDiffEngine:
    settings: Settings

    async def diff_jobs(
        self,
        session: AsyncSession,
        *,
        left_job_id: uuid.UUID,
        right_job_id: uuid.UUID,
        limit_events: int = 500,
    ) -> ReplayDiffResult:
        ts = TimelineService(settings=self.settings)
        left = await ts.build_for_job(session, job_id=left_job_id)
        right = await ts.build_for_job(session, job_id=right_job_id)

        left_kinds = [e.kind for e in left][-limit_events:]
        right_kinds = [e.kind for e in right][-limit_events:]

        lcp = 0
        for a, b in zip(left_kinds, right_kinds):
            if a != b:
                break
            lcp += 1

        status = "same"
        if left_kinds != right_kinds:
            status = "diverged"
            if lcp >= min(len(left_kinds), len(right_kinds)) * 0.8:
                status = "degraded"

        diff = {
            "left_job_id": str(left_job_id),
            "right_job_id": str(right_job_id),
            "left_events": len(left_kinds),
            "right_events": len(right_kinds),
            "lcp": lcp,
            "left_next": left_kinds[lcp:lcp + 10],
            "right_next": right_kinds[lcp:lcp + 10],
        }
        return ReplayDiffResult(status=status, diff=diff)

    async def record_report(
        self,
        session: AsyncSession,
        *,
        left_job_id: uuid.UUID,
        right_job_id: uuid.UUID,
        result: ReplayDiffResult,
    ) -> ReplayDiffReport:
        row = ReplayDiffReport(
            left_job_id=left_job_id,
            right_job_id=right_job_id,
            status=result.status,
            diff_json=json.dumps(result.diff, sort_keys=True, separators=(",", ":")),
            created_at=datetime.now(UTC),
        )
        session.add(row)
        await session.flush()
        return row

