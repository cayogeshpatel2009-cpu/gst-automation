from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.email.delivery import EmailDelivery
from gst_automation.orchestration.dto import JobCreate, JobPriority
from gst_automation.orchestration.services.orchestrator_service import OrchestratorService


def _short_key(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:40]


@dataclass(frozen=True, slots=True)
class EmailReliabilityService:
    async def reconcile_failed(
        self,
        session: AsyncSession,
        *,
        celery,
        min_age_minutes: int = 5,
        limit: int = 50,
    ) -> int:
        cutoff = datetime.now(UTC) - timedelta(minutes=min_age_minutes)
        res = await session.execute(
            select(EmailDelivery)
            .where(EmailDelivery.status == "failed")
            .where(EmailDelivery.created_at <= cutoff)
            .order_by(EmailDelivery.created_at.asc())
            .limit(limit)
        )
        rows = list(res.scalars().all())
        if not rows:
            return 0

        orch = OrchestratorService(session=session, celery=celery)
        enq = 0
        for r in rows:
            if not r.idempotency_key:
                continue
            await orch.create_and_enqueue(
                JobCreate(
                    kind="email_delivery",
                    queue="emails",
                    priority=JobPriority.P3_EMAIL,
                    idempotency_key=f"email_retry:{_short_key(r.idempotency_key)}",
                    client_id=r.client_id,
                    payload={
                        "client_id": str(r.client_id),
                        "to_email": r.to_email,
                        "cc_email": r.cc_email,
                        "subject": r.subject,
                        "body": "",
                        "attachment_path": r.attachment_path,
                        "filename": None,
                        "idempotency_key": r.idempotency_key,
                    },
                ),
                actor="email_reconcile",
            )
            enq += 1
        return enq

