from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.browser.artifacts import ArtifactManager
from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.validation.dto import RealSiteSmokePayload
from gst_automation.validation.real_site_policy import RealSitePolicy


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RealSiteSmokeWorkflow:
    settings: Settings
    artifacts: ArtifactManager
    policy: RealSitePolicy

    async def run(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        payload_json: str,
        artifacts_dir: Path,
    ) -> None:
        payload = RealSiteSmokePayload.model_validate(json.loads(payload_json))
        self.policy.assert_url_allowed(payload.start_url)

        # Navigation-only: block all unintended downloads unless explicitly allowed.
        if not payload.allow_downloads:
            page.on("download", lambda d: logger.warning("real_site.download_blocked", url=d.url))

        await page.goto(payload.start_url)
        await self._screenshot(session, job_id=job_id, context_id=context_id, page=page, artifacts_dir=artifacts_dir, name="start")

        for idx, a in enumerate(payload.actions):
            if a.kind == "goto":
                assert a.url is not None
                self.policy.assert_url_allowed(a.url)
                await page.goto(a.url)
            elif a.kind == "sleep_ms":
                await page.wait_for_timeout(int(a.value or 0))
            elif a.kind == "screenshot":
                await self._screenshot(
                    session,
                    job_id=job_id,
                    context_id=context_id,
                    page=page,
                    artifacts_dir=artifacts_dir,
                    name=a.name or f"step_{idx}",
                )
            elif a.kind == "expect_title_contains":
                assert a.text is not None
                t = await page.title()
                if a.text not in t:
                    raise AssertionError(f"title missing substring: {a.text!r}")
            elif a.kind == "expect_text":
                assert a.text is not None
                body = await page.inner_text("body")
                if a.text not in body:
                    raise AssertionError(f"expected text not found: {a.text!r}")
            else:
                raise ValueError(f"unsupported real_site_smoke action: {a.kind}")

    async def _screenshot(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        artifacts_dir: Path,
        name: str,
    ) -> None:
        path = artifacts_dir / "screenshots" / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(path), full_page=True)
        await self.artifacts.record_file(
            session,
            job_id=job_id,
            context_id=context_id,
            kind="screenshot",
            path=path,
            relpath=str(path.relative_to(Path(self.settings.browser_artifacts_dir))),
        )


async def run_real_site_smoke(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    context_id: uuid.UUID,
    page: Page,
    payload_json: str,
    settings: Settings,
    artifacts_dir: Path,
) -> None:
    artifacts = ArtifactManager(artifacts_root=Path(settings.browser_artifacts_dir))
    wf = RealSiteSmokeWorkflow(settings=settings, artifacts=artifacts, policy=RealSitePolicy(settings=settings))
    t0 = time.monotonic()
    await wf.run(
        session,
        job_id=job_id,
        context_id=context_id,
        page=page,
        payload_json=payload_json,
        artifacts_dir=artifacts_dir,
    )
    logger.info("real_site_smoke.completed", job_id=str(job_id), seconds=time.monotonic() - t0)

