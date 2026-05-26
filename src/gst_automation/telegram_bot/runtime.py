from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import redis.asyncio as redis
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, Update

from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.db.session import Db
from gst_automation.telegram_bot.service import TelegramAuditService, TelegramMessageService, TelegramUserService
from gst_automation.telegram_bot.client import TelegramClient, OperatorAction


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TelegramRuntime:
    settings: Settings
    db: Db
    redis_client: redis.Redis

    def build_dispatcher(self) -> Dispatcher:
        dp = Dispatcher()
        logger.info("telegram.dispatcher.created", dispatcher_id=id(dp))
        # Reuse existing command handlers from TelegramClient.
        tc = TelegramClient(self.settings, self.redis_client)
        dp.include_router(tc.router)
        logger.info(
            "telegram.dispatcher.handlers_registered",
            dispatcher_id=id(dp),
            router_count=len(getattr(dp, "sub_routers", []) or []),
            router0_message_handlers=len(getattr(dp.sub_routers[0].message, "handlers", [])) if getattr(dp, "sub_routers", None) else None,
        )

        # Catch-all update logger to prove inbound updates reach the dispatcher.
        dp.update.register(self._handle_any_update)

        # Add a minimal text handler for inbound message capture + allowlist enforcement.
        router = Router()
        # Important: do not consume command messages (e.g. /ping, /start) or we will block the TelegramClient router.
        router.message.register(self._handle_any_message, F.text & ~F.text.startswith("/"))
        dp.include_router(router)
        try:
            routers = list(getattr(dp, "sub_routers", []) or [])
            logger.info(
                "telegram.dispatcher.routers",
                dispatcher_id=id(dp),
                router_count=len(routers),
                message_handler_counts=[len(r.message.handlers) for r in routers],
                callback_handler_counts=[len(r.callback_query.handlers) for r in routers],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("telegram.dispatcher.routers_introspect_failed", err=str(exc))
        return dp

    async def _handle_any_update(self, update: Update) -> None:
        try:
            msg = getattr(update, "message", None)
            chat_id = int(msg.chat.id) if msg is not None else None
            user_id = int(msg.from_user.id) if (msg is not None and msg.from_user is not None) else None
            text = ((msg.text or "").strip() if msg is not None else "")[:200]
        except Exception:
            chat_id = None
            user_id = None
            text = ""
        logger.info(
            "telegram.raw_update.received",
            update_id=int(getattr(update, "update_id", 0) or 0),
            telegram_user_id=user_id,
            chat_id=chat_id,
            text=text,
        )
        # Ensure command messages (e.g. /ping) are still visible in audit logs for deterministic verification.
        try:
            msg = getattr(update, "message", None)
            if msg is None or msg.from_user is None:
                return
            txt = (msg.text or "").strip()
            if not txt.startswith("/"):
                return
            async with self.db.session() as session:
                audit = TelegramAuditService(session)
                await audit.log_action(
                    telegram_user_id=int(msg.from_user.id),
                    action="polling.update_received",
                    details={"chat_id": int(msg.chat.id), "is_command": True},
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("telegram.raw_update.audit_failed", err=str(exc))

    async def _handle_any_message(self, message: Message) -> None:
        logger.info("telegram.handler.invoked", message_id=getattr(message, "message_id", None))
        user = message.from_user
        if not user:
            return
        user_id = int(user.id)
        chat_id = int(message.chat.id)
        text = (message.text or "").strip()

        allowed = {int(x) for x in (self.settings.telegram_allowed_user_ids or [])}
        allowed_ok = (user_id in allowed) or (chat_id in allowed)
        logger.info(
            "telegram.update.received",
            telegram_user_id=user_id,
            chat_id=chat_id,
            allowed=bool(allowed_ok),
            text=text[:200],
        )
        # Deterministic operator feedback: acknowledge that the bot saw the message.
        # This is intentionally short and contains no secrets.
        try:
            await message.answer("received")
        except Exception as exc:  # noqa: BLE001
            logger.warning("telegram.message.answer_failed", err=str(exc))

        async with self.db.session() as session:
            audit = TelegramAuditService(session)
            users = TelegramUserService(session)
            msgs = TelegramMessageService(session)

            await msgs.log_message(
                telegram_message_id=int(message.message_id),
                telegram_user_id=user_id,
                direction="receive",
                message_type="text",
                content=text,
            )
            await audit.log_action(
                telegram_user_id=user_id,
                action="polling.update_received",
                details={"chat_id": chat_id, "text_len": len(text)},
            )

            if not allowed_ok:
                await audit.log_action(
                    telegram_user_id=user_id,
                    action="polling.update_rejected",
                    details={"chat_id": chat_id},
                )
                await session.commit()
                logger.warning("telegram.update_rejected", telegram_user_id=user_id, chat_id=chat_id)
                return

            # Register/update user row for operator mapping.
            try:
                await users.register_user(
                    telegram_user_id=user_id,
                    telegram_chat_id=chat_id,
                    telegram_username=getattr(user, "username", None),
                    telegram_first_name=getattr(user, "first_name", None),
                    telegram_last_name=getattr(user, "last_name", None),
                    role="operator",
                )
            except Exception:
                pass
            await session.commit()

        logger.info("telegram.update_received", telegram_user_id=user_id, chat_id=chat_id, text=text[:200])

        # Deterministic captcha reply routing (minimal):
        # If a captcha_state.json exists, route operator text to that checkpoint.
        # This keeps HITL inside existing checkpoint/redis channel.
        try:
            state_path = Path(self.settings.data_dir) / "captcha_state.json"
            if state_path.exists() and text:
                obj = json.loads(state_path.read_text(encoding="utf-8"))
                cp = obj.get("checkpoint_id")
                status = str(obj.get("status") or "")
                if cp and status.startswith("waiting"):
                    checkpoint_id = uuid.UUID(str(cp))
                    action = OperatorAction(
                        kind="captcha_reply",
                        checkpoint_id=checkpoint_id,
                        value=text,
                        timestamp=datetime.now(UTC),
                    )
                    tc = TelegramClient(self.settings, self.redis_client)
                    await tc.enqueue_operator_action(checkpoint_id, action)
                    logger.info(
                        "telegram.captcha_reply_routed",
                        checkpoint_id=str(checkpoint_id),
                        telegram_user_id=user_id,
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("telegram.captcha_reply_route_failed", err=str(exc))
        finally:
            logger.info("telegram.handler.completed", message_id=getattr(message, "message_id", None))


async def run_polling(*, settings: Settings, db: Db) -> None:
    if not settings.telegram_enabled or not settings.telegram_polling_enabled:
        logger.info("telegram.polling.disabled")
        return
    if not settings.telegram_bot_token:
        logger.warning("telegram.polling.missing_token")
        return

    r = redis.from_url(settings.redis_url)
    bot = Bot(token=settings.telegram_bot_token)
    runtime = TelegramRuntime(settings=settings, db=db, redis_client=r)
    dp = runtime.build_dispatcher()
    bot_username = None
    bot_id = None
    try:
        me = await bot.get_me()
        bot_id = int(me.id)
        bot_username = me.username
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram.polling.bot_me_failed", err=str(exc))

    logger.info(
        "telegram.polling.start",
        bot_username=bot_username,
        bot_id=bot_id,
        dispatcher_id=id(dp),
        allowed_updates=["message", "callback_query"],
    )
    try:
        heartbeat: asyncio.Task | None = asyncio.create_task(_polling_heartbeat(), name="telegram.polling.heartbeat")
        logger.info("telegram.polling.active")
        # For deterministic debugging: log if there are pending updates before polling begins.
        try:
            pending = await bot.get_updates(limit=3, timeout=0)
            if pending:
                logger.info(
                    "telegram.polling.preexisting_updates",
                    count=len(pending),
                    update_ids=[u.update_id for u in pending],
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("telegram.polling.preexisting_updates_failed", err=str(exc))

        logger.info("telegram.polling.start_polling", dispatcher_id=id(dp))
        await dp.start_polling(bot)
        logger.warning("telegram.polling.exited")
    except asyncio.CancelledError:
        logger.info("telegram.polling.cancelled")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("telegram.polling.exception", err=str(exc))
        raise
    finally:
        try:
            if heartbeat is not None:
                heartbeat.cancel()
                await heartbeat
        except Exception:
            pass
        try:
            await bot.session.close()
        except Exception:
            pass
        try:
            await r.aclose()
        except Exception:
            pass


async def _polling_heartbeat() -> None:
    while True:
        await asyncio.sleep(30)
        logger.info("telegram.polling.heartbeat")
