from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from gst_automation.db.base import Base


class QueueMetric(Base):
    """Queue health snapshot for dashboards/alerting."""

    __tablename__ = "queue_metrics"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    queue: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    depth: Mapped[int] = mapped_column(Integer(), nullable=False)
    oldest_age_seconds: Mapped[int] = mapped_column(Integer(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )

