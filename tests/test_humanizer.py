from __future__ import annotations

from gst_automation.portal.humanize import Humanizer


def test_humanizer_deterministic() -> None:
    h1 = Humanizer(seed="x")
    h2 = Humanizer(seed="x")
    assert h1.key_delay_ms() == h2.key_delay_ms()

