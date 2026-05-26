from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.exceptions import GstAutomationError
from gst_automation.orchestration.repositories.lease_repo import LeaseRepo


class BrowserLeaseInvalid(GstAutomationError):
    """Raised when browser execution detects stale/expired orchestration lease."""


@dataclass(frozen=True, slots=True)
class LeaseGuard:
    """Lease-aware guard for browser actions (fencing + lease token)."""

    session: AsyncSession
    job_id: uuid.UUID
    lease_token: str
    expected_fencing_token: int
    _repo_override: LeaseRepo | None = None

    async def assert_valid(self) -> None:
        repo = self._repo_override or LeaseRepo(self.session)
        current = await repo.get_fencing_token(job_id=self.job_id, lease_token=self.lease_token)
        if current is None:
            raise BrowserLeaseInvalid("lease missing/expired")
        if int(current) != int(self.expected_fencing_token):
            raise BrowserLeaseInvalid("fencing token mismatch")
