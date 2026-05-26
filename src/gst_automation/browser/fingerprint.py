from __future__ import annotations

from dataclasses import dataclass

from gst_automation.core.settings import Settings


@dataclass(frozen=True, slots=True)
class FingerprintPolicy:
    locale: str
    timezone_id: str
    viewport_width: int
    viewport_height: int

    @classmethod
    def from_settings(cls, s: Settings) -> "FingerprintPolicy":
        return cls(
            locale=s.browser_locale,
            timezone_id=s.browser_timezone,
            viewport_width=s.browser_viewport_width,
            viewport_height=s.browser_viewport_height,
        )

