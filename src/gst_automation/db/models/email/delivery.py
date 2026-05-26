from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from gst_automation.db.base import Base


class EmailDelivery(Base):
    __tablename__ = "email_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    to_email: Mapped[str] = mapped_column(String(256), nullable=False)
    cc_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    subject: Mapped[str] = mapped_column(Text(), nullable=False)
    attachment_path: Mapped[str] = mapped_column(Text(), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)  # queued/sent/failed
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
