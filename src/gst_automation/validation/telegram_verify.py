from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.telegram_bot.service import TelegramAuditService, TelegramUserService


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TelegramRoundTripVerifier:
    settings: Settings
    session: AsyncSession

    async def run(self, *, timeout_seconds: int = 120, debug: bool = False) -> dict[str, Any]:
        if not bool(self.settings.telegram_enabled):
            return {"ok": False, "error": "TELEGRAM_ENABLED is false"}
        if not self.settings.telegram_bot_token:
            return {"ok": False, "error": "TELEGRAM_BOT_TOKEN not set"}
        allowed = list(self.settings.telegram_allowed_user_ids or [])
        if not allowed:
            return {"ok": False, "error": "TELEGRAM_ALLOWED_USER_IDS is empty"}
        allowed_set = {int(x) for x in allowed}

        audit = TelegramAuditService(self.session)
        users = TelegramUserService(self.session)

        bot = Bot(token=self.settings.telegram_bot_token)
        try:
            try:
                me = await bot.get_me()
            except Exception as exc:  # noqa: BLE001
                await audit.log_action(
                    telegram_user_id=allowed[0],
                    action="verify.bot_init_failed",
                    details={"err": str(exc)},
                )
                return {"ok": False, "error": f"telegram bot init failed: {exc}"}

            # Webhook conflicts disable getUpdates; report deterministic state.
            webhook = await bot.get_webhook_info()
            if debug:
                print("[telegram.verify] webhook_info=", webhook.model_dump())

            await audit.log_action(
                telegram_user_id=allowed[0],
                action="verify.bot_initialized",
                details={"bot_id": me.id, "bot_username": me.username},
            )

            # Establish baseline offset so we only consider new updates for this verification window.
            try:
                init_updates = await bot.get_updates(limit=1, timeout=0)
                offset = (init_updates[-1].update_id + 1) if init_updates else None
            except Exception as exc:  # noqa: BLE001
                await audit.log_action(
                    telegram_user_id=allowed[0],
                    action="verify.get_updates_failed",
                    details={"err": str(exc)},
                )
                return {"ok": False, "error": f"getUpdates failed: {exc}"}
            if debug:
                print("[telegram.verify] bot_username=", me.username)
                print("[telegram.verify] allowed_user_ids=", allowed)
                print("[telegram.verify] initial_offset=", offset)

            sent: dict[int, int] = {}
            send_errors: dict[int, str] = {}
            for uid in allowed:
                try:
                    msg = await bot.send_message(chat_id=uid, text="GST Automation Telegram test successful")
                    sent[uid] = int(msg.message_id)
                    await audit.log_action(
                        telegram_user_id=uid,
                        action="verify.test_message_sent",
                        details={"message_id": int(msg.message_id)},
                    )
                except Exception as exc:  # noqa: BLE001
                    await audit.log_action(telegram_user_id=uid, action="verify.send_failed", details={"err": str(exc)})
                    send_errors[uid] = str(exc)
                    if debug:
                        print("[telegram.verify] send_failed user_or_chat_id=", uid, "err=", str(exc))
            if debug:
                print("[telegram.verify] sent_message_ids=", sent)
                if send_errors:
                    print("[telegram.verify] send_errors=", send_errors)

            deadline = time.time() + float(timeout_seconds)
            received: dict[str, Any] | None = None
            blocked: list[int] = []
            updates_seen = 0
            while time.time() < deadline and received is None:
                try:
                    updates = await bot.get_updates(
                        offset=offset,
                        timeout=int(self.settings.telegram_polling_timeout_seconds or 30),
                    )
                except Exception as exc:  # noqa: BLE001
                    await audit.log_action(
                        telegram_user_id=allowed[0],
                        action="verify.poll_failed",
                        details={"err": str(exc)},
                    )
                    continue
                if updates:
                    updates_seen += len(updates)
                    if debug:
                        print(f"[telegram.verify] updates_batch size={len(updates)}")

                for upd in updates:
                    offset = upd.update_id + 1
                    msg = getattr(upd, "message", None)
                    if debug:
                        print("[telegram.verify] update_id=", upd.update_id, "has_message=", msg is not None)
                    if msg is None:
                        continue
                    from_user = msg.from_user
                    if not from_user:
                        continue
                    uid = int(from_user.id)
                    chat_id = int(msg.chat.id)
                    text = (msg.text or "").strip()
                    if debug:
                        print("[telegram.verify] msg from_user_id=", uid, "chat_id=", chat_id, "text=", text[:200])
                    # Allowlist may include either user_id (private chat) or chat_id (groups).
                    if uid not in allowed_set and chat_id not in allowed_set:
                        blocked.append(uid)
                        await audit.log_action(
                            telegram_user_id=uid,
                            action="verify.blocked_user_update",
                            details={"text": text[:200]},
                        )
                        continue
                    # Best-effort user registration/update.
                    try:
                        await users.register_user(
                            telegram_user_id=uid,
                            telegram_chat_id=chat_id,
                            telegram_username=getattr(from_user, "username", None),
                            telegram_first_name=getattr(from_user, "first_name", None),
                            telegram_last_name=getattr(from_user, "last_name", None),
                            role="operator",
                        )
                    except Exception:
                        pass

                    is_reply_to_test = False
                    if getattr(msg, "reply_to_message", None) is not None:
                        mid = int(getattr(msg.reply_to_message, "message_id", 0) or 0)
                        is_reply_to_test = (sent.get(uid) == mid)
                    if text:
                        received = {
                            "telegram_user_id": uid,
                            "chat_id": chat_id,
                            "text": text,
                            "reply_to_test_message": bool(is_reply_to_test),
                            "message_id": int(getattr(msg, "message_id", 0) or 0),
                            "received_at": datetime.now(UTC).isoformat(),
                        }
                        await audit.log_action(
                            telegram_user_id=uid,
                            action="verify.reply_received",
                            details={"reply_to_test": bool(is_reply_to_test), "text_len": len(text)},
                        )
                        break

            ok = received is not None
            return {
                "ok": ok,
                "bot_username": me.username,
                "allowed_user_ids": allowed,
                "sent_message_ids": sent,
                "send_errors": send_errors,
                "received": received,
                "blocked_updates_seen": sorted(set(blocked)),
                "updates_seen": updates_seen,
            }
        finally:
            await bot.session.close()
