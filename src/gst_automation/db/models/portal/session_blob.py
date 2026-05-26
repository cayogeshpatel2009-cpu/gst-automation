from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from gst_automation.db.base import Base


class PortalSessionBlob(Base):
    """Encrypted session storage_state blob per client/portal profile."""

    __tablename__ = "portal_session_blobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    profile: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # e.g. "gst"
    encrypted_blob: Mapped[str] = mapped_column(Text(), nullable=False)
    key_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default", index=True)
    version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

