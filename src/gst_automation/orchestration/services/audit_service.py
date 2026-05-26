from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.audit import AuditEvent


@dataclass(frozen=True, slots=True)
class AuditService:
    session: AsyncSession

    async def record(
        self,
        *,
        event_type: str,
        actor: str,
        client_id: uuid.UUID | None,
        details: dict[str, Any],
    ) -> None:
        ev = AuditEvent(
            client_id=client_id,
            event_type=event_type,
            actor=actor,
            details_json=AuditEvent.details_to_json(details),
            created_at=datetime.now(UTC),
        )
        self.session.add(ev)
        await self.session.flush()

