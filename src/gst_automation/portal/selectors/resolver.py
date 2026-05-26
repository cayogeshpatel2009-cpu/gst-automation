from __future__ import annotations

from dataclasses import dataclass

from playwright.async_api import Page

from gst_automation.core.logging import get_logger
from gst_automation.portal.errors import SelectorResolutionFailed
from gst_automation.portal.selectors.types import SelectorCandidate, SelectorDefinition
from gst_automation.portal.telemetry import SELECTOR_ATTEMPTS_TOTAL, SELECTOR_FALLBACKS_TOTAL


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SelectorResolver:
    """Resolves selectors with fallback chains and telemetry."""

    async def resolve(self, page: Page, definition: SelectorDefinition, *, timeout_ms: int) -> str:
        selector, _idx, _total = await self.resolve_detailed(page, definition, timeout_ms=timeout_ms)
        return selector

    async def resolve_detailed(
        self, page: Page, definition: SelectorDefinition, *, timeout_ms: int
    ) -> tuple[str, int, int]:
        candidates = sorted(definition.candidates, key=lambda c: c.weight, reverse=True)
        for idx, c in enumerate(candidates):
            try:
                selector = self._to_playwright_selector(c)
                await page.wait_for_selector(selector, timeout=timeout_ms, state="visible")
                SELECTOR_ATTEMPTS_TOTAL.labels(key=definition.key, result="ok").inc()
                if idx > 0:
                    SELECTOR_FALLBACKS_TOTAL.labels(key=definition.key).inc()
                return selector, idx, len(candidates)
            except Exception:  # noqa: BLE001
                continue
        SELECTOR_ATTEMPTS_TOTAL.labels(key=definition.key, result="fail").inc()
        logger.warning("selector.resolve_failed", key=definition.key, version=definition.version)
        raise SelectorResolutionFailed(f"selector resolution failed: {definition.key}@{definition.version}")

    def _to_playwright_selector(self, c: SelectorCandidate) -> str:
        if c.kind == "css":
            return c.value
        if c.kind == "text":
            return f"text={c.value}"
        if c.kind == "aria":
            return f"aria/{c.value}"
        if c.kind == "role":
            # value format: "button[name='Submit']" (kept flexible)
            return f"role={c.value}"
        raise ValueError(f"Unsupported selector kind: {c.kind}")
