from __future__ import annotations

from gst_automation.gst.selector_promotion import score_css_selector


def test_score_css_selector_penalizes_nth_child() -> None:
    s = score_css_selector("div:nth-child(3) > button")
    assert s.score < 100

