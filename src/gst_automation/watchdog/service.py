from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import redis.asyncio as redis
from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.locks.redis_lock import RedisLockManager
from gst_automation.observability.metrics import (
    JOB_ENQUEUED_TOTAL,
    QUEUE_OVERLOAD,
    SCHEDULER_SELECTED,
    WATCHDOG_TICKS_TOTAL,
)
from gst_automation.orchestration.repositories.job_repo import JobRepo
from gst_automation.orchestration.services.lease_recovery_service import LeaseRecoveryService
from gst_automation.orchestration.services.worker_service import WorkerService
from gst_automation.scheduler.fairness import FairScheduler, FairnessPolicy
from gst_automation.watchdog.anomaly import AnomalyRecord, AnomalyService
from gst_automation.validation.cleanup_invariants import CleanupInvariantScanner
from gst_automation.validation.retention import RetentionService
from gst_automation.gst.selector_drift import SelectorDriftDetector


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WatchdogService:
    """Cluster watchdog: stale worker/lease recovery + runnable job enqueue."""

    session: AsyncSession
    celery: Celery
    redis_client: redis.Redis

    async def tick(self) -> None:
        lock_mgr = RedisLockManager(self.redis_client)
        owner = f"watchdog:{os.getpid()}"
        leader = await lock_mgr.acquire(name="watchdog:leader", owner=owner, ttl_seconds=20)
        if leader is None:
            return
        try:
            WATCHDOG_TICKS_TOTAL.labels(result="leader").inc()
            await self._tick_as_leader()
        finally:
            await lock_mgr.release(leader)

    async def _tick_as_leader(self) -> None:
        settings = Settings.load()
        anomaly = AnomalyService(self.session)
        ws = WorkerService(self.session)
        stale = await ws.mark_stale_workers_offline(stale_after_seconds=30)
        if stale:
            logger.warning("watchdog.stale_workers_offline", count=stale)
            await anomaly.record(
                AnomalyRecord(
                    anomaly_type="dead_workers",
                    severity="HIGH" if stale >= 3 else "WARNING",
                    score=min(100, stale * 10),
                    message="workers marked offline due to missing heartbeats",
                    details={"count": stale},
                )
            )

        lr = LeaseRecoveryService(self.session)
        expired = await lr.find_expired_job_ids(limit=200)
        reclaimed = 0
        for job_id in expired:
            ok = await lr.reclaim_expired_job(job_id=job_id)
            if ok:
                reclaimed += 1
                self.celery.send_task(
                    "gst_automation.celery_app.tasks.job_runner.run_job",
                    args=[str(job_id)],
                    queue="downloads",
                    priority=5,
                    countdown=0,
                )
        if reclaimed:
            logger.warning("watchdog.reclaimed_jobs", count=reclaimed)
            await anomaly.record(
                AnomalyRecord(
                    anomaly_type="lease_recovery",
                    severity="WARNING",
                    score=min(100, reclaimed * 5),
                    message="expired leases recovered",
                    details={"count": reclaimed},
                )
            )

        repo = JobRepo(self.session)
        # Backpressure signal (best-effort): if broker queue depth is too high, stop enqueuing low priority.
        overload = await self._is_overloaded(limit=settings.backpressure_queue_depth_limit)
        for q, flag in overload.items():
            QUEUE_OVERLOAD.labels(queue=q).set(1 if flag else 0)
            if flag:
                await anomaly.record(
                    AnomalyRecord(
                        anomaly_type="queue_overload",
                        severity="HIGH" if q in {"critical", "downloads"} else "WARNING",
                        score=80 if q in {"critical", "downloads"} else 50,
                        message="broker queue depth exceeded backpressure threshold",
                        details={"queue": q, "limit": settings.backpressure_queue_depth_limit},
                    )
                )

        now = datetime.now(UTC)
        runnable = await repo.find_runnable(now=now, limit=settings.scheduler_max_enqueue_per_tick)
        inflight = await self._inflight_by_client(limit=5000)
        scheduler = FairScheduler(
            FairnessPolicy(
                per_client_concurrency=settings.scheduler_per_client_concurrency,
                max_enqueue_per_tick=settings.scheduler_max_enqueue_per_tick,
            )
        )
        selected = scheduler.select(runnable=runnable, inflight_by_client=inflight, now=now)
        SCHEDULER_SELECTED.set(len(selected))
        for job in selected:
            if overload.get(job.queue, False) and settings.backpressure_pause_low_priority and job.priority >= 4:
                continue
            self.celery.send_task(
                "gst_automation.celery_app.tasks.job_runner.run_job",
                args=[str(job.id)],
                queue=job.queue,
                priority=job.priority,
                countdown=0,
            )
            JOB_ENQUEUED_TOTAL.labels(queue=job.queue).inc()

        # Stabilization: periodic cleanup/retention audits (bounded work, leader-only).
        # Runs ~every 30s to avoid adding load on frequent watchdog ticks.
        if int(now.timestamp()) % 30 == 0:
            try:
                await CleanupInvariantScanner(settings=settings).scan(self.session)
            except Exception as exc:  # noqa: BLE001
                logger.warning("cleanup.scan_failed", err=str(exc))
            try:
                # Dry-run by default in watchdog; operators can execute via API/CLI.
                await RetentionService(settings=settings).enforce(self.session, dry_run=True, limit=100)
            except Exception as exc:  # noqa: BLE001
                logger.warning("retention.audit_failed", err=str(exc))
            try:
                await SelectorDriftDetector().record_anomalies(self.session)
            except Exception as exc:  # noqa: BLE001
                logger.warning("selector_drift.scan_failed", err=str(exc))

    async def _is_overloaded(self, *, limit: int) -> dict[str, bool]:
        # Redis broker uses per-queue lists; names are implementation-specific. Best-effort only.
        queues = ["critical", "downloads", "emails", "monitoring", "maintenance", "dead_letter"]
        overloaded: dict[str, bool] = {}
        for q in queues:
            # Celery's Redis transport typically uses "unacked" keys + list keys; check common list key.
            key = q
            try:
                depth = int(await self.redis_client.llen(key))  # type: ignore[no-any-return]
            except Exception:
                depth = 0
            overloaded[q] = depth >= limit
        return overloaded

    async def _inflight_by_client(self, *, limit: int) -> dict[uuid.UUID, int]:
        # Counts active leases per client for per-client concurrency enforcement.
        # Implemented with lightweight SQL; tolerant to missing client_id (treated separately).
        from sqlalchemy import func, select

        from gst_automation.db.models.orchestration.job import Job
        from gst_automation.db.models.orchestration.job_lease import JobLease

        res = await self.session.execute(
            select(Job.client_id, func.count(Job.id))
            .select_from(Job)
            .join(JobLease, JobLease.job_id == Job.id)
            .group_by(Job.client_id)
            .limit(limit)
        )
        out: dict[uuid.UUID, int] = {}
        for cid, count in res.all():
            if cid is None:
                continue
            out[cid] = int(count)
        return out
