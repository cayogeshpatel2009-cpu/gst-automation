from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psutil
from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.browser.fingerprint import FingerprintPolicy
from gst_automation.browser.metrics import BROWSER_ACTIVE, BROWSER_LAUNCH_TOTAL, BROWSER_RSS_MB
from gst_automation.browser.metrics import BROWSER_RESTART_TOTAL
from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.db.models.browser.browser_instance import BrowserInstance
from gst_automation.orchestration.repositories.worker_repo import WorkerRepo


logger = get_logger(__name__)


@dataclass
class _LiveBrowser:
    id: uuid.UUID
    browser: Browser
    created_monotonic: float


class BrowserPool:
    """In-process browser pool (per Celery worker process) with DB registry + recycling."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pw: Playwright | None = None
        self._browsers: list[_LiveBrowser] = []
        self._contexts_created: dict[uuid.UUID, int] = {}
        self._fingerprint = FingerprintPolicy.from_settings(settings)

    async def start(self) -> None:
        if self._pw is not None:
            return
        self._pw = await async_playwright().start()

    async def stop(self) -> None:
        for b in self._browsers:
            try:
                await b.browser.close()
            except Exception:
                pass
        self._browsers.clear()
        self._contexts_created.clear()
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None
        BROWSER_ACTIVE.set(0)

    async def restart(self, *, reason: str) -> None:
        """Restart the in-process pool (used by watchdog on memory leak / crash)."""
        BROWSER_RESTART_TOTAL.labels(reason=reason).inc()
        await self.stop()
        await self.start()

    async def acquire_browser(self, session: AsyncSession, *, worker_name: str) -> _LiveBrowser:
        await self.start()
        assert self._pw is not None

        if self._browsers:
            if await self._maybe_retire_current(session, worker_name=worker_name):
                pass
            else:
                return self._browsers[0]

        try:
            try:
                browser = await self._pw.chromium.launch(headless=self._settings.browser_headless)
            except AttributeError as exc:
                # Playwright connection can become stale in long-running workers; restart and retry once.
                msg = str(exc)
                if "has no attribute 'send'" in msg or "BrowserType.launch" in msg:
                    logger.warning("browser.launch_retry", err=msg, worker_name=worker_name)
                    await self.restart(reason="launch_failed")
                    assert self._pw is not None
                    browser = await self._pw.chromium.launch(headless=self._settings.browser_headless)
                else:
                    raise
            bid = uuid.uuid4()
            self._browsers.append(_LiveBrowser(id=bid, browser=browser, created_monotonic=time.monotonic()))
            self._contexts_created[bid] = 0
            await self._register_browser(session, browser_id=bid, worker_name=worker_name)
            BROWSER_ACTIVE.set(len(self._browsers))
            BROWSER_LAUNCH_TOTAL.labels(result="ok").inc()
            return self._browsers[0]
        except Exception as exc:  # noqa: BLE001
            BROWSER_LAUNCH_TOTAL.labels(result="error").inc()
            logger.exception("browser.launch_failed", err=str(exc))
            raise

    async def _maybe_retire_current(self, session: AsyncSession, *, worker_name: str) -> bool:
        """Retire current browser if it breaches governance thresholds.

        Returns True if the browser was retired (and removed).
        """
        if not self._browsers:
            return False
        b = self._browsers[0]
        age = time.monotonic() - b.created_monotonic
        created = int(self._contexts_created.get(b.id, 0))
        if age < self._settings.browser_browser_ttl_seconds and created < self._settings.browser_max_contexts_per_browser:
            return False
        reason = "ttl" if age >= self._settings.browser_browser_ttl_seconds else "max_contexts"
        logger.warning(
            "browser.retire",
            reason=reason,
            worker_name=worker_name,
            browser_id=str(b.id),
            age_seconds=int(age),
            contexts_created=created,
        )
        try:
            await b.browser.close()
        except Exception:
            pass
        self._browsers.clear()
        self._contexts_created.pop(b.id, None)
        BROWSER_ACTIVE.set(0)
        try:
            await session.execute(
                BrowserInstance.__table__.update()
                .where(BrowserInstance.id == b.id)
                .values(state="offline", retired_at=datetime.now(UTC), last_heartbeat_at=datetime.now(UTC))
            )
        except Exception:
            pass
        return True

    async def new_context(
        self,
        *,
        live: _LiveBrowser,
        record_har_path: str | None = None,
        storage_state: dict | str | None = None,
    ) -> BrowserContext:
        self._contexts_created[live.id] = int(self._contexts_created.get(live.id, 0)) + 1
        context = await live.browser.new_context(
            locale=self._fingerprint.locale,
            timezone_id=self._fingerprint.timezone_id,
            viewport={"width": self._fingerprint.viewport_width, "height": self._fingerprint.viewport_height},
            accept_downloads=True,
            record_har_path=record_har_path,
            storage_state=storage_state,
        )
        context.set_default_timeout(self._settings.browser_action_timeout_ms)
        context.set_default_navigation_timeout(self._settings.browser_navigation_timeout_ms)
        return context

    async def _register_browser(self, session: AsyncSession, *, browser_id: uuid.UUID, worker_name: str) -> None:
        generation = await WorkerRepo(session).get_generation(worker_name=worker_name)
        row = BrowserInstance(
            id=browser_id,
            worker_name=worker_name,
            worker_generation=generation,
            state="online",
            browser_type="chromium",
            headless=1 if self._settings.browser_headless else 0,
            launch_config_json=json.dumps({"headless": self._settings.browser_headless}),
            created_at=datetime.now(UTC),
            last_heartbeat_at=datetime.now(UTC),
        )
        session.add(row)
        await session.flush()

    def update_rss_metric(self) -> None:
        # Best-effort: uses current process RSS as proxy when browser PID is not directly exposed.
        rss_mb = int(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024))
        for b in self._browsers:
            BROWSER_RSS_MB.labels(browser_id=str(b.id)).set(rss_mb)


_POOL: BrowserPool | None = None


def get_pool(settings: Settings) -> BrowserPool:
    global _POOL
    if _POOL is None:
        _POOL = BrowserPool(settings)
    return _POOL
