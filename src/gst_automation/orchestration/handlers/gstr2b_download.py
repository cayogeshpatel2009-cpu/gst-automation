from __future__ import annotations

import uuid
from dataclasses import dataclass

from playwright.async_api import Page

from gst_automation.core.settings import Settings
from gst_automation.gst.gstr2b_download import Gstr2bDownloadEngine
from gst_automation.orchestration.handlers.base import JobHandlerV2
from gst_automation.orchestration.handlers.context import JobRunContext


@dataclass(frozen=True, slots=True)
class Gstr2bDownloadJobHandler(JobHandlerV2):
    async def run_with_context(self, *, job_id: uuid.UUID, payload_json: str, ctx: JobRunContext) -> None:
        settings: Settings = ctx.settings
        bs = ctx.browser_session
        page: Page = await bs.context.new_page()
        await Gstr2bDownloadEngine(settings=settings).run(
            ctx.session,
            job_id=job_id,
            context_id=bs.context_id,
            page=page,
            payload_json=payload_json,
        )
