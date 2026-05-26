from __future__ import annotations

import uuid
from dataclasses import dataclass

from celery import Celery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.client import Client
from gst_automation.db.models.clients.client_config import ClientConfig
from gst_automation.orchestration.dto import JobCreate, JobPriority
from gst_automation.orchestration.services.orchestrator_service import OrchestratorService


@dataclass(frozen=True, slots=True)
class Gstr2bBatchRequest:
    financial_year: str
    period_yyyy_mm: str


@dataclass(frozen=True, slots=True)
class BatchEnqueueResult:
    enqueued: int
    job_ids: list[uuid.UUID]


@dataclass(frozen=True, slots=True)
class Gstr2bBatchService:
    session: AsyncSession
    celery: Celery

    async def enqueue_for_active_clients(self, req: Gstr2bBatchRequest, *, actor: str = "batch") -> BatchEnqueueResult:
        res = await self.session.execute(select(Client))
        clients = list(res.scalars().all())
        cfg_res = await self.session.execute(select(ClientConfig).where(ClientConfig.active == 1))
        cfgs = {c.client_id: c for c in cfg_res.scalars().all()}

        job_ids: list[uuid.UUID] = []
        orch = OrchestratorService(session=self.session, celery=self.celery)
        for c in clients:
            cfg = cfgs.get(c.id)
            if cfg is None or c.status != "active":
                continue
            job_id = await orch.create_and_enqueue(
                JobCreate(
                    kind="gstr2b_download",
                    queue="downloads",
                    priority=int(cfg.priority or JobPriority.P2_DOWNLOAD),
                    payload={
                        "client_id": str(c.id),
                        "financial_year": req.financial_year,
                        "period_yyyy_mm": req.period_yyyy_mm,
                    },
                ),
                actor=actor,
            )
            job_ids.append(job_id)
        return BatchEnqueueResult(enqueued=len(job_ids), job_ids=job_ids)

