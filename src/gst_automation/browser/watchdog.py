from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime

import psutil
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.browser.pool import BrowserPool
from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.db.models.browser.browser_crash import BrowserCrash


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BrowserWatchdog:
    """In-process browser watchdog: memory leak guard + crash recovery hooks."""

    settings: Settings
    pool: BrowserPool

    async def tick(self, session: AsyncSession, *, worker_name: str) -> None:
        rss_mb = int(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024))
        if rss_mb >= self.settings.browser_max_rss_mb:
            logger.warning("browser.watchdog.rss_limit", rss_mb=rss_mb, limit=self.settings.browser_max_rss_mb)
            await self._record_crash(
                session,
                crash_type="rss_limit",
                severity="HIGH",
                message="worker RSS exceeded browser_max_rss_mb; restarting browser pool",
                details={"rss_mb": rss_mb, "limit": self.settings.browser_max_rss_mb, "worker": worker_name},
            )
            await self.pool.restart(reason="rss_limit")
        self.pool.update_rss_metric()

    async def _record_crash(
        self,
        session: AsyncSession,
        *,
        crash_type: str,
        severity: str,
        message: str,
        details: dict[str, object],
    ) -> None:
        row = BrowserCrash(
            browser_id=None,
            context_id=None,
            job_id=None,
            crash_type=crash_type,
            severity=severity,
            message=message,
            details_json=json.dumps(details, sort_keys=True, separators=(",", ":")),
            created_at=datetime.now(UTC),
        )
        session.add(row)
        await session.flush()

