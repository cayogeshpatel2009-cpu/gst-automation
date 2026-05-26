from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LockHandle:
    name: str
    token: str
    owner: str


class LockManager(Protocol):
    async def acquire(self, *, name: str, owner: str, ttl_seconds: int) -> LockHandle | None: ...
    async def renew(self, handle: LockHandle, *, ttl_seconds: int) -> bool: ...
    async def release(self, handle: LockHandle) -> bool: ...

