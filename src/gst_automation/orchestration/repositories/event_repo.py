from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.orchestration.event import OrchestrationEvent


@dataclass(frozen=True, slots=True)
class EventRepo:
    session: AsyncSession

    async def publish(self, event: OrchestrationEvent) -> OrchestrationEvent:
        self.session.add(event)
        await self.session.flush()
        return event

