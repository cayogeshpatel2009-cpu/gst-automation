"""Telegram reminder and scheduler service for operator-triggered orchestration."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.telegram_bot.client import TelegramClient, OperatorAction
from gst_automation.telegram_bot.service import TelegramUserService, TelegramAuditService
from gst_automation.db.models.gst.operator_checkpoint import OperatorCheckpoint
from gst_automation.db.models.orchestration.job import Job
from gst_automation.orchestration.dto import JobCreate
from gst_automation.orchestration.services.orchestrator_service import OrchestratorService

logger = get_logger(__name__)


@dataclass(frozen=True)
class ReminderPayload:
    """Payload for morning reminder."""

    message: str = "GSTR-2B download window ready"
    title: str = "GSTR-2B Download Reminder"


class TelegramReminderService:
    """Handles scheduled reminders and operator responses."""

    def __init__(self, settings: Settings, session: AsyncSession, redis_client: redis.Redis) -> None:
        self.settings = settings
        self.session = session
        self.redis = redis_client
        self.telegram = TelegramClient(settings, redis_client)
        self.user_service = TelegramUserService(session)
        self.audit_service = TelegramAuditService(session)

    async def send_morning_reminder(self) -> None:
        """Send morning reminder to all active operators."""
        operators = await self.user_service.list_operators()
        if not operators:
            logger.warning("telegram.reminder_no_operators")
            return

        reminder_text = "🚀 *GSTR-2B Download Window Ready*\n\nReady to begin automated downloads?\nClick below to start."

        buttons = [
            ("✅ YES, START", "btn:start_download"),
            ("⏸️ POSTPONE 30 MIN", "btn:postpone_30min"),
            ("❌ CANCEL TODAY", "btn:cancel_today"),
        ]

        for operator in operators:
            msg_id = await self.telegram.send_message(
                telegram_user_id=operator.telegram_chat_id,
                text=reminder_text,
                buttons=buttons,
            )
            if msg_id:
                await self.audit_service.log_action(
                    telegram_user_id=operator.telegram_user_id,
                    action="reminder_sent",
                    details={"message_id": msg_id},
                )
                logger.info(
                    "telegram.reminder_sent",
                    operator_id=str(operator.id),
                    telegram_user_id=operator.telegram_user_id,
                )
            else:
                logger.error(
                    "telegram.reminder_send_failed",
                    operator_id=str(operator.id),
                    telegram_user_id=operator.telegram_user_id,
                )

    async def handle_reminder_response(
        self,
        telegram_user_id: int,
        callback_data: str,
    ) -> None:
        """Handle operator's response to reminder."""
        user = await self.user_service.get_user(telegram_user_id=telegram_user_id)
        if not user:
            logger.error(
                "telegram.reminder_response_unknown_user",
                telegram_user_id=telegram_user_id,
            )
            return

        await self.user_service.update_last_seen(telegram_user_id=telegram_user_id)

        if callback_data == "btn:start_download":
            await self._on_start_download(user.telegram_chat_id, telegram_user_id)
        elif callback_data == "btn:postpone_30min":
            await self._on_postpone(user.telegram_chat_id, telegram_user_id)
        elif callback_data == "btn:cancel_today":
            await self._on_cancel(user.telegram_chat_id, telegram_user_id)

    async def _on_start_download(self, telegram_chat_id: int, telegram_user_id: int) -> None:
        """Handle YES START button click."""
        msg = await self.telegram.send_message(
            telegram_user_id=telegram_chat_id,
            text="⏳ Starting download orchestration...\n\nAllocating browser workers and initializing GST sessions.",
        )

        await self.audit_service.log_action(
            telegram_user_id=telegram_user_id,
            action="start_download_clicked",
            details={"timestamp": datetime.now(UTC).isoformat()},
        )

        # Create a background job that will enqueue download orchestration
        # For now, we just log it. The actual job creation happens in the background task.
        logger.info(
            "telegram.start_download_requested",
            telegram_user_id=telegram_user_id,
        )

    async def _on_postpone(self, telegram_chat_id: int, telegram_user_id: int) -> None:
        """Handle POSTPONE button click."""
        msg = await self.telegram.send_message(
            telegram_user_id=telegram_chat_id,
            text="⏸️ Reminder postponed for 30 minutes.",
        )

        await self.audit_service.log_action(
            telegram_user_id=telegram_user_id,
            action="reminder_postponed",
            details={"postpone_minutes": 30},
        )

        logger.info(
            "telegram.reminder_postponed",
            telegram_user_id=telegram_user_id,
        )

    async def _on_cancel(self, telegram_chat_id: int, telegram_user_id: int) -> None:
        """Handle CANCEL TODAY button click."""
        msg = await self.telegram.send_message(
            telegram_user_id=telegram_chat_id,
            text="❌ Download reminder cancelled for today.",
        )

        await self.audit_service.log_action(
            telegram_user_id=telegram_user_id,
            action="reminder_cancelled",
        )

        logger.info(
            "telegram.reminder_cancelled",
            telegram_user_id=telegram_user_id,
        )


class TelegramCaptchaService:
    """Handles CAPTCHA detection and operator interaction."""

    def __init__(self, settings: Settings, session: AsyncSession, redis_client: redis.Redis) -> None:
        self.settings = settings
        self.session = session
        self.redis = redis_client
        self.telegram = TelegramClient(settings, redis_client)
        self.user_service = TelegramUserService(session)
        self.audit_service = TelegramAuditService(session)

    async def send_captcha_request(
        self,
        checkpoint_id: uuid.UUID,
        job_id: uuid.UUID,
        client_display_name: str,
        gstin: str,
        captcha_image_path: str,
    ) -> bool:
        """Send CAPTCHA image to operators and wait for response."""
        operators = await self.user_service.list_operators()
        if not operators:
            logger.error(
                "telegram.captcha_no_operators",
                checkpoint_id=str(checkpoint_id),
                job_id=str(job_id),
            )
            return False

        caption = f"""🔐 *CAPTCHA Required*

*Client:* {client_display_name}
*GSTIN:* `{gstin}`
*Job:* `{str(job_id)[:12]}...`

Please enter the CAPTCHA text:"""

        buttons = [
            ("🔄 REFRESH", f"btn:refresh_captcha:{checkpoint_id}"),
            ("❌ CANCEL", f"btn:cancel_job:{checkpoint_id}"),
        ]

        # Send to all operators
        for operator in operators:
            msg_id = await self.telegram.send_photo(
                telegram_user_id=operator.telegram_chat_id,
                photo_path=captcha_image_path,
                caption=caption,
                buttons=buttons,
                checkpoint_id=checkpoint_id,
            )
            if msg_id:
                logger.info(
                    "telegram.captcha_sent",
                    operator_id=str(operator.id),
                    checkpoint_id=str(checkpoint_id),
                    message_id=msg_id,
                )
            else:
                logger.error(
                    "telegram.captcha_send_failed",
                    operator_id=str(operator.id),
                    checkpoint_id=str(checkpoint_id),
                )

        return True

    async def wait_for_captcha_response(
        self,
        checkpoint_id: uuid.UUID,
        timeout_seconds: int | None = None,
    ) -> str | None:
        """Wait for operator CAPTCHA response (blocking)."""
        timeout = timeout_seconds or self.settings.telegram_captcha_timeout_seconds
        action = await self.telegram.pop_operator_action(checkpoint_id=checkpoint_id, timeout_seconds=min(timeout, 60))
        if action and action.value:
            return action.value
        return None

    async def handle_captcha_response(
        self,
        telegram_user_id: int,
        checkpoint_id: uuid.UUID,
        captcha_text: str,
    ) -> None:
        """Handle operator's CAPTCHA response."""
        user = await self.user_service.get_user(telegram_user_id=telegram_user_id)
        if not user:
            logger.error(
                "telegram.captcha_response_unknown_user",
                telegram_user_id=telegram_user_id,
            )
            return

        await self.user_service.update_last_seen(telegram_user_id=telegram_user_id)

        # Enqueue action for checkpoint
        action = OperatorAction(
            kind="captcha_reply",
            checkpoint_id=checkpoint_id,
            value=captcha_text,
            timestamp=datetime.now(UTC),
        )
        await self.telegram.enqueue_operator_action(checkpoint_id=checkpoint_id, action=action)

        await self.audit_service.log_action(
            telegram_user_id=telegram_user_id,
            action="captcha_response_submitted",
            details={
                "checkpoint_id": str(checkpoint_id),
                "text_length": len(captcha_text),
            },
        )

        logger.info(
            "telegram.captcha_response_received",
            telegram_user_id=telegram_user_id,
            checkpoint_id=str(checkpoint_id),
        )
