from __future__ import annotations

import uuid
from dataclasses import dataclass

from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.browser.artifacts import ArtifactManager
from gst_automation.core.logging import get_logger
from gst_automation.portal.state import PageStateDetector
from gst_automation.portal.telemetry import RECOVERY_ATTEMPTS_TOTAL


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    max_attempts: int = 2


@dataclass(frozen=True, slots=True)
class RecoveryEngine:
    """Recovery hooks for generic failures (redirects, loaders, modals)."""

    artifacts: ArtifactManager
    detector: PageStateDetector = PageStateDetector()
    policy: RecoveryPolicy = RecoveryPolicy()

    async def recover(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        reason: str,
    ) -> bool:
        for i in range(1, self.policy.max_attempts + 1):
            try:
                RECOVERY_ATTEMPTS_TOTAL.labels(reason=reason, result="attempt").inc()
                state = await self.detector.detect(page)
                logger.info("recovery.state", reason=reason, state=state.state, confidence=state.confidence)
                if state.state in {"loading"}:
                    await page.wait_for_load_state("domcontentloaded", timeout=15_000)
                    RECOVERY_ATTEMPTS_TOTAL.labels(reason=reason, result="ok").inc()
                    return True
                # Generic no-op recovery for now; portal-specific strategies come later.
            except Exception as exc:  # noqa: BLE001
                logger.warning("recovery.failed", reason=reason, attempt=i, err=str(exc))
        RECOVERY_ATTEMPTS_TOTAL.labels(reason=reason, result="fail").inc()
        return False

