from __future__ import annotations

from celery import shared_task

from gst_automation.celery_app.runtime import run_async
from gst_automation.orchestration.worker_runtime import WorkerRuntime


@shared_task(name="gst_automation.celery_app.tasks.maintenance.worker_heartbeat")
def worker_heartbeat() -> None:
    run_async(WorkerRuntime.heartbeat_tick())


@shared_task(name="gst_automation.celery_app.tasks.maintenance.watchdog_tick")
def watchdog_tick() -> None:
    run_async(WorkerRuntime.watchdog_tick())

