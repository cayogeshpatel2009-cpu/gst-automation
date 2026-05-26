from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.orchestration.distributed_lock import DistributedLock
from gst_automation.locks.base import LockHandle, LockManager


@dataclass(frozen=True, slots=True)
class DbLockManager(LockManager):
    """PostgreSQL-backed lock fallback using a single-row-per-lock approach."""

    session: AsyncSession

    async def acquire(self, *, name: str, owner: str, ttl_seconds: int) -> LockHandle | None:
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        token = f"{owner}:{secrets.token_hex(16)}"

        # Single-row semantics. Races are resolved by unique PK constraint on name.
        res = await self.session.execute(select(DistributedLock).where(DistributedLock.name == name))
        row = res.scalar_one_or_none()
        if row is None:
            self.session.add(
                DistributedLock(
                    name=name,
                    owner_name=owner,
                    token=token,
                    acquired_at=now,
                    renewed_at=now,
                    expires_at=expires_at,
                )
            )
            await self.session.flush()
            return LockHandle(name=name, token=token, owner=owner)

        if row.expires_at <= now:
            row.owner_name = owner
            row.token = token
            row.renewed_at = now
            row.expires_at = expires_at
            await self.session.flush()
            return LockHandle(name=name, token=token, owner=owner)

        return None

    async def renew(self, handle: LockHandle, *, ttl_seconds: int) -> bool:
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        res = await self.session.execute(select(DistributedLock).where(DistributedLock.name == handle.name))
        row = res.scalar_one_or_none()
        if row is None or row.token != handle.token:
            return False
        row.renewed_at = now
        row.expires_at = expires_at
        await self.session.flush()
        return True

    async def release(self, handle: LockHandle) -> bool:
        res = await self.session.execute(select(DistributedLock).where(DistributedLock.name == handle.name))
        row = res.scalar_one_or_none()
        if row is None or row.token != handle.token:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

