from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.orchestration.job_lease import JobLease


@dataclass(frozen=True, slots=True)
class LeaseRepo:
    session: AsyncSession

    async def get(self, job_id: uuid.UUID) -> JobLease | None:
        res = await self.session.execute(select(JobLease).where(JobLease.job_id == job_id))
        return res.scalar_one_or_none()

    async def upsert(
        self,
        *,
        job_id: uuid.UUID,
        worker_name: str,
        worker_generation: int,
        lease_token: str,
        ttl_seconds: int,
    ) -> JobLease:
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        existing = await self.get(job_id)
        if existing is None:
            lease = JobLease(
                job_id=job_id,
                worker_name=worker_name,
                worker_generation=worker_generation,
                lease_token=lease_token,
                fencing_token=1,
                acquired_at=now,
                last_heartbeat_at=now,
                expires_at=expires_at,
            )
            self.session.add(lease)
            await self.session.flush()
            return lease
        existing.worker_name = worker_name
        existing.worker_generation = worker_generation
        existing.lease_token = lease_token
        existing.last_heartbeat_at = now
        existing.expires_at = expires_at
        existing.fencing_token = int(existing.fencing_token) + 1
        await self.session.flush()
        return existing

    async def heartbeat(self, *, job_id: uuid.UUID, lease_token: str, ttl_seconds: int) -> int | None:
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        stmt = (
            update(JobLease)
            .where(JobLease.job_id == job_id)
            .where(JobLease.lease_token == lease_token)
            .values(
                last_heartbeat_at=now,
                expires_at=expires_at,
                fencing_token=JobLease.fencing_token + 1,
            )
            .returning(JobLease.fencing_token)
        )
        result = await self.session.execute(stmt)
        row = result.first()
        if row is None:
            return None
        return int(row[0])

    async def clear(self, *, job_id: uuid.UUID, lease_token: str) -> bool:
        stmt = update(JobLease).where(JobLease.job_id == job_id).where(JobLease.lease_token == lease_token).values(
            expires_at=datetime.now(UTC)
        )
        result = await self.session.execute(stmt)
        return (result.rowcount or 0) == 1

    async def get_fencing_token(self, *, job_id: uuid.UUID, lease_token: str) -> int | None:
        res = await self.session.execute(
            select(JobLease.fencing_token, JobLease.worker_name, JobLease.worker_generation)
            .where(JobLease.job_id == job_id)
            .where(JobLease.lease_token == lease_token)
        )
        row = res.first()
        if row is None:
            return None
        return int(row[0])

    async def get_worker_identity(self, *, job_id: uuid.UUID, lease_token: str) -> tuple[str, int] | None:
        res = await self.session.execute(
            select(JobLease.worker_name, JobLease.worker_generation)
            .where(JobLease.job_id == job_id)
            .where(JobLease.lease_token == lease_token)
        )
        row = res.first()
        if row is None:
            return None
        return str(row[0]), int(row[1])
