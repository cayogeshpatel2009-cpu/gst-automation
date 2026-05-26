from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from gst_automation.db.base import Base


class JobLease(Base):
    """Lease record used for crash-safe execution and recovery."""

    __tablename__ = "job_leases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, unique=True, index=True)
    worker_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    worker_generation: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)

    lease_token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    fencing_token: Mapped[int] = mapped_column(BigInteger(), nullable=False, default=0, index=True)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
