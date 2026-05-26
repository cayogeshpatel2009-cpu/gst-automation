from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from gst_automation.db.base import Base


class PortalSelectorDef(Base):
    """Durable selector definitions with versioning and candidate chains (JSON)."""

    __tablename__ = "portal_selector_defs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer(), nullable=False, index=True)
    candidates_json: Mapped[str] = mapped_column(Text(), nullable=False)
    active: Mapped[int] = mapped_column(Integer(), nullable=False, default=1, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )

