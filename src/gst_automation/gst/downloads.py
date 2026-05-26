from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from datetime import UTC, datetime

from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.archive.hashing import sha256_file
from gst_automation.browser.artifacts import ArtifactManager
from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.gst.metrics import GSTR2B_DOWNLOAD_SECONDS


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DownloadResult:
    path: Path
    sha256_hex: str
    byte_size: int
    suggested_filename: str | None


@dataclass(frozen=True, slots=True)
class DownloadWatcher:
    settings: Settings
    artifacts: ArtifactManager

    async def click_and_wait(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        click_selector: str,
        dest_dir: Path,
        filename: str,
        timeout_ms: int | None = None,
        min_bytes: int = 10_000,
    ) -> DownloadResult:
        dest_dir.mkdir(parents=True, exist_ok=True)
        timeout = int(timeout_ms or self.settings.browser_download_timeout_seconds * 1000)
        import time

        t0 = time.monotonic()
        async with page.expect_download(timeout=timeout) as dl_info:
            await page.click(click_selector)
        dl = await dl_info.value
        if Path(filename).suffix.lower() != ".xlsx":
            raise RuntimeError(f"unexpected download filename (expected .xlsx): {filename}")

        out_path = dest_dir / filename
        if out_path.exists():
            stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
            out_path = dest_dir / f"{out_path.stem}_{stamp}{out_path.suffix}"
        tmp_path = dest_dir / f".{out_path.name}.tmp"
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

        await dl.save_as(tmp_path)
        size = tmp_path.stat().st_size
        if size < int(min_bytes):
            # Keep corrupt/partial file for forensics; rename and fail fast for retry.
            bad = dest_dir / f"{out_path.stem}.corrupt{out_path.suffix}"
            try:
                tmp_path.replace(bad)
            except Exception:  # noqa: BLE001
                pass
            raise RuntimeError(f"download too small ({size} bytes) for {filename}")
        sha = sha256_file(tmp_path)
        tmp_path.replace(out_path)
        GSTR2B_DOWNLOAD_SECONDS.observe(time.monotonic() - t0)

        await self.artifacts.record_file(
            session,
            job_id=job_id,
            context_id=context_id,
            kind="download",
            path=out_path,
            relpath=str(out_path.relative_to(Path(self.settings.browser_artifacts_dir))),
        )
        logger.info("download.completed", job_id=str(job_id), filename=filename, size=size)
        return DownloadResult(path=out_path, sha256_hex=sha, byte_size=size, suggested_filename=dl.suggested_filename)
