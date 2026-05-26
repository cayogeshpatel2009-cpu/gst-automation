from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.watchdog.anomaly import AnomalyRecord, AnomalyService
from gst_automation.portal.telemetry import PORTAL_LATENCY_SECONDS


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PortalHealthSample:
    latency_seconds: float
    ok: bool
    reason: str


@dataclass(frozen=True, slots=True)
class PortalHealthMonitor:
    """Health monitor scaffold; records anomalies and metrics. Portal checks are plugged later."""

    async def record_sample(
        self, session: AsyncSession, *, sample: PortalHealthSample, metadata: dict[str, Any] | None = None
    ) -> None:
        PORTAL_LATENCY_SECONDS.observe(max(0.0, sample.latency_seconds))
        if not sample.ok:
            await AnomalyService(session).record(
                AnomalyRecord(
                    anomaly_type="portal_degraded",
                    severity="HIGH",
                    score=80,
                    message="portal health sample failed",
                    details={"reason": sample.reason, **(metadata or {})},
                )
            )

