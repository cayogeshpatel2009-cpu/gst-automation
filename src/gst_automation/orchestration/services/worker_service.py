from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.orchestration.worker import Worker


@dataclass(frozen=True, slots=True)
class WorkerService:
    session: AsyncSession

    async def mark_stale_workers_offline(self, *, stale_after_seconds: int = 30) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
        stmt = (
            update(Worker)
            .where(Worker.last_heartbeat_at < cutoff)
            .where(Worker.status == "online")
            .values(status="offline")
        )
        res = await self.session.execute(stmt)
        return int(res.rowcount or 0)

