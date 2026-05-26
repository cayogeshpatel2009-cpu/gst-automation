from __future__ import annotations

import pytest

from gst_automation.portal.errors import SelectorNotFound
from gst_automation.portal.selectors.registry import SelectorRegistry
from gst_automation.portal.selectors.types import SelectorCandidate, SelectorDefinition


def test_selector_registry_latest() -> None:
    reg = SelectorRegistry(
        definitions={
            ("k", 1): SelectorDefinition("k", 1, (SelectorCandidate(kind="css", value="#a"),)),
            ("k", 2): SelectorDefinition("k", 2, (SelectorCandidate(kind="css", value="#b"),)),
        }
    )
    assert reg.latest(key="k").version == 2


def test_selector_registry_missing_raises() -> None:
    reg = SelectorRegistry(definitions={})
    with pytest.raises(SelectorNotFound):
        reg.latest(key="missing")

