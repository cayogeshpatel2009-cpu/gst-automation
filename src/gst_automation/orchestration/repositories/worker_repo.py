from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.orchestration.worker import Worker
from gst_automation.db.models.orchestration.worker_heartbeat import WorkerHeartbeat


@dataclass(frozen=True, slots=True)
class WorkerRepo:
    session: AsyncSession

    async def upsert_worker(self, *, worker_name: str, hostname: str, pid: int, queues: list[str]) -> Worker:
        res = await self.session.execute(select(Worker).where(Worker.worker_name == worker_name))
        existing = res.scalar_one_or_none()
        now = datetime.now(UTC)
        if existing is None:
            w = Worker(
                worker_name=worker_name,
                generation=1,
                hostname=hostname,
                pid=pid,
                queues_json=json.dumps(sorted(set(queues))),
                status="online",
                started_at=now,
                last_heartbeat_at=now,
            )
            self.session.add(w)
            await self.session.flush()
            return w
        if existing.pid != pid:
            existing.generation = int(existing.generation) + 1
        existing.hostname = hostname
        existing.pid = pid
        existing.queues_json = json.dumps(sorted(set(queues)))
        existing.status = "online"
        existing.last_heartbeat_at = now
        await self.session.flush()
        return existing

    async def get_generation(self, *, worker_name: str) -> int:
        res = await self.session.execute(select(Worker.generation).where(Worker.worker_name == worker_name))
        val = res.scalar_one_or_none()
        return int(val) if val is not None else 0

    async def append_heartbeat(
        self,
        *,
        worker_name: str,
        cpu_percent: int,
        memory_rss_bytes: int,
        active_jobs: int,
        health_state: str,
    ) -> None:
        hb = WorkerHeartbeat(
            worker_name=worker_name,
            cpu_percent=cpu_percent,
            memory_rss_bytes=memory_rss_bytes,
            active_jobs=active_jobs,
            health_state=health_state,
        )
        self.session.add(hb)
        await self.session.flush()
