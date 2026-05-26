from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.browser.artifacts import ArtifactManager
from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.db.models.gst.portal_profile import GstPortalProfile


logger = get_logger(__name__)


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class GstPortalProfileSnapshot:
    url: str
    timing: dict[str, object]
    redirect_chain: list[str]
    dom_fingerprint_sha256: str
    title: str
    has_modal_like: bool


@dataclass(frozen=True, slots=True)
class GstPortalProfiler:
    settings: Settings
    artifacts: ArtifactManager

    async def snapshot(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        name: str,
        artifacts_dir: Path,
    ) -> GstPortalProfileSnapshot:
        url = page.url
        title = await page.title()
        redirect_chain = await page.evaluate("() => (performance.getEntriesByType('navigation')[0]?.redirectCount ?? 0)")
        timing = await page.evaluate(
            """() => {
              const nav = performance.getEntriesByType('navigation')[0];
              if (!nav) return {};
              return {
                startTime: nav.startTime,
                domContentLoaded: nav.domContentLoadedEventEnd,
                loadEventEnd: nav.loadEventEnd,
                responseEnd: nav.responseEnd,
                redirectCount: nav.redirectCount,
                transferSize: nav.transferSize
              };
            }"""
        )
        html = await page.content()
        dom_fp = _sha256_hex(html[:200_000])
        has_modal_like = await page.evaluate(
            """() => {
              const modal = document.querySelector('[role="dialog"], .modal, .MuiDialog-root, .ant-modal, .overlay');
              return !!modal;
            }"""
        )

        snap = GstPortalProfileSnapshot(
            url=url,
            timing=timing if isinstance(timing, dict) else {},
            redirect_chain=[url] * int(redirect_chain or 0),
            dom_fingerprint_sha256=dom_fp,
            title=title,
            has_modal_like=bool(has_modal_like),
        )

        path = artifacts_dir / "gst_profile" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snap.__dict__, sort_keys=True, indent=2), encoding="utf-8")
        await self.artifacts.record_file(
            session,
            job_id=job_id,
            context_id=context_id,
            kind="gst_profile",
            path=path,
            relpath=str(path.relative_to(Path(self.settings.browser_artifacts_dir))),
        )

        session.add(
            GstPortalProfile(
                job_id=job_id,
                context_id=context_id,
                url=url,
                title=title,
                dom_fingerprint_sha256=dom_fp,
                redirect_count=int(redirect_chain or 0),
                timing_json=json.dumps(snap.timing, sort_keys=True, separators=(",", ":")),
                created_at=datetime.now(UTC),
            )
        )
        return snap
