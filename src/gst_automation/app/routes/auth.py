from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

import redis.asyncio as redis

from gst_automation.core.settings import Settings
from gst_automation.gst.hitl_channel import HitlChannel, OperatorAction


router = APIRouter(prefix="/auth", tags=["auth"])


class OperatorActionIn(BaseModel):
    kind: str = Field(min_length=1, max_length=32)  # type|press|click|approve|reject
    selector: str | None = Field(default=None, max_length=512)
    value: str | None = Field(default=None, max_length=2048)
    key: str | None = Field(default=None, max_length=64)
    sensitive: bool = False


@router.post("/checkpoints/{checkpoint_id}/actions")
async def enqueue_checkpoint_action(request: Request, checkpoint_id: str, payload: OperatorActionIn) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    r = redis.from_url(settings.redis_url)
    try:
        channel = HitlChannel(r)
        cid = uuid.UUID(checkpoint_id)
        await channel.enqueue_action(
            checkpoint_id=cid,
            action=OperatorAction(
                kind=payload.kind,
                selector=payload.selector,
                value=payload.value,
                key=payload.key,
                sensitive=bool(payload.sensitive),
            ),
        )
        return {"ok": True}
    finally:
        await r.close()

