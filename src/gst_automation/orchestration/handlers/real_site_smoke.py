from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Page

from gst_automation.browser.artifacts import ArtifactManager
from gst_automation.core.logging import get_logger
from gst_automation.orchestration.handlers.base import JobHandlerV2
from gst_automation.orchestration.handlers.context import JobRunContext
from gst_automation.validation.real_site_smoke import run_real_site_smoke


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RealSiteSmokeJobHandler(JobHandlerV2):
    """Safe real-site validation (navigation/screenshot only; allowlist enforced)."""

    async def run_with_context(
        self, *, job_id: uuid.UUID, payload_json: str, ctx: JobRunContext
    ) -> None:
        bs = ctx.browser_session
        page: Page = await bs.context.new_page()

        await run_real_site_smoke(
            ctx.session,
            job_id=job_id,
            context_id=bs.context_id,
            page=page,
            payload_json=payload_json,
            settings=ctx.settings,
            artifacts_dir=Path(bs.artifacts_dir),
        )

        # Index replay not used here; console indexing can be added if needed.
        try:
            artifacts = ArtifactManager(artifacts_root=Path(ctx.settings.browser_artifacts_dir))
            # no-op: screenshots indexed by workflow.
            _ = artifacts
        except Exception as exc:  # noqa: BLE001
            logger.warning("real_site_smoke.index_warn", job_id=str(job_id), err=str(exc))

