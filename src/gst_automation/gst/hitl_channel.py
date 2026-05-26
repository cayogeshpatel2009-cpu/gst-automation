from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from typing import Any

import redis.asyncio as redis


@dataclass(frozen=True, slots=True)
class OperatorAction:
    kind: str  # type|press|click|approve|reject
    selector: str | None = None
    value: str | None = None
    key: str | None = None
    sensitive: bool = False


@dataclass(frozen=True, slots=True)
class HitlChannel:
    redis_client: redis.Redis
    namespace: str = "hitl"

    def _actions_key(self, checkpoint_id: uuid.UUID) -> str:
        return f"{self.namespace}:checkpoint:{checkpoint_id}:actions"

    async def enqueue_action(self, *, checkpoint_id: uuid.UUID, action: OperatorAction) -> None:
        payload = json.dumps(asdict(action), sort_keys=True, separators=(",", ":"))
        await self.redis_client.rpush(self._actions_key(checkpoint_id), payload)

    async def pop_action(self, *, checkpoint_id: uuid.UUID, timeout_seconds: int = 5) -> OperatorAction | None:
        res = await self.redis_client.blpop(self._actions_key(checkpoint_id), timeout=timeout_seconds)
        if not res:
            return None
        _key, raw = res
        obj = json.loads(raw)
        return OperatorAction(**obj)
