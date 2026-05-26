from __future__ import annotations

import asyncio
import uuid

import pytest

from gst_automation.gst.hitl_channel import HitlChannel, OperatorAction


class _FakeRedis:
    def __init__(self) -> None:
        self._q: dict[str, list[str]] = {}

    async def rpush(self, key: str, val: str) -> None:
        self._q.setdefault(key, []).append(val)

    async def blpop(self, key: str, timeout: int = 0):  # type: ignore[no-untyped-def]
        _ = timeout
        q = self._q.get(key, [])
        if not q:
            await asyncio.sleep(0)
            return None
        v = q.pop(0)
        return (key, v)


@pytest.mark.asyncio
async def test_hitl_channel_roundtrip() -> None:
    r = _FakeRedis()
    c = HitlChannel(r)  # type: ignore[arg-type]
    cid = uuid.uuid4()
    await c.enqueue_action(checkpoint_id=cid, action=OperatorAction(kind="type", selector="#x", value="123", sensitive=True))
    act = await c.pop_action(checkpoint_id=cid, timeout_seconds=1)
    assert act is not None
    assert act.kind == "type"
    assert act.selector == "#x"

