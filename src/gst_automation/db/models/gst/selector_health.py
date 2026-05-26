from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from gst_automation.db.base import Base


class SelectorHealthEvent(Base):
    """Per-attempt selector resolution telemetry for drift detection and scoring."""

    __tablename__ = "selector_health_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    context_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)

    selector_key: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    selector_version: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, index=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # ok/fallback/fail
    candidate_index: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    candidates_total: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    details_json: Mapped[str] = mapped_column(Text(), nullable=False, default="{}")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )

