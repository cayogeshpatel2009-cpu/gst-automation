from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from gst_automation.db.base import Base


class WorkerHeartbeat(Base):
    """Time-series worker heartbeat events (append-only)."""

    __tablename__ = "worker_heartbeats"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    worker_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    cpu_percent: Mapped[int] = mapped_column(Integer(), nullable=False)
    memory_rss_bytes: Mapped[int] = mapped_column(Integer(), nullable=False)
    active_jobs: Mapped[int] = mapped_column(Integer(), nullable=False)
    health_state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

