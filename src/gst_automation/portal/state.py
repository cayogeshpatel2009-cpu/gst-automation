from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from playwright.async_api import Page

from gst_automation.core.logging import get_logger


logger = get_logger(__name__)

PageState = Literal[
    "unknown",
    "maintenance",
    "session_expired",
    "captcha",
    "otp",
    "error_modal",
    "loading",
    "ready",
]


@dataclass(frozen=True, slots=True)
class StateResult:
    state: PageState
    confidence: float
    evidence: str


class PageStateDetector:
    """Generic page state detector (no portal-specific selectors)."""

    async def detect(self, page: Page) -> StateResult:
        try:
            content = (await page.content()).lower()
        except Exception:  # noqa: BLE001
            return StateResult(state="unknown", confidence=0.1, evidence="content_unavailable")

        if "maintenance" in content or "temporarily unavailable" in content:
            return StateResult(state="maintenance", confidence=0.8, evidence="keyword")
        if "session expired" in content or "re-login" in content:
            return StateResult(state="session_expired", confidence=0.8, evidence="keyword")
        if "captcha" in content:
            return StateResult(state="captcha", confidence=0.6, evidence="keyword")
        if "otp" in content and "enter" in content:
            return StateResult(state="otp", confidence=0.6, evidence="keyword")
        if "error" in content and "modal" in content:
            return StateResult(state="error_modal", confidence=0.5, evidence="keyword")
        return StateResult(state="ready", confidence=0.4, evidence="default")

