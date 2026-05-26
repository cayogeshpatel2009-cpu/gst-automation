from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from gst_automation.db.base import Base


class BrowserInstance(Base):
    """Durable record of a Playwright browser instance managed by a worker process."""

    __tablename__ = "browser_instances"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    worker_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    worker_generation: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, index=True)

    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # online/retiring/offline
    browser_type: Mapped[str] = mapped_column(String(32), nullable=False, default="chromium")
    headless: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)

    launch_config_json: Mapped[str] = mapped_column(Text(), nullable=False, default="{}")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
