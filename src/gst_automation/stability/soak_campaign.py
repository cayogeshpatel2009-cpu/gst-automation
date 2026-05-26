from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from celery import Celery
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.db.models.orchestration.worker_heartbeat import WorkerHeartbeat
from gst_automation.db.models.stability.soak import SoakCampaign, SoakCampaignJob, SoakSnapshot
from gst_automation.stability.scoring_service import StabilityScoreService
from gst_automation.orchestration.dto import JobCreate, JobPriority
from gst_automation.orchestration.services.orchestrator_service import OrchestratorService
from gst_automation.validation.suites import ValidationSuites


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SoakCampaignConfig:
    duration_seconds: int
    rate_per_minute: int
    chaos_percent: int
    snapshot_every_seconds: int = 60


@dataclass(frozen=True, slots=True)
class SoakCampaignEngine:
    settings: Settings
    celery: Celery

    async def start_campaign(self, session: AsyncSession, *, cfg: SoakCampaignConfig) -> uuid.UUID:
        row = SoakCampaign(
            status="running",
            duration_seconds=cfg.duration_seconds,
            rate_per_minute=cfg.rate_per_minute,
            chaos_percent=cfg.chaos_percent,
            config_json=json.dumps(cfg.__dict__, sort_keys=True, separators=(",", ":")),
        )
        session.add(row)
        await session.flush()
        return row.id

    async def run_campaign_loop(self, session: AsyncSession, *, campaign_id: uuid.UUID) -> None:
        campaign = await session.get(SoakCampaign, campaign_id)
        if campaign is None:
            raise RuntimeError("campaign not found")

        start = datetime.now(UTC)
        deadline = start + timedelta(seconds=int(campaign.duration_seconds))
        next_snapshot = start

        orch = OrchestratorService(session=session, celery=self.celery)
        scorer = StabilityScoreService()
        i = 0

        while datetime.now(UTC) < deadline and campaign.status == "running":
            # Deterministic mix: chaos every Nth job based on chaos_percent.
            chaos_every = max(1, int(100 / max(1, int(campaign.chaos_percent))))
            if i % 30 == 0:
                payload = ValidationSuites.chaos_modal_storm()
            elif i % 20 == 0:
                payload = ValidationSuites.selector_drift()
            elif i % chaos_every == 0:
                payload = ValidationSuites.chaos_redirect_loop()
            else:
                payload = ValidationSuites.basic_smoke()
            job_id = await orch.create_and_enqueue(
                JobCreate(
                    kind="portal_smoke",
                    queue="downloads",
                    priority=JobPriority.P2_DOWNLOAD,
                    payload=payload.model_dump(),
                ),
                actor="soak_campaign",
            )
            session.add(SoakCampaignJob(campaign_id=campaign_id, job_id=job_id))
            i += 1

            now = datetime.now(UTC)
            if now >= next_snapshot:
                await self._snapshot(session, campaign_id=campaign_id)
                await scorer.compute(session, scope="campaign", scope_id=campaign_id, window_minutes=60)
                next_snapshot = now + timedelta(seconds=60)
                await session.commit()

            sleep_s = max(1.0, 60.0 / max(1, int(campaign.rate_per_minute)))
            await asyncio.sleep(sleep_s)

            campaign = await session.get(SoakCampaign, campaign_id)
            if campaign is None:
                break

        await session.execute(
            SoakCampaign.__table__.update()
            .where(SoakCampaign.id == campaign_id)
            .values(status="finished", ended_at=datetime.now(UTC))
        )
        await session.flush()

    async def _snapshot(self, session: AsyncSession, *, campaign_id: uuid.UUID) -> None:
        now = datetime.now(UTC)
        # Latest worker heartbeat (best-effort) for RSS/CPU trends.
        res = await session.execute(
            select(WorkerHeartbeat.worker_name, func.max(WorkerHeartbeat.heartbeat_at))
            .group_by(WorkerHeartbeat.worker_name)
            .limit(50)
        )
        latest_by_worker = {r[0]: r[1] for r in res.all()}
        hb_rows = []
        for worker, ts in latest_by_worker.items():
            res2 = await session.execute(
                select(WorkerHeartbeat)
                .where(WorkerHeartbeat.worker_name == worker)
                .where(WorkerHeartbeat.heartbeat_at == ts)
                .limit(1)
            )
            hb = res2.scalars().first()
            if hb:
                hb_rows.append(
                    {
                        "worker_name": hb.worker_name,
                        "cpu_percent": hb.cpu_percent,
                        "memory_rss_bytes": hb.memory_rss_bytes,
                        "active_jobs": hb.active_jobs,
                        "health_state": hb.health_state,
                        "heartbeat_at": hb.heartbeat_at.isoformat(),
                    }
                )
        snapshot = {"at": now.isoformat(), "workers": hb_rows}
        session.add(
            SoakSnapshot(
                campaign_id=campaign_id,
                snapshot_json=json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
            )
        )
