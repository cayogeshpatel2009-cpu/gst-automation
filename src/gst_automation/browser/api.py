from __future__ import annotations

import uuid
from dataclasses import dataclass

from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.browser.lease_guard import LeaseGuard
from gst_automation.browser.session import BrowserSession


@dataclass(frozen=True, slots=True)
class BrowserPage:
    """Playwright Page wrapper with lease-aware safety hooks."""

    page: Page
    guard: LeaseGuard

    async def goto(self, url: str) -> None:
        await self.guard.assert_valid()
        await self.page.goto(url)

    async def click(self, selector: str) -> None:
        await self.guard.assert_valid()
        await self.page.click(selector)


@dataclass(frozen=True, slots=True)
class BrowserApi:
    """Factory for page abstractions and lease-safe helpers."""

    session: AsyncSession
    job_id: uuid.UUID
    lease_token: str
    fencing_token: int

    async def new_page(self, bs: BrowserSession) -> BrowserPage:
        guard = LeaseGuard(
            session=self.session,
            job_id=self.job_id,
            lease_token=self.lease_token,
            expected_fencing_token=self.fencing_token,
        )
        page = await bs.context.new_page()
        return BrowserPage(page=page, guard=guard)

