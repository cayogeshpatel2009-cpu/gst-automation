from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from datetime import time

from gst_automation.core.settings import Settings
from gst_automation.celery_app.queues import QUEUES


def _telegram_reminder_schedule():
    """Calculate cron schedule for Telegram morning reminder."""
    settings = Settings.load()
    hour = settings.telegram_reminder_hour or 9
    minute = settings.telegram_reminder_minute or 0
    # Run at configured time on weekdays (Mon-Fri: 0-4)
    return crontab(hour=hour, minute=minute, day_of_week="mon-fri")


def build_celery(settings: Settings) -> Celery:
    """Build a production-configured Celery app from settings."""
    app = Celery("gst_automation")
    # Register Celery signal handlers (heartbeat loop, graceful cleanup hooks).
    from gst_automation.celery_app import signals as _signals  # noqa: F401

    app.conf.update(
        broker_url=settings.celery_broker_url,
        result_backend=settings.celery_result_backend,
        task_default_exchange="gst",
        task_default_exchange_type="direct",
        task_default_routing_key="downloads",
        task_default_queue="downloads",
        task_queues=QUEUES,
        task_acks_late=settings.celery_acks_late,
        worker_prefetch_multiplier=settings.celery_prefetch_multiplier,
        broker_transport_options={
            # Redis visibility timeout for unacked tasks (seconds).
            "visibility_timeout": max(settings.celery_task_time_limit_seconds * 2, 3600),
        },
        task_time_limit=settings.celery_task_time_limit_seconds,
        task_soft_time_limit=settings.celery_task_soft_time_limit_seconds,
        task_track_started=True,
        task_default_priority=5,
        task_queue_max_priority=9,
        accept_content=["json"],
        task_serializer="json",
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_routes={
            "gst_automation.celery_app.tasks.job_runner.run_job": {"queue": "downloads", "priority": 5},
            "gst_automation.celery_app.tasks.maintenance.worker_heartbeat": {"queue": "monitoring", "priority": 8},
            "gst_automation.celery_app.tasks.maintenance.watchdog_tick": {"queue": "monitoring", "priority": 9},
        },
        beat_schedule={
            "watchdog-tick": {
                "task": "gst_automation.celery_app.tasks.maintenance.watchdog_tick",
                "schedule": 15.0,
            },
            "telegram-morning-reminder": {
                "task": "gst_automation.celery_app.tasks.telegram.send_morning_reminder",
                "schedule": _telegram_reminder_schedule(),
            },
        },
        task_default_rate_limit=None,
    )
    # Autodiscover expects package roots and appends `.tasks` by default.
    # Use `gst_automation.celery_app` so it imports `gst_automation.celery_app.tasks`,
    # and `gst_automation.celery_app.tasks.__init__` will import task modules.
    app.autodiscover_tasks(["gst_automation.celery_app"])
    return app
