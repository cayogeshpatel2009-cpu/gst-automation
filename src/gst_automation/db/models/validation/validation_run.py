from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from gst_automation.db.base import Base


class ValidationRun(Base):
    """Operator-triggered validation run (smoke/chaos/soak/stress) that groups jobs."""

    __tablename__ = "validation_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # smoke/chaos/soak/stress
    scenario: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running", index=True)

    config_json: Mapped[str] = mapped_column(Text(), nullable=False, default="{}")
    summary_json: Mapped[str] = mapped_column(Text(), nullable=False, default="{}")

    jobs_total: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    jobs_completed: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class ValidationRunJob(Base):
    __tablename__ = "validation_run_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )

