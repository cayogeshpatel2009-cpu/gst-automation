from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.settings import Settings
from gst_automation.telegram_bot.service import TelegramAuditService


@dataclass(frozen=True, slots=True)
class TelegramPingValidator:
    settings: Settings
    session: AsyncSession

    async def run(self, *, timeout_seconds: int = 60) -> dict[str, Any]:
        if not bool(self.settings.telegram_enabled):
            return {"ok": False, "error": "TELEGRAM_ENABLED is false"}
        if not bool(self.settings.telegram_polling_enabled):
            return {"ok": False, "error": "TELEGRAM_POLLING_ENABLED is false"}
        if not self.settings.telegram_bot_token:
            return {"ok": False, "error": "TELEGRAM_BOT_TOKEN not set"}
        if not (self.settings.telegram_allowed_user_ids or []):
            return {"ok": False, "error": "TELEGRAM_ALLOWED_USER_IDS is empty"}

        bot = Bot(token=self.settings.telegram_bot_token)
        audit = TelegramAuditService(self.session)

        me = await bot.get_me()
        await audit.log_action(
            telegram_user_id=int(self.settings.telegram_allowed_user_ids[0]),
            action="ping.self_check",
            details={"bot_username": me.username, "bot_id": int(me.id)},
        )
        await self.session.commit()

        # Deterministic operator-driven validation:
        # send instructions and wait for operator to run /ping in the chat.
        target = int(self.settings.telegram_allowed_user_ids[0])
        await bot.send_message(
            chat_id=target,
            text="Telegram ping check: please send /ping in this chat within 60s.",
        )

        deadline = time.time() + float(timeout_seconds)
        while time.time() < deadline:
            rows = await audit.get_user_actions(telegram_user_id=target, limit=20)
            # Our runtime logs inbound updates as polling.update_received; /ping handler replies "pong" in chat.
            for r in rows:
                if r.action == "polling.update_received":
                    try:
                        await bot.send_message(chat_id=target, text="ping captured (audit OK)")
                    except Exception:
                        pass
                    # best-effort only: return the latest received update marker
                    await bot.session.close()
                    return {
                        "ok": True,
                        "bot_username": me.username,
                        "bot_id": int(me.id),
                        "received_at": datetime.now(UTC).isoformat(),
                    }
            await asyncio.sleep(1)

        await bot.session.close()
        return {"ok": False, "error": "timeout waiting for inbound /ping (no polling.update_received seen)"}
