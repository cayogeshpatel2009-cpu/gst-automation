from __future__ import annotations

import asyncio
import os
import socket
import uuid
from dataclasses import dataclass

import psutil
import redis.asyncio as redis

from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.db.session import Db
from gst_automation.locks.redis_lock import RedisLockManager
from gst_automation.orchestration.handlers.registry import HandlerRegistry
from gst_automation.orchestration.handlers.base import JobHandlerV2
from gst_automation.orchestration.handlers.context import JobRunContext
from gst_automation.orchestration.services.job_service import JobService
from gst_automation.orchestration.worker_identity import compute_worker_name
from gst_automation.orchestration.repositories.worker_repo import WorkerRepo
from gst_automation.celery_app.client import get_celery
from gst_automation.watchdog.service import WatchdogService
from gst_automation.retry.engine import RetryEngine
from gst_automation.orchestration.repositories.retry_repo import RetryRepo
from gst_automation.orchestration.services.dlq_service import DlqService
from gst_automation.orchestration.events import EventContext
from gst_automation.orchestration.services.transition_service import TransitionService
from gst_automation.orchestration.budgets import BudgetRegistry
from gst_automation.browser.pool import get_pool
from gst_automation.browser.session import ContextIsolationEngine
from gst_automation.browser.watchdog import BrowserWatchdog
from gst_automation.portal.sessions import SessionManager
from gst_automation.gst.execution_validator import GstExecutionValidator
from gst_automation.gst.forensics import GstForensicsPackager


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WorkerRuntime:
    """Runtime entrypoints invoked by Celery wrappers (sync tasks call these async methods)."""

    @staticmethod
    async def run_job(*, job_id: uuid.UUID) -> None:
        settings = Settings.load()
        db = Db(settings.database_url)
        r = redis.from_url(settings.redis_url)
        lock_mgr = RedisLockManager(r)

        queues = _queues_from_env()
        worker_name = compute_worker_name(pid=os.getpid(), queues=queues)
        handlers = HandlerRegistry.build_default()

        async def _lease_heartbeat_loop(job_id_str: str, lease_token: str) -> None:
            # Heartbeat at 1/3 of TTL.
            ttl = 60
            interval = max(int(ttl / 3), 5)
            while True:
                await asyncio.sleep(interval)
                async with db.session() as session:
                    from gst_automation.orchestration.repositories.lease_repo import LeaseRepo

                    repo = LeaseRepo(session)
                    new_fence = await repo.heartbeat(job_id=job_id, lease_token=lease_token, ttl_seconds=ttl)
                    await session.commit()
                if new_fence is None:
                    logger.warning("lease.heartbeat_failed", job_id=job_id_str, worker_name=worker_name)
                else:
                    nonlocal fencing_token
                    fencing_token = int(new_fence)

        async def _lock_renew_loop() -> None:
            assert lock_handle is not None
            ttl = 120
            while True:
                await asyncio.sleep(40)
                try:
                    ok = await lock_mgr.renew(lock_handle, ttl_seconds=ttl)
                    if not ok:
                        logger.warning("lock.renew_failed", job_id=job_id_str, lock_name=lock_handle.name)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("lock.renew_error", job_id=job_id_str, err=str(exc))

        job_id_uuid = job_id  # typed as uuid.UUID by caller
        job_id_str = str(job_id_uuid)

        lease_token: str | None = None
        attempt_id: str | None = None
        attempt_uuid: uuid.UUID | None = None
        attempt_no: int | None = None
        fencing_token: int | None = None
        event_ctx: EventContext | None = None
        heartbeat_task: asyncio.Task[None] | None = None
        lock_renew_task: asyncio.Task[None] | None = None
        lock_handle = None
        try:
            async with db.session() as session:
                svc = JobService(session)
                lease, attempt = await svc.acquire_lease(job_id=job_id_uuid, worker_name=worker_name, actor=worker_name)
                lease_token = lease.lease_token
                attempt_id = str(attempt.id)
                attempt_uuid = attempt.id
                attempt_no = attempt.attempt_no
                fencing_token = int(lease.fencing_token)
                event_ctx = EventContext(
                    actor=worker_name,
                    trace_id=attempt.trace_id,
                    correlation_id=attempt.correlation_id,
                    run_id=attempt.run_id,
                )
                await session.commit()

            lock_handle = await lock_mgr.acquire(name=f"job:{job_id_str}", owner=worker_name, ttl_seconds=120)
            if lock_handle is None:
                # Another worker holds lock; reschedule quickly.
                assert lease_token is not None
                assert attempt_uuid is not None
                assert fencing_token is not None
                assert event_ctx is not None
                async with db.session() as session:
                    svc = JobService(session)
                    await svc.schedule_retry(
                        job_id=job_id_uuid,
                        attempt_id=attempt_uuid,
                        lease_token=lease_token,
                        fencing_token=fencing_token,
                        backoff_seconds=15,
                        actor=worker_name,
                        ctx=event_ctx,
                    )
                    await session.commit()
                return

            heartbeat_task = asyncio.create_task(_lease_heartbeat_loop(job_id_str, lease_token))
            lock_renew_task = asyncio.create_task(_lock_renew_loop())

            async with db.session() as session:
                assert event_ctx is not None
                ts = TransitionService(session)
                await ts.transition(
                    job_id=job_id_uuid,
                    to_state="running",
                    reason_code="worker_started",
                    reason_details={"worker_name": worker_name},
                    ctx=event_ctx,
                )
                await session.commit()

            async with db.session() as session:
                from gst_automation.orchestration.repositories.job_repo import JobRepo

                repo = JobRepo(session)
                job = await repo.get(job_id_uuid)
                if job is None:
                    raise RuntimeError("Job missing after lease")
                handler = handlers.get(job.kind)
                if handler is None:
                    raise RuntimeError(f"No handler registered for job kind: {job.kind}")
                # Browser infrastructure warm path: allocate isolated context even for noop jobs
                # to validate lifecycle/cleanup and surface instability early.
                gen = await WorkerRepo(session).get_generation(worker_name=worker_name)
                pool = get_pool(settings)
                isolator = ContextIsolationEngine(settings, pool)
                storage_state: dict | None = None
                if job.kind in {"gstr2b_download", "gst_observation_session"}:
                    # Session-first mode: attempt to load latest storage_state for this client.
                    try:
                        import json as _json

                        payload = _json.loads(job.payload_json or "{}")
                        client_id = payload.get("client_id") or (str(job.client_id) if job.client_id else None)
                        if client_id:
                            storage_state = await SessionManager(settings=settings).load_latest_storage_state(
                                session, client_id=uuid.UUID(client_id), profile="gst"
                            )
                    except Exception:
                        storage_state = None
                bs = await isolator.allocate(
                    session,
                    job_id=job.id,
                    worker_name=worker_name,
                    worker_generation=gen,
                    lease_token=lease_token,
                    fencing_token=fencing_token,
                    storage_state=storage_state,
                )
                budget = BudgetRegistry().budget_for(job.kind)
                try:
                    assert attempt_uuid is not None
                    assert attempt_no is not None
                    assert event_ctx is not None
                    ctx = JobRunContext(
                        settings=settings,
                        session=session,
                        worker_name=worker_name,
                        worker_generation=gen,
                        lease_token=lease_token,
                        fencing_token=fencing_token,
                        attempt_id=attempt_uuid,
                        attempt_no=attempt_no,
                        event_ctx=event_ctx,
                        browser_session=bs,
                    )
                    if isinstance(handler, JobHandlerV2):
                        await asyncio.wait_for(
                            handler.run_with_context(job_id=job.id, payload_json=job.payload_json, ctx=ctx),
                            timeout=float(budget.hard_seconds),
                        )
                    else:
                        await asyncio.wait_for(
                            handler.run(job_id=job.id, payload_json=job.payload_json),
                            timeout=float(budget.hard_seconds),
                        )
                finally:
                    await isolator.close(session, bs)
                await session.commit()

            async with db.session() as session:
                assert lease_token is not None
                assert attempt_uuid is not None
                assert fencing_token is not None
                assert event_ctx is not None
                svc = JobService(session)
                await svc.complete_job(
                    job_id=job_id_uuid,
                    attempt_id=attempt_uuid,
                    lease_token=lease_token,
                    fencing_token=fencing_token,
                    actor=worker_name,
                    ctx=event_ctx,
                )

                # Post-completion hardening validators (best-effort; must not fail the job completion path).
                try:
                    from gst_automation.orchestration.repositories.job_repo import JobRepo

                    job_row = await JobRepo(session).get(job_id_uuid)
                    if job_row and job_row.kind == "gstr2b_download":
                        import json as _json
                        from pathlib import Path as _Path

                        payload = _json.loads(job_row.payload_json or "{}")
                        client_id = payload.get("client_id")
                        period = payload.get("period_yyyy_mm") or payload.get("period")
                        if client_id and period:
                            rep = await GstExecutionValidator().validate_job(
                                session,
                                job_id=job_row.id,
                                client_id=uuid.UUID(str(client_id)),
                                period=str(period),
                                require_email_sent=False,
                                artifacts_root=_Path(settings.browser_artifacts_dir),
                            )
                            if rep.status != "ok":
                                try:
                                    await GstForensicsPackager(artifacts_root=_Path(settings.browser_artifacts_dir)).package_job(
                                        session, job_id=job_row.id
                                    )
                                except Exception as _exc2:  # noqa: BLE001
                                    logger.warning("hardening.forensics_pack_failed", job_id=job_id_str, err=str(_exc2))
                except Exception as _exc:  # noqa: BLE001
                    logger.warning("hardening.post_validator_failed", job_id=job_id_str, err=str(_exc))
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("job.run_failed", job_id=job_id_str, worker_name=worker_name, err=str(exc))
            if lease_token and attempt_uuid and attempt_no is not None:
                engine = RetryEngine()
                decision = engine.decide(exc, attempt_no=attempt_no)
                async with db.session() as session:
                    if decision.action == "retry":
                        rr = RetryRepo(session)
                        await rr.add(
                            job_id=job_id_uuid,
                            attempt_id=attempt_uuid,
                            classification=decision.classification,
                            backoff_seconds=decision.backoff_seconds,
                            jitter_seconds=decision.jitter_seconds,
                            reason=decision.reason,
                        )
                        svc = JobService(session)
                        await svc.schedule_retry(
                            job_id=job_id_uuid,
                            attempt_id=attempt_uuid,
                            lease_token=lease_token,
                            fencing_token=fencing_token or 0,
                            backoff_seconds=decision.backoff_seconds + decision.jitter_seconds,
                            actor=worker_name,
                            ctx=event_ctx,
                        )
                    else:
                        from gst_automation.orchestration.repositories.job_repo import JobRepo

                        repo = JobRepo(session)
                        job = await repo.get(job_id_uuid)
                        payload_json = job.payload_json if job else "{}"
                        kind = job.kind if job else "unknown"
                        dlq = DlqService(session)
                        await dlq.dead_letter(
                            job_id=job_id_uuid,
                            job_kind=kind,
                            payload_json=payload_json,
                            failure={"error": str(exc), "classification": decision.classification},
                            actor=worker_name,
                        )
                    await session.commit()
        finally:
            if heartbeat_task:
                heartbeat_task.cancel()
            if lock_renew_task:
                lock_renew_task.cancel()
            if lock_handle is not None:
                try:
                    await lock_mgr.release(lock_handle)
                except Exception:
                    logger.warning("lock.release_failed", job_id=job_id_str, lock_name=lock_handle.name)
            await r.close()
            await db.close()

    @staticmethod
    async def heartbeat_tick() -> None:
        settings = Settings.load()
        db = Db(settings.database_url)
        queues = _queues_from_env()
        worker_name = compute_worker_name(pid=os.getpid(), queues=queues)

        proc = psutil.Process(os.getpid())
        mem = int(proc.memory_info().rss)
        cpu = int(proc.cpu_percent(interval=None))
        health_state = "ok"
        hostname = socket.gethostname()

        async with db.session() as session:
            repo = WorkerRepo(session)
            await repo.upsert_worker(worker_name=worker_name, hostname=hostname, pid=os.getpid(), queues=queues)
            await repo.append_heartbeat(
                worker_name=worker_name,
                cpu_percent=cpu,
                memory_rss_bytes=mem,
                active_jobs=0,
                health_state=health_state,
            )
            # Browser pool telemetry (best-effort per-process).
            try:
                get_pool(settings).update_rss_metric()
            except Exception:
                pass
            await session.commit()
        await db.close()

    @staticmethod
    async def watchdog_tick() -> None:
        settings = Settings.load()
        db = Db(settings.database_url)
        r = redis.from_url(settings.redis_url)
        celery = get_celery()
        async with db.session() as session:
            svc = WatchdogService(session=session, celery=celery, redis_client=r)
            await svc.tick()
            # Browser watchdog is per-process; still useful in beat-triggered tasks on monitoring workers.
            try:
                await BrowserWatchdog(settings=settings, pool=get_pool(settings)).tick(
                    session, worker_name="watchdog"
                )
            except Exception:
                pass
            await session.commit()
        await r.close()
        await db.close()


def _queues_from_env() -> list[str]:
    raw = os.getenv("WORKER_QUEUES", "downloads")
    return [q.strip() for q in raw.split(",") if q.strip()]
