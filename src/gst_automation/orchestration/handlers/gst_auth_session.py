from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import redis.asyncio as redis
from playwright.async_api import Page

from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.orchestration.handlers.base import JobHandlerV2
from gst_automation.orchestration.handlers.context import JobRunContext
from gst_automation.gst.auth_session import GstAuthSessionEngine


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class GstAuthSessionJobHandler(JobHandlerV2):
    """Supervised GST authentication session acquisition (HITL)."""

    async def run_with_context(
        self, *, job_id: uuid.UUID, payload_json: str, ctx: JobRunContext
    ) -> None:
        settings: Settings = ctx.settings
        r = redis.from_url(settings.redis_url)
        try:
            bs = ctx.browser_session
            page: Page = await bs.context.new_page()
            await GstAuthSessionEngine(settings=settings).run(
                ctx.session,
                r,
                job_id=job_id,
                context_id=bs.context_id,
                page=page,
                artifacts_dir=Path(bs.artifacts_dir),
                payload_json=payload_json,
            )
        finally:
            await r.close()

