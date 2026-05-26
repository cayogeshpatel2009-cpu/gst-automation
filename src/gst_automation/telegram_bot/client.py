"""Telegram bot integration module.

Provides operator-triggered GST orchestration via Telegram:
- Operator receives morning reminders
- Operator confirms via buttons
- CAPTCHA screenshots sent to operator
- Operator replies with CAPTCHA text
- System auto-inserts and continues
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Awaitable, Any

import redis.asyncio as redis
from aiogram import Bot, Router, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.db.models.telegram import TelegramUser, TelegramMessage, TelegramAudit
from gst_automation.db.models.gst.operator_checkpoint import OperatorCheckpoint
from gst_automation.telegram_bot.commands import build_command_router

logger = get_logger(__name__)


@dataclass(frozen=True)
class TelegramConfig:
    """Telegram bot configuration."""

    token: str
    api_key: str | None = None  # For message templates API
    webhook_url: str | None = None  # If None, use long polling
    polling_timeout_seconds: int = 30
    image_upload_timeout_seconds: int = 60


@dataclass(frozen=True)
class OperatorAction:
    """Action received from operator via Telegram."""

    kind: str  # "captcha_reply", "otp_reply", "button_callback"
    checkpoint_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    value: str = ""
    callback_data: str | None = None
    timestamp: datetime | None = None


class TelegramClient:
    """Core Telegram bot client."""

    def __init__(self, settings: Settings, redis_client: redis.Redis) -> None:
        self.settings = settings
        self.redis = redis_client
        self.config = TelegramConfig(
            token=settings.telegram_bot_token,
            api_key=settings.telegram_api_key,
            webhook_url=settings.telegram_webhook_url,
            polling_timeout_seconds=int(settings.telegram_polling_timeout_seconds or 30),
        )
        self.bot = Bot(token=self.config.token)
        self.router = build_command_router(settings=self.settings, redis_client=self.redis)

    async def send_message(
        self,
        telegram_user_id: int,
        text: str,
        buttons: list[tuple[str, str]] | None = None,
        checkpoint_id: uuid.UUID | None = None,
    ) -> int | None:
        """Send text message with optional inline buttons.
        
        Returns: Telegram message ID if successful.
        """
        try:
            markup = None
            if buttons:
                keyboard = []
                for button_text, callback_data in buttons:
                    keyboard.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
                markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

            msg = await self.bot.send_message(
                chat_id=telegram_user_id,
                text=text,
                reply_markup=markup,
            )
            logger.info(
                "telegram.message_sent",
                user_id=telegram_user_id,
                message_id=msg.message_id,
                checkpoint_id=str(checkpoint_id) if checkpoint_id else None,
            )
            return msg.message_id
        except Exception as exc:
            logger.error(
                "telegram.send_message_failed",
                user_id=telegram_user_id,
                err=str(exc),
                checkpoint_id=str(checkpoint_id) if checkpoint_id else None,
            )
            return None

    async def send_photo(
        self,
        telegram_user_id: int,
        photo_path: Path,
        caption: str = "",
        buttons: list[tuple[str, str]] | None = None,
        checkpoint_id: uuid.UUID | None = None,
    ) -> int | None:
        """Send photo with optional caption and buttons.
        
        Returns: Telegram message ID if successful.
        """
        try:
            if not photo_path.exists():
                logger.error(
                    "telegram.photo_not_found",
                    photo_path=str(photo_path),
                    user_id=telegram_user_id,
                )
                return None

            markup = None
            if buttons:
                keyboard = []
                for button_text, callback_data in buttons:
                    keyboard.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
                markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

            with open(photo_path, "rb") as f:
                msg = await self.bot.send_photo(
                    chat_id=telegram_user_id,
                    photo=InputFile(f, filename=photo_path.name),
                    caption=caption,
                    reply_markup=markup,
                )
            logger.info(
                "telegram.photo_sent",
                user_id=telegram_user_id,
                message_id=msg.message_id,
                checkpoint_id=str(checkpoint_id) if checkpoint_id else None,
            )
            return msg.message_id
        except Exception as exc:
            logger.error(
                "telegram.send_photo_failed",
                photo_path=str(photo_path),
                user_id=telegram_user_id,
                err=str(exc),
                checkpoint_id=str(checkpoint_id) if checkpoint_id else None,
            )
            return None

    async def enqueue_operator_action(
        self,
        checkpoint_id: uuid.UUID,
        action: OperatorAction,
    ) -> bool:
        """Queue operator action from Telegram for checkpoint processing."""
        try:
            key = f"telegram:action:{checkpoint_id}"
            payload = json.dumps(
                {
                    "kind": action.kind,
                    "checkpoint_id": str(action.checkpoint_id) if action.checkpoint_id else None,
                    "job_id": str(action.job_id) if action.job_id else None,
                    "value": action.value,
                    "callback_data": action.callback_data,
                    "timestamp": (action.timestamp or datetime.now(UTC)).isoformat(),
                }
            )
            await self.redis.rpush(key, payload)
            # Set TTL so stale actions expire
            await self.redis.expire(key, 3600)
            logger.info(
                "telegram.action_enqueued",
                checkpoint_id=str(checkpoint_id),
                action_kind=action.kind,
            )
            return True
        except Exception as exc:
            logger.error(
                "telegram.enqueue_action_failed",
                checkpoint_id=str(checkpoint_id),
                err=str(exc),
            )
            return False

    async def pop_operator_action(
        self,
        checkpoint_id: uuid.UUID,
        timeout_seconds: int = 5,
    ) -> OperatorAction | None:
        """Pop next operator action for checkpoint (blocking)."""
        try:
            key = f"telegram:action:{checkpoint_id}"
            result = await self.redis.blpop(key, timeout=timeout_seconds)
            if result is None:
                return None
            _, payload_str = result
            data = json.loads(payload_str)
            return OperatorAction(
                kind=data["kind"],
                checkpoint_id=uuid.UUID(data["checkpoint_id"]) if data.get("checkpoint_id") else None,
                job_id=uuid.UUID(data["job_id"]) if data.get("job_id") else None,
                value=data.get("value", ""),
                callback_data=data.get("callback_data"),
                timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else None,
            )
        except Exception as exc:
            logger.error(
                "telegram.pop_action_failed",
                checkpoint_id=str(checkpoint_id),
                err=str(exc),
            )
            return None

    async def close(self) -> None:
        """Close bot session."""
        await self.bot.session.close()
