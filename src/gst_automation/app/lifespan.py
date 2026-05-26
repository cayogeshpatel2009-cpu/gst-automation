from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import FastAPI

from gst_automation.core.logging import configure_logging, get_logger
from gst_automation.core.settings import Settings
from gst_automation.core.startup import StartupValidator
from gst_automation.core.db_diagnostics import validate_db_url
from gst_automation.db.session import Db
from gst_automation.telegram_bot.runtime import run_polling
from sqlalchemy import text


logger = get_logger(__name__)


async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.load()
    configure_logging(settings)
    app.state.settings = settings
    app.state.telegram_polling_task = None

    validator = StartupValidator(settings=settings)
    await validator.validate_or_raise()

    # Log sanitized DB target early (no passwords in logs).
    try:
        target = validate_db_url(str(settings.database_url), label="DATABASE_URL")
        logger.info("startup.db_target", target=target.display)
    except Exception:
        # StartupValidator already enforces correctness; avoid double-failing.
        pass

    app.state.db = Db(settings.database_url)
    await app.state.db.ping()
    # Best-effort schema diagnostics (no migration execution).
    try:
        async with app.state.db._engine.connect() as conn:  # noqa: SLF001
            r = await conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
            row = r.first()
            rev = str(row[0]) if row and row[0] else None
            logger.info("startup.db_schema", alembic_revision=rev)
    except Exception as exc:  # noqa: BLE001
        logger.warning("startup.db_schema_unavailable", err=str(exc))

    if bool(settings.telegram_enabled) and bool(settings.telegram_polling_enabled):
        try:
            task = asyncio.create_task(run_polling(settings=settings, db=app.state.db), name="telegram.polling")
            app.state.telegram_polling_task = task
            logger.info("telegram.polling.task_started")

            def _done_callback(t: asyncio.Task) -> None:
                try:
                    exc = t.exception()
                except asyncio.CancelledError:
                    logger.info("telegram.polling.task_cancelled")
                    return
                except Exception as e:  # noqa: BLE001
                    logger.exception("telegram.polling.task_exception", err=str(e))
                    return
                if exc is not None:
                    logger.exception("telegram.polling.task_failed", err=str(exc))
                else:
                    logger.warning("telegram.polling.task_exited")

            task.add_done_callback(_done_callback)
        except Exception as exc:  # noqa: BLE001
            logger.exception("telegram.polling.start_failed", err=str(exc))

    logger.info("startup.complete", environment=settings.environment)
    try:
        yield
    finally:
        logger.info("lifespan.shutdown.triggered")
        task = getattr(app.state, "telegram_polling_task", None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001
                logger.warning("telegram.polling.shutdown_failed", err=str(exc))
        await app.state.db.close()
        logger.info("shutdown.complete")
