from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from gst_automation.db.base import Base


class RetentionPolicy(Base):
    """DB-driven retention policy for browser artifacts/replays."""

    __tablename__ = "retention_policies"

    kind: Mapped[str] = mapped_column(String(64), primary_key=True)  # trace/har/screenshot/download/console/replay/*
    ttl_days: Mapped[int] = mapped_column(Integer(), nullable=False, default=14)
    enabled: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    preserve: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)  # forensic mode override

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )


class RetentionAction(Base):
    """Append-only action log for retention enforcement and audits."""

    __tablename__ = "retention_actions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    relpath: Mapped[str] = mapped_column(Text(), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)  # delete/keep/error
    reason: Mapped[str] = mapped_column(Text(), nullable=False, default="")
    details_json: Mapped[str] = mapped_column(Text(), nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )

