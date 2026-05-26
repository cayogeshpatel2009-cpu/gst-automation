from __future__ import annotations

import uuid

from celery import shared_task

from gst_automation.celery_app.runtime import run_async
from gst_automation.orchestration.worker_runtime import WorkerRuntime


@shared_task(name="gst_automation.celery_app.tasks.job_runner.run_job", bind=True)
def run_job(self: object, job_id: str) -> None:
    """Execute one durable job by id (service-layer orchestration)."""
    parsed = uuid.UUID(job_id)
    run_async(WorkerRuntime.run_job(job_id=parsed))

