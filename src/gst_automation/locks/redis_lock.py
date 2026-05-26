from __future__ import annotations

import secrets

import redis.asyncio as redis

from gst_automation.locks.base import LockHandle, LockManager
from gst_automation.observability.metrics import LOCK_ACQUIRE_TOTAL


class RedisLockManager(LockManager):
    """Redis-based distributed locks using SET NX PX with token ownership."""

    def __init__(self, client: redis.Redis) -> None:
        self._r = client

    async def acquire(self, *, name: str, owner: str, ttl_seconds: int) -> LockHandle | None:
        token = f"{owner}:{secrets.token_hex(16)}"
        key = f"lock:{name}"
        ok = await self._r.set(key, token, nx=True, ex=ttl_seconds)
        if not ok:
            LOCK_ACQUIRE_TOTAL.labels(result="contended").inc()
            return None
        LOCK_ACQUIRE_TOTAL.labels(result="acquired").inc()
        return LockHandle(name=name, token=token, owner=owner)

    async def renew(self, handle: LockHandle, *, ttl_seconds: int) -> bool:
        key = f"lock:{handle.name}"
        lua = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
          return redis.call("expire", KEYS[1], ARGV[2])
        else
          return 0
        end
        """
        res = await self._r.eval(lua, 1, key, handle.token, int(ttl_seconds))
        return int(res) == 1

    async def release(self, handle: LockHandle) -> bool:
        key = f"lock:{handle.name}"
        lua = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
          return redis.call("del", KEYS[1])
        else
          return 0
        end
        """
        res = await self._r.eval(lua, 1, key, handle.token)
        return int(res) == 1
