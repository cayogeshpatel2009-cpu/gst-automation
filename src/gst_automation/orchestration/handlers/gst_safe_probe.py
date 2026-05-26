from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Page

from gst_automation.core.logging import get_logger
from gst_automation.orchestration.handlers.base import JobHandlerV2
from gst_automation.orchestration.handlers.context import JobRunContext
from gst_automation.gst.safe_probe import run_gst_safe_probe


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class GstSafeProbeJobHandler(JobHandlerV2):
    """GST-safe, read-only probe (no login submission, no downloads)."""

    async def run_with_context(
        self, *, job_id: uuid.UUID, payload_json: str, ctx: JobRunContext
    ) -> None:
        bs = ctx.browser_session
        page: Page = await bs.context.new_page()
        await run_gst_safe_probe(
            ctx.session,
            job_id=job_id,
            context_id=bs.context_id,
            page=page,
            payload_json=payload_json,
            settings=ctx.settings,
            artifacts_dir=Path(bs.artifacts_dir),
        )

