from __future__ import annotations

import uuid

import pytest

from gst_automation.browser.lease_guard import BrowserLeaseInvalid, LeaseGuard


class FakeLeaseRepo:
    def __init__(self, current: int | None) -> None:
        self._current = current

    async def get_fencing_token(self, *, job_id: uuid.UUID, lease_token: str) -> int | None:  # noqa: ARG002
        return self._current


@pytest.mark.asyncio
async def test_chaos_stale_fencing_token_blocks_actions() -> None:
    job_id = uuid.uuid4()
    guard = LeaseGuard(
        session=None,  # type: ignore[arg-type]
        job_id=job_id,
        lease_token="t",
        expected_fencing_token=1,
        _repo_override=FakeLeaseRepo(current=2),  # type: ignore[arg-type]
    )
    with pytest.raises(BrowserLeaseInvalid):
        await guard.assert_valid()


@pytest.mark.asyncio
async def test_chaos_missing_lease_blocks_actions() -> None:
    job_id = uuid.uuid4()
    guard = LeaseGuard(
        session=None,  # type: ignore[arg-type]
        job_id=job_id,
        lease_token="t",
        expected_fencing_token=1,
        _repo_override=FakeLeaseRepo(current=None),  # type: ignore[arg-type]
    )
    with pytest.raises(BrowserLeaseInvalid):
        await guard.assert_valid()

