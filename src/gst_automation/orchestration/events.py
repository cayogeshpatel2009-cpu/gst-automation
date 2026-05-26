from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.orchestration.event import OrchestrationEvent
from gst_automation.orchestration.repositories.event_repo import EventRepo


@dataclass(frozen=True, slots=True)
class EventContext:
    actor: str
    trace_id: str
    correlation_id: str
    run_id: str


@dataclass(frozen=True, slots=True)
class EventPublisher:
    """Append-only orchestration event publisher (DB-outbox style)."""

    session: AsyncSession

    async def publish(
        self,
        *,
        event_type: str,
        job_id: uuid.UUID | None,
        client_id: uuid.UUID | None,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None,
        ctx: EventContext,
        schema_version: int = 1,
    ) -> OrchestrationEvent:
        repo = EventRepo(self.session)
        ev = OrchestrationEvent(
            event_type=event_type,
            schema_version=schema_version,
            job_id=job_id,
            client_id=client_id,
            payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            metadata_json=json.dumps(metadata or {}, sort_keys=True, separators=(",", ":")),
            trace_id=ctx.trace_id,
            correlation_id=ctx.correlation_id,
            run_id=ctx.run_id,
            actor=ctx.actor,
            created_at=datetime.now(UTC),
        )
        return await repo.publish(ev)

