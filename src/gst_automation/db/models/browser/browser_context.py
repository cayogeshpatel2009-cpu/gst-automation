from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from gst_automation.db.base import Base


class BrowserContextRecord(Base):
    """Durable record of an allocated browser context (per-job isolation)."""

    __tablename__ = "browser_contexts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    browser_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)

    job_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    lease_token: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    fencing_token: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, index=True)
    worker_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    worker_generation: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, index=True)

    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # active/closed/orphaned
    workspace_dir: Mapped[str] = mapped_column(Text(), nullable=False)
    downloads_dir: Mapped[str] = mapped_column(Text(), nullable=False)
    artifacts_dir: Mapped[str] = mapped_column(Text(), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

