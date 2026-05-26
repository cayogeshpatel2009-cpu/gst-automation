from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from gst_automation.db.base import Base


class WatchdogAnomaly(Base):
    """Append-only anomaly record for incident response and dashboards."""

    __tablename__ = "watchdog_anomalies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    anomaly_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    score: Mapped[int] = mapped_column(Integer(), nullable=False)
    message: Mapped[str] = mapped_column(Text(), nullable=False)
    details_json: Mapped[str] = mapped_column(Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )


class WatchdogAnomalyState(Base):
    """Latest state for alert deduplication/cooldowns."""

    __tablename__ = "watchdog_anomaly_state"

    anomaly_type: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_count: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)

