from __future__ import annotations

import uuid
from dataclasses import dataclass

from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.browser.artifacts import ArtifactManager
from gst_automation.core.settings import Settings
from gst_automation.portal.humanize import Humanizer
from gst_automation.portal.interactions import InteractionEngine
from gst_automation.portal.navigation import NavigationEngine
from gst_automation.portal.recovery import RecoveryEngine
from gst_automation.portal.selectors.registry import SelectorRegistry
from gst_automation.portal.selectors.resolver import SelectorResolver
from gst_automation.db.models.gst.selector_health import SelectorHealthEvent
from datetime import UTC, datetime
import json
import time


@dataclass(frozen=True, slots=True)
class PortalDsl:
    """High-level portal automation primitives (future GST logic must use these only)."""

    settings: Settings
    artifacts: ArtifactManager
    selectors: SelectorRegistry
    resolver: SelectorResolver = SelectorResolver()

    async def safe_goto(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        url: str,
    ) -> None:
        nav = NavigationEngine(artifacts=self.artifacts)
        await nav.goto(session, job_id=job_id, context_id=context_id, page=page, url=url)

    async def safe_click(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        selector_key: str,
        selector_version: int | None = None,
        humanizer: Humanizer | None = None,
    ) -> None:
        definition = (
            self.selectors.get(key=selector_key, version=selector_version)
            if selector_version is not None
            else self.selectors.latest(key=selector_key)
        )
        t0 = time.monotonic()
        try:
            resolved, idx, total = await self.resolver.resolve_detailed(
                page, definition, timeout_ms=self.settings.browser_action_timeout_ms
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            session.add(
                SelectorHealthEvent(
                    job_id=job_id,
                    context_id=context_id,
                    selector_key=definition.key,
                    selector_version=int(definition.version),
                    result="ok" if idx == 0 else "fallback",
                    candidate_index=int(idx),
                    candidates_total=int(total),
                    latency_ms=latency_ms,
                    details_json=json.dumps({"url": page.url}, sort_keys=True, separators=(",", ":")),
                    created_at=datetime.now(UTC),
                )
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.monotonic() - t0) * 1000)
            session.add(
                SelectorHealthEvent(
                    job_id=job_id,
                    context_id=context_id,
                    selector_key=definition.key,
                    selector_version=int(definition.version),
                    result="fail",
                    candidate_index=0,
                    candidates_total=len(definition.candidates),
                    latency_ms=latency_ms,
                    details_json=json.dumps({"url": page.url, "err": str(exc)}, sort_keys=True, separators=(",", ":")),
                    created_at=datetime.now(UTC),
                )
            )
            raise
        engine = InteractionEngine(settings=self.settings, artifacts=self.artifacts)
        await engine.click(
            session=session, job_id=job_id, context_id=context_id, page=page, selector=resolved, humanizer=humanizer
        )
