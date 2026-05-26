from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.portal.selector_def import PortalSelectorDef
from gst_automation.portal.selectors.types import SelectorCandidate, SelectorDefinition


@dataclass(frozen=True, slots=True)
class SelectorRepo:
    session: AsyncSession

    async def get_active(self, *, key: str, version: int) -> SelectorDefinition | None:
        res = await self.session.execute(
            select(PortalSelectorDef)
            .where(PortalSelectorDef.key == key)
            .where(PortalSelectorDef.version == version)
            .where(PortalSelectorDef.active == 1)
        )
        row = res.scalar_one_or_none()
        if row is None:
            return None
        payload = json.loads(row.candidates_json)
        candidates = tuple(SelectorCandidate(**c) for c in payload["candidates"])
        return SelectorDefinition(key=key, version=version, candidates=candidates)

    async def latest_active(self, *, key: str) -> SelectorDefinition | None:
        res = await self.session.execute(
            select(PortalSelectorDef)
            .where(PortalSelectorDef.key == key)
            .where(PortalSelectorDef.active == 1)
            .order_by(PortalSelectorDef.version.desc())
            .limit(1)
        )
        row = res.scalar_one_or_none()
        if row is None:
            return None
        payload = json.loads(row.candidates_json)
        candidates = tuple(SelectorCandidate(**c) for c in payload["candidates"])
        return SelectorDefinition(key=row.key, version=row.version, candidates=candidates)

