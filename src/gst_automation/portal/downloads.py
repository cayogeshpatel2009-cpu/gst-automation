from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Download, Page
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.browser.artifacts import ArtifactManager
from gst_automation.browser.metrics import DOWNLOAD_SECONDS
from gst_automation.browser.sandbox import DownloadSandbox
from gst_automation.core.logging import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DownloadPolicy:
    timeout_seconds: int = 300


@dataclass(frozen=True, slots=True)
class DownloadStateEngine:
    """Generic download capture and validation (no portal-specific expectations)."""

    sandbox: DownloadSandbox
    artifacts: ArtifactManager
    policy: DownloadPolicy = DownloadPolicy()

    async def wait_and_finalize(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        trigger_coro,
        final_dir: Path,
        final_name: str,
    ) -> Path:
        import time

        start = time.monotonic()
        async with page.expect_download(timeout=self.policy.timeout_seconds * 1000) as dl_info:
            await trigger_coro
        download: Download = await dl_info.value
        tmp_path = await download.path()
        if tmp_path is None:
            raise RuntimeError("download path unavailable")
        result = self.sandbox.finalize_file(
            tmp_path=Path(tmp_path), final_dir=final_dir, final_name=final_name
        )
        DOWNLOAD_SECONDS.observe(max(0.0, time.monotonic() - start))
        await self.artifacts.record_file(
            session,
            job_id=job_id,
            context_id=context_id,
            kind="download",
            path=result.path,
            relpath=str(result.path.relative_to(self.artifacts.artifacts_root)),
        )
        return result.path

