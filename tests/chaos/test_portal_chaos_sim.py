from __future__ import annotations

import pytest

from gst_automation.portal.selectors.types import SelectorCandidate, SelectorDefinition
from gst_automation.portal.selectors.resolver import SelectorResolver
from gst_automation.portal.errors import SelectorResolutionFailed


class FakePage:
    def __init__(self, ok_selector: str | None) -> None:
        self._ok = ok_selector

    async def wait_for_selector(self, selector: str, timeout: int, state: str) -> None:  # noqa: ARG002
        if self._ok is None or selector != self._ok:
            raise TimeoutError("not found")


@pytest.mark.asyncio
async def test_chaos_selector_fallback_chain_works() -> None:
    d = SelectorDefinition(
        key="k",
        version=1,
        candidates=(
            SelectorCandidate(kind="css", value="#missing", weight=200),
            SelectorCandidate(kind="css", value="#ok", weight=100),
        ),
    )
    page = FakePage(ok_selector="#ok")
    r = SelectorResolver()
    resolved = await r.resolve(page, d, timeout_ms=10)
    assert resolved == "#ok"


@pytest.mark.asyncio
async def test_chaos_selector_all_fail_raises() -> None:
    d = SelectorDefinition(key="k", version=1, candidates=(SelectorCandidate(kind="css", value="#x"),))
    page = FakePage(ok_selector=None)
    r = SelectorResolver()
    with pytest.raises(SelectorResolutionFailed):
        await r.resolve(page, d, timeout_ms=10)

