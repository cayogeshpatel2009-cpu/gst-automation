from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from gst_automation.db.base import Base


class GstExecutionReport(Base):
    """Post-run validation report for gstr2b_download executions."""

    __tablename__ = "gst_execution_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # YYYY-MM

    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # ok/violation/error
    score: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    report_json: Mapped[str] = mapped_column(Text(), nullable=False, default="{}")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )

