from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from gst_automation.db.base import Base


class ClientConfig(Base):
    __tablename__ = "client_configs"

    client_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    client_email: Mapped[str] = mapped_column(String(256), nullable=False)
    cc_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    active: Mapped[int] = mapped_column(Integer(), nullable=False, default=1, index=True)
    priority: Mapped[int] = mapped_column(Integer(), nullable=False, default=3, index=True)
    folder_root: Mapped[str] = mapped_column(Text(), nullable=False)
    retry_policy_json: Mapped[str] = mapped_column(Text(), nullable=False, default="{}")
    session_reuse_enabled: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    financial_year: Mapped[str] = mapped_column(String(16), nullable=False, default="2025-26", index=True)
    preferred_run_window: Mapped[int] = mapped_column(Integer(), nullable=False, default=18, index=True)
    tags: Mapped[str | None] = mapped_column(Text(), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )


class ClientCredentialRef(Base):
    """Reference to a credential stored in the Vault (no raw secrets in DB)."""

    __tablename__ = "client_credential_refs"

    client_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    gst_username: Mapped[str] = mapped_column(String(128), nullable=False)
    gst_password_secret_key: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
