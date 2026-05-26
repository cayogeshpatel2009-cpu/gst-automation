from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from gst_automation.db.base import Base


class OrchestrationEvent(Base):
    """Durable internal event record (replay-safe)."""

    __tablename__ = "orchestration_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    schema_version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    client_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text(), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text(), nullable=False, default="{}")
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
