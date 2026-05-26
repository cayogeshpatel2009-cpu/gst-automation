from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.db.models.portal.selector_def import PortalSelectorDef


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SelectorCandidateSet:
    key: str
    candidates: list[str]
    notes: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SelectorDiscoveryEngine:
    """Read-only selector discovery + versioning (stores inactive defs for operator review)."""

    async def store_snapshot(
        self,
        session: AsyncSession,
        *,
        candidates: list[SelectorCandidateSet],
        prefix: str = "gst",
    ) -> list[uuid.UUID]:
        out: list[uuid.UUID] = []
        for c in candidates:
            key = f"{prefix}.{c.key}"
            # Next version = max(version)+1
            res = await session.execute(select(PortalSelectorDef.version).where(PortalSelectorDef.key == key))
            versions = [int(r[0]) for r in res.all()]
            next_version = (max(versions) + 1) if versions else 1
            row = PortalSelectorDef(
                key=key,
                version=next_version,
                candidates_json=json.dumps({"candidates": c.candidates, "notes": c.notes}, sort_keys=True, separators=(",", ":")),
                active=0,  # operator must activate explicitly
                created_at=datetime.now(UTC),
            )
            session.add(row)
            await session.flush()
            out.append(row.id)
        logger.info("selector.discovery_snapshot", count=len(out))
        return out

