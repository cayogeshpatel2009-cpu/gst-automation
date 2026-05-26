"""Telegram bot service layer - database operations and business logic."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.db.models.telegram import TelegramUser, TelegramMessage, TelegramAudit
from gst_automation.db.models.gst.operator_checkpoint import OperatorCheckpoint

logger = get_logger(__name__)


@dataclass(frozen=True)
class TelegramUserInfo:
    """Info about a Telegram user."""

    id: uuid.UUID
    telegram_user_id: int
    telegram_chat_id: int
    telegram_username: str | None
    status: str
    role: str
    created_at: datetime
    last_seen_at: datetime | None


class TelegramUserService:
    """Manages Telegram user allowlist and credentials."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def register_user(
        self,
        *,
        telegram_user_id: int,
        telegram_chat_id: int,
        telegram_username: str | None = None,
        telegram_first_name: str | None = None,
        telegram_last_name: str | None = None,
        role: str = "operator",
    ) -> TelegramUserInfo:
        """Register or update a Telegram user (admin action)."""
        stmt = select(TelegramUser).where(TelegramUser.telegram_user_id == telegram_user_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()

        if user:
            user.telegram_chat_id = telegram_chat_id
            user.telegram_username = telegram_username
            user.telegram_first_name = telegram_first_name
            user.telegram_last_name = telegram_last_name
            user.status = "active"
            logger.info(
                "telegram.user_updated",
                user_id=str(user.id),
                telegram_user_id=telegram_user_id,
            )
        else:
            user = TelegramUser(
                telegram_user_id=telegram_user_id,
                telegram_chat_id=telegram_chat_id,
                telegram_username=telegram_username,
                telegram_first_name=telegram_first_name,
                telegram_last_name=telegram_last_name,
                role=role,
                status="active",
            )
            self.session.add(user)
            logger.info(
                "telegram.user_registered",
                telegram_user_id=telegram_user_id,
            )

        await self.session.flush()
        return TelegramUserInfo(
            id=user.id,
            telegram_user_id=user.telegram_user_id,
            telegram_chat_id=user.telegram_chat_id,
            telegram_username=user.telegram_username,
            status=user.status,
            role=user.role,
            created_at=user.created_at,
            last_seen_at=user.last_seen_at,
        )

    async def get_user(self, *, telegram_user_id: int) -> TelegramUserInfo | None:
        """Get user info by Telegram user ID."""
        stmt = select(TelegramUser).where(TelegramUser.telegram_user_id == telegram_user_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user is None:
            return None
        return TelegramUserInfo(
            id=user.id,
            telegram_user_id=user.telegram_user_id,
            telegram_chat_id=user.telegram_chat_id,
            telegram_username=user.telegram_username,
            status=user.status,
            role=user.role,
            created_at=user.created_at,
            last_seen_at=user.last_seen_at,
        )

    async def is_allowed(self, *, telegram_user_id: int) -> bool:
        """Check if Telegram user is allowed (active)."""
        user = await self.get_user(telegram_user_id=telegram_user_id)
        return user is not None and user.status == "active"

    async def list_operators(self) -> list[TelegramUserInfo]:
        """List all active operator users."""
        stmt = select(TelegramUser).where(TelegramUser.status == "active").where(TelegramUser.role == "operator")
        users = (await self.session.execute(stmt)).scalars().all()
        return [
            TelegramUserInfo(
                id=u.id,
                telegram_user_id=u.telegram_user_id,
                telegram_chat_id=u.telegram_chat_id,
                telegram_username=u.telegram_username,
                status=u.status,
                role=u.role,
                created_at=u.created_at,
                last_seen_at=u.last_seen_at,
            )
            for u in users
        ]

    async def disable_user(self, *, telegram_user_id: int) -> bool:
        """Disable a Telegram user."""
        stmt = select(TelegramUser).where(TelegramUser.telegram_user_id == telegram_user_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user is None:
            return False
        user.status = "disabled"
        user.disabled_at = datetime.now(UTC)
        await self.session.flush()
        logger.info("telegram.user_disabled", telegram_user_id=telegram_user_id)
        return True

    async def update_last_seen(self, *, telegram_user_id: int) -> None:
        """Update last_seen_at timestamp."""
        stmt = select(TelegramUser).where(TelegramUser.telegram_user_id == telegram_user_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user:
            user.last_seen_at = datetime.now(UTC)
            await self.session.flush()


class TelegramMessageService:
    """Manages Telegram message history (send/receive)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log_message(
        self,
        *,
        telegram_message_id: int | None,
        telegram_user_id: int,
        direction: str,
        message_type: str,
        content: str,
        callback_data: str | None = None,
        checkpoint_id: uuid.UUID | None = None,
        job_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """Log a Telegram message (send or receive)."""
        msg = TelegramMessage(
            telegram_message_id=telegram_message_id,
            telegram_user_id=telegram_user_id,
            checkpoint_id=checkpoint_id,
            job_id=job_id,
            direction=direction,
            message_type=message_type,
            content=content,
            callback_data=callback_data,
        )
        self.session.add(msg)
        await self.session.flush()
        logger.debug(
            "telegram.message_logged",
            message_id=str(msg.id),
            direction=direction,
            checkpoint_id=str(checkpoint_id) if checkpoint_id else None,
        )
        return msg.id

    async def get_messages_for_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
    ) -> list[TelegramMessage]:
        """Get all messages associated with a checkpoint."""
        stmt = select(TelegramMessage).where(TelegramMessage.checkpoint_id == checkpoint_id).order_by(TelegramMessage.created_at)
        result = await self.session.execute(stmt)
        return result.scalars().all()


class TelegramAuditService:
    """Audit logging for Telegram bot actions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log_action(
        self,
        *,
        telegram_user_id: int,
        action: str,
        details: dict | None = None,
    ) -> uuid.UUID:
        """Log a Telegram bot action."""
        audit = TelegramAudit(
            telegram_user_id=telegram_user_id,
            action=action,
            details_json=json.dumps(details or {}),
        )
        self.session.add(audit)
        await self.session.flush()
        return audit.id

    async def get_user_actions(
        self,
        telegram_user_id: int,
        action_type: str | None = None,
        limit: int = 100,
    ) -> list[TelegramAudit]:
        """Get audit log for a user."""
        stmt = select(TelegramAudit).where(TelegramAudit.telegram_user_id == telegram_user_id)
        if action_type:
            stmt = stmt.where(TelegramAudit.action == action_type)
        stmt = stmt.order_by(TelegramAudit.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()
