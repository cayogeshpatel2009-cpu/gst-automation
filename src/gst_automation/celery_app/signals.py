from __future__ import annotations

import os
import threading
import time

from celery.signals import worker_process_init, worker_process_shutdown

from gst_automation.core.logging import get_logger
from gst_automation.celery_app.runtime import run_async
from gst_automation.orchestration.worker_runtime import WorkerRuntime
from gst_automation.browser.pool import get_pool
from gst_automation.core.settings import Settings


logger = get_logger(__name__)

_stop_event = threading.Event()
_thread: threading.Thread | None = None


def _heartbeat_loop() -> None:
    # Runs in each worker process; records heartbeat every 10 seconds.
    while not _stop_event.is_set():
        try:
            run_async(WorkerRuntime.heartbeat_tick())
        except Exception as exc:  # noqa: BLE001
            logger.warning("worker.heartbeat_loop_error", err=str(exc))
        _stop_event.wait(10.0)


@worker_process_init.connect
def _on_worker_process_init(**_: object) -> None:
    global _thread
    _stop_event.clear()
    _thread = threading.Thread(target=_heartbeat_loop, name="gst-heartbeat", daemon=True)
    _thread.start()
    logger.info("worker.process_init", pid=os.getpid())


@worker_process_shutdown.connect
def _on_worker_process_shutdown(**_: object) -> None:
    _stop_event.set()
    try:
        run_async(get_pool(Settings.load()).stop())
    except Exception as exc:  # noqa: BLE001
        logger.warning("browser.pool_stop_failed", err=str(exc))
    logger.info("worker.process_shutdown", pid=os.getpid())
