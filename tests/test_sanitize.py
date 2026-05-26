from __future__ import annotations

from gst_automation.storage.sanitize import safe_segment


def test_safe_segment_blocks_traversal() -> None:
    assert safe_segment("../secret") == "secret"
    assert safe_segment("..\\secret") == "secret"


def test_safe_segment_nonempty() -> None:
    assert safe_segment("   ") == "unknown"

