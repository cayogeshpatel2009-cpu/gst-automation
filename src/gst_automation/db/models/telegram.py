from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import BigInteger, DateTime, String, Text, Uuid, Integer
from sqlalchemy.orm import Mapped, mapped_column

from gst_automation.db.base import Base


TelegramUserStatus = Literal["active", "disabled", "pending"]
TelegramMessageDirection = Literal["send", "receive"]


class TelegramUser(Base):
    """Telegram user allowlist and credentials."""

    __tablename__ = "telegram_users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger(), nullable=False, unique=True, index=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger(), nullable=False, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(200), nullable=True)
    telegram_first_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    telegram_last_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")  # active/disabled/pending
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="operator")  # operator/admin

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TelegramMessage(Base):
    """Telegram message log (send/receive) for audit and mapping."""

    __tablename__ = "telegram_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer(), nullable=True, index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger(), nullable=False, index=True)

    checkpoint_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)

    direction: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # send/receive
    message_type: Mapped[str] = mapped_column(String(32), nullable=False)  # text/photo/button_callback/etc
    content: Mapped[str] = mapped_column(Text(), nullable=False)

    # For received messages, capture button callback data or text reply
    callback_data: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )


class TelegramAudit(Base):
    """Audit log for all Telegram bot actions."""

    __tablename__ = "telegram_audit"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger(), nullable=False, index=True)

    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    details_json: Mapped[str] = mapped_column(Text(), nullable=False, default="{}")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
