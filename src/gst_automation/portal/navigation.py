from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.browser.artifacts import ArtifactManager
from gst_automation.core.logging import get_logger
from gst_automation.portal.errors import NavigationFailed
from gst_automation.portal.telemetry import NAVIGATIONS_TOTAL, PORTAL_LATENCY_SECONDS


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class NavigationPolicy:
    attempts: int = 3
    timeout_ms: int = 60_000


@dataclass(frozen=True, slots=True)
class NavigationEngine:
    """Retry-aware safe navigation with telemetry and failure artifacts."""

    artifacts: ArtifactManager
    policy: NavigationPolicy = NavigationPolicy()

    async def goto(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        url: str,
    ) -> None:
        last_exc: Exception | None = None
        for attempt in range(1, self.policy.attempts + 1):
            start = time.monotonic()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=self.policy.timeout_ms)
                NAVIGATIONS_TOTAL.labels(result="ok").inc()
                PORTAL_LATENCY_SECONDS.observe(max(0.0, time.monotonic() - start))
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                NAVIGATIONS_TOTAL.labels(result="fail").inc()
                await self._capture_failure(session, job_id=job_id, context_id=context_id, page=page)
                logger.warning("nav.goto_failed", attempt=attempt, url=url, err=str(exc))
        raise NavigationFailed(f"goto failed: {url}: {last_exc}")

    async def _capture_failure(
        self, session: AsyncSession, *, job_id: uuid.UUID, context_id: uuid.UUID, page: Page
    ) -> None:
        try:
            root = self.artifacts.context_root(job_id=job_id, context_id=context_id)
            root.mkdir(parents=True, exist_ok=True)
            path = root / "nav_failure.png"
            await page.screenshot(path=str(path), full_page=True)
            await self.artifacts.record_file(
                session,
                job_id=job_id,
                context_id=context_id,
                kind="screenshot",
                path=path,
                relpath=str(path.relative_to(self.artifacts.artifacts_root)),
            )
        except Exception:
            return

