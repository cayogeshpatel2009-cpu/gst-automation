from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.db.models.orchestration.job import Job


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ExecutionWaitResult:
    completed: list[uuid.UUID]
    failed: list[uuid.UUID]
    still_running: list[uuid.UUID]


@dataclass(frozen=True, slots=True)
class ValidationExecutor:
    """DB-polling executor for orchestration jobs (no Celery result dependency)."""

    async def wait_for_jobs(
        self,
        session: AsyncSession,
        *,
        job_ids: list[uuid.UUID],
        timeout_seconds: int = 600,
        poll_seconds: float = 2.0,
    ) -> ExecutionWaitResult:
        deadline = datetime.now(UTC) + timedelta(seconds=timeout_seconds)
        pending = set(job_ids)
        completed: list[uuid.UUID] = []
        failed: list[uuid.UUID] = []

        while pending and datetime.now(UTC) < deadline:
            res = await session.execute(select(Job.id, Job.state).where(Job.id.in_(list(pending))))
            rows = res.all()
            for jid, state in rows:
                if state == "completed":
                    pending.remove(jid)
                    completed.append(jid)
                elif state in {"failed", "dead_letter"}:
                    pending.remove(jid)
                    failed.append(jid)
            await session.commit()
            if pending:
                import asyncio

                await asyncio.sleep(poll_seconds)

        still = list(pending)
        logger.info(
            "validation.wait",
            completed=len(completed),
            failed=len(failed),
            still_running=len(still),
        )
        return ExecutionWaitResult(completed=completed, failed=failed, still_running=still)

