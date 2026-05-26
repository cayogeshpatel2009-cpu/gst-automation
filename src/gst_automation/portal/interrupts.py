from __future__ import annotations

from dataclasses import dataclass

from playwright.async_api import Page

from gst_automation.core.logging import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class InterruptPolicy:
    attempts: int = 2


@dataclass(frozen=True, slots=True)
class InterruptManager:
    """Generic interruption handler (cookie banners/modals) with safe no-op defaults."""

    policy: InterruptPolicy = InterruptPolicy()

    async def dismiss_known_interrupts(self, page: Page) -> bool:
        # No portal-specific selectors here; framework hook only.
        _ = page
        return False

