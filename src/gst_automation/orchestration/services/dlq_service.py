from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.orchestration.dead_letter import DeadLetterJob
from gst_automation.orchestration.repositories.dlq_repo import DlqRepo
from gst_automation.orchestration.services.audit_service import AuditService
from gst_automation.orchestration.services.transition_service import TransitionService
from gst_automation.orchestration.events import EventContext
from gst_automation.orchestration.ids import new_correlation_id, new_run_id, new_trace_id


@dataclass(frozen=True, slots=True)
class DlqService:
    session: AsyncSession

    async def dead_letter(
        self,
        *,
        job_id: uuid.UUID,
        job_kind: str,
        payload_json: str,
        failure: dict[str, Any],
        actor: str,
    ) -> uuid.UUID:
        audit = AuditService(self.session)
        dlq_repo = DlqRepo(self.session)
        ctx = EventContext(actor=actor, trace_id=new_trace_id(), correlation_id=new_correlation_id(), run_id=new_run_id())
        ts = TransitionService(self.session)
        await ts.transition(
            job_id=job_id,
            to_state="dead_lettered",
            reason_code="retry_exhausted",
            reason_details=failure,
            ctx=ctx,
        )

        row = DeadLetterJob(
            job_id=job_id,
            job_kind=job_kind,
            payload_json=payload_json,
            failure_json=json.dumps(failure, sort_keys=True, separators=(",", ":")),
            created_at=datetime.now(UTC),
        )
        await dlq_repo.add(row)
        await audit.record(
            event_type="job.dead_lettered",
            actor=actor,
            client_id=None,
            details={"job_id": str(job_id), "job_kind": job_kind},
        )
        return row.id
