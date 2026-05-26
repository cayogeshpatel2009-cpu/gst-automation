from __future__ import annotations

import asyncio
from dataclasses import dataclass

from playwright.async_api import Page

from gst_automation.core.logging import get_logger
from gst_automation.validation.dto import ChaosConfig
from gst_automation.validation.metrics import CHAOS_EVENTS_TOTAL


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ChaosInjector:
    """Deterministic chaos injection hooks for browser validation workflows."""

    cfg: ChaosConfig

    async def maybe_inject(self, *, step_index: int, page: Page) -> None:
        if self.cfg.scenario == "none":
            return
        if self.cfg.at_step is None or int(self.cfg.at_step) != int(step_index):
            return

        scenario = self.cfg.scenario
        try:
            if scenario == "navigation_timeout":
                # Make next navigation extremely likely to time out.
                page.set_default_navigation_timeout(1)
            elif scenario == "network_offline":
                await page.context.set_offline(True)
            elif scenario == "redirect_storm":
                await page.goto("/redirect-loop")
            elif scenario == "modal_storm":
                await page.goto("/modal-storm")
            elif scenario == "playwright_disconnect":
                # Simulate a hard disconnect by closing the underlying browser context.
                await page.context.close()
            elif scenario == "chromium_crash":
                # Force-close browser to simulate crash.
                await page.context.browser.close()
            elif scenario == "download_corrupt":
                # Test portal serves corrupt data; injection is a no-op here.
                await asyncio.sleep(0)
            elif scenario == "page_freeze":
                # CPU-bound JS loop (short) to exercise timeouts/watchdog behavior.
                await page.evaluate(
                    "() => { const end = Date.now() + 3000; while (Date.now() < end) {} return true; }"
                )
            elif scenario == "memory_pressure":
                # Allocate memory in-page (bounded) to exercise RSS monitoring without OOM.
                await page.evaluate(
                    "() => { const bufs = []; for (let i=0;i<32;i++) bufs.push(new ArrayBuffer(1024*1024)); return bufs.length; }"
                )
            else:
                raise ValueError(f"unknown chaos scenario: {scenario}")
            logger.warning("chaos.injected", scenario=scenario, step_index=step_index)
            CHAOS_EVENTS_TOTAL.labels(scenario=scenario, result="ok").inc()
        except Exception as exc:  # noqa: BLE001
            logger.warning("chaos.inject_failed", scenario=scenario, step_index=step_index, err=str(exc))
            CHAOS_EVENTS_TOTAL.labels(scenario=scenario, result="error").inc()
            raise
