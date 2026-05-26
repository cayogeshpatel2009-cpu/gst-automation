from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.browser.artifacts import ArtifactManager
from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.portal.errors import InteractionFailed
from gst_automation.portal.humanize import Humanizer
from gst_automation.portal.telemetry import INTERACTIONS_TOTAL
from gst_automation.retry.engine import RetryEngine


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class InteractionPolicy:
    attempts: int = 3
    timeout_ms: int = 30_000


@dataclass(frozen=True, slots=True)
class InteractionEngine:
    """Safe interaction wrappers: retry-aware + screenshot-on-failure + telemetry."""

    settings: Settings
    artifacts: ArtifactManager
    retry: RetryEngine = RetryEngine()
    policy: InteractionPolicy = InteractionPolicy()

    async def click(
        self,
        *,
        session: AsyncSession,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        selector: str,
        humanizer: Humanizer | None = None,
    ) -> None:
        last_exc: Exception | None = None
        for attempt in range(1, self.policy.attempts + 1):
            try:
                if humanizer is not None:
                    await page.wait_for_timeout(humanizer.action_jitter_ms())
                await page.click(selector, timeout=self.policy.timeout_ms)
                INTERACTIONS_TOTAL.labels(op="click", result="ok").inc()
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                INTERACTIONS_TOTAL.labels(op="click", result="fail").inc()
                await self._capture_failure(session, job_id=job_id, context_id=context_id, page=page, kind="click")
                logger.warning("interaction.click_failed", attempt=attempt, selector=selector, err=str(exc))
        raise InteractionFailed(f"click failed for selector={selector}: {last_exc}")

    async def fill(
        self,
        *,
        session: AsyncSession,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        selector: str,
        value: str,
        humanizer: Humanizer | None = None,
    ) -> None:
        last_exc: Exception | None = None
        for attempt in range(1, self.policy.attempts + 1):
            try:
                await page.click(selector, timeout=self.policy.timeout_ms)
                await page.fill(selector, "", timeout=self.policy.timeout_ms)
                if humanizer is None:
                    await page.fill(selector, value, timeout=self.policy.timeout_ms)
                else:
                    for ch in value:
                        await page.type(selector, ch, delay=humanizer.key_delay_ms())
                INTERACTIONS_TOTAL.labels(op="fill", result="ok").inc()
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                INTERACTIONS_TOTAL.labels(op="fill", result="fail").inc()
                await self._capture_failure(session, job_id=job_id, context_id=context_id, page=page, kind="fill")
                logger.warning("interaction.fill_failed", attempt=attempt, selector=selector, err=str(exc))
        raise InteractionFailed(f"fill failed for selector={selector}: {last_exc}")

    async def _capture_failure(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        kind: str,
    ) -> None:
        try:
            root = self.artifacts.context_root(job_id=job_id, context_id=context_id)
            root.mkdir(parents=True, exist_ok=True)
            path = root / f"{kind}_failure.png"
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

