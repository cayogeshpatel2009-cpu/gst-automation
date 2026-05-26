from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.gst.operator_checkpoint import OperatorCheckpoint


@dataclass(frozen=True, slots=True)
class OperatorCheckpointService:
    session: AsyncSession

    async def create(
        self,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID | None,
        kind: str,
        instructions: str,
        details: dict[str, object] | None = None,
    ) -> uuid.UUID:
        row = OperatorCheckpoint(
            job_id=job_id,
            context_id=context_id,
            kind=kind,
            status="pending",
            instructions=instructions,
            details_json=json.dumps(details or {}, sort_keys=True, separators=(",", ":")),
        )
        self.session.add(row)
        await self.session.flush()
        return row.id

    async def get(self, checkpoint_id: uuid.UUID) -> OperatorCheckpoint | None:
        return await self.session.get(OperatorCheckpoint, checkpoint_id)

    async def list_pending(self, *, limit: int = 50) -> list[OperatorCheckpoint]:
        res = await self.session.execute(
            select(OperatorCheckpoint)
            .where(OperatorCheckpoint.status == "pending")
            .order_by(OperatorCheckpoint.created_at.asc())
            .limit(limit)
        )
        return list(res.scalars().all())

    async def resolve(
        self,
        *,
        checkpoint_id: uuid.UUID,
        status: str,
        resolved_by: str,
    ) -> bool:
        row = await self.session.get(OperatorCheckpoint, checkpoint_id)
        if row is None:
            return False
        if row.status != "pending":
            return True
        row.status = status
        row.resolved_by = resolved_by
        row.resolved_at = datetime.now(UTC)
        await self.session.flush()
        return True

