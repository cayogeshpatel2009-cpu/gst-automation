from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from gst_automation.db.base import Base


class CleanupAudit(Base):
    """Invariant audit record for cleanup correctness (post-job or scheduled)."""

    __tablename__ = "cleanup_audits"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    audit_scope: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # job/context/global
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # ok/violation/error
    findings_json: Mapped[str] = mapped_column(Text(), nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )

