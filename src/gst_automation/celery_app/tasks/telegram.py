"""Celery tasks for Telegram bot operations."""

from __future__ import annotations

from celery import shared_task

from gst_automation.celery_app.runtime import run_async
from gst_automation.orchestration.worker_runtime import WorkerRuntime


@shared_task(name="gst_automation.celery_app.tasks.telegram.send_morning_reminder")
def send_morning_reminder() -> None:
    """Send morning reminder to all operators."""
    run_async(_send_morning_reminder_async())


@shared_task(name="gst_automation.celery_app.tasks.telegram.send_captcha_request")
def send_captcha_request(*, checkpoint_id: str, job_id: str, client_name: str, gstin: str, image_path: str) -> None:
    """Send CAPTCHA request to operators."""
    run_async(_send_captcha_request_async(checkpoint_id=checkpoint_id, job_id=job_id, client_name=client_name, gstin=gstin, image_path=image_path))


async def _send_morning_reminder_async() -> None:
    """Async implementation of send_morning_reminder."""
    from gst_automation.core.settings import Settings
    from gst_automation.db.session import Db
    import redis.asyncio as redis
    from gst_automation.telegram_bot.scheduler import TelegramReminderService

    settings = Settings.load()
    db = Db(settings.database_url)
    r = redis.from_url(settings.redis_url)

    try:
        async with db.session() as session:
            reminder_service = TelegramReminderService(settings, session, r)
            await reminder_service.send_morning_reminder()
            await session.commit()
    finally:
        await r.close()
        await db.close()


async def _send_captcha_request_async(
    *,
    checkpoint_id: str,
    job_id: str,
    client_name: str,
    gstin: str,
    image_path: str,
) -> None:
    """Async implementation of send_captcha_request."""
    import uuid
    from gst_automation.core.settings import Settings
    from gst_automation.db.session import Db
    import redis.asyncio as redis
    from gst_automation.telegram_bot.scheduler import TelegramCaptchaService

    settings = Settings.load()
    db = Db(settings.database_url)
    r = redis.from_url(settings.redis_url)

    try:
        async with db.session() as session:
            captcha_service = TelegramCaptchaService(settings, session, r)
            await captcha_service.send_captcha_request(
                checkpoint_id=uuid.UUID(checkpoint_id),
                job_id=uuid.UUID(job_id),
                client_display_name=client_name,
                gstin=gstin,
                captcha_image_path=image_path,
            )
            await session.commit()
    finally:
        await r.close()
        await db.close()
