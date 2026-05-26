from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import redis.asyncio as redis
from playwright.async_api import Page

from gst_automation.core.settings import Settings
from gst_automation.gst.assisted_gstr2b import AssistedGstr2bEngine
from gst_automation.orchestration.handlers.base import JobHandlerV2
from gst_automation.orchestration.handlers.context import JobRunContext


@dataclass(frozen=True, slots=True)
class AssistedGstr2bExecutionJobHandler(JobHandlerV2):
    async def run_with_context(self, *, job_id: uuid.UUID, payload_json: str, ctx: JobRunContext) -> None:
        settings: Settings = ctx.settings
        r = redis.from_url(settings.redis_url)
        try:
            bs = ctx.browser_session
            page: Page = await bs.context.new_page()
            await AssistedGstr2bEngine(settings=settings).run(
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

