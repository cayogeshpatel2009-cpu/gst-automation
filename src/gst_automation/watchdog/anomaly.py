from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.orchestration.anomaly import WatchdogAnomaly, WatchdogAnomalyState
from gst_automation.orchestration.events import EventContext, EventPublisher
from gst_automation.orchestration.ids import new_correlation_id, new_run_id, new_trace_id


Severity = Literal["INFO", "WARNING", "HIGH", "CRITICAL"]


@dataclass(frozen=True, slots=True)
class AnomalyPolicy:
    cooldown_seconds: int = 300
    max_alerts_per_minute: int = 30


@dataclass(frozen=True, slots=True)
class AnomalyRecord:
    anomaly_type: str
    severity: Severity
    score: int
    message: str
    details: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AnomalyService:
    """Persists anomalies with cooldown/dedupe and publishes orchestration events."""

    session: AsyncSession
    policy: AnomalyPolicy = AnomalyPolicy()

    async def record(self, record: AnomalyRecord, *, actor: str = "watchdog") -> bool:
        now = datetime.now(UTC)
        state = await self._get_state(record.anomaly_type)
        should_alert = self._should_alert(state, now)
        # Flood protection: cap anomaly event publishing under storms (DB still records).
        if should_alert:
            recent_alerts = await self._count_recent_alerts(now=now, window_seconds=60)
            if recent_alerts >= self.policy.max_alerts_per_minute:
                should_alert = False

        row = WatchdogAnomaly(
            anomaly_type=record.anomaly_type,
            severity=record.severity,
            score=record.score,
            message=record.message,
            details_json=json.dumps(record.details, sort_keys=True, separators=(",", ":")),
            created_at=now,
        )
        self.session.add(row)

        if state is None:
            st = WatchdogAnomalyState(
                anomaly_type=record.anomaly_type,
                last_seen_at=now,
                last_alerted_at=now if should_alert else None,
                consecutive_count=1,
            )
            self.session.add(st)
        else:
            state.last_seen_at = now
            state.consecutive_count = int(state.consecutive_count) + 1
            if should_alert:
                state.last_alerted_at = now

        if should_alert:
            publisher = EventPublisher(self.session)
            ctx = EventContext(
                actor=actor,
                trace_id=new_trace_id(),
                correlation_id=new_correlation_id(),
                run_id=new_run_id(),
            )
            await publisher.publish(
                event_type="anomaly.detected",
                job_id=None,
                client_id=None,
                payload={
                    "type": record.anomaly_type,
                    "severity": record.severity,
                    "score": record.score,
                    "message": record.message,
                },
                metadata={"details": record.details},
                ctx=ctx,
                schema_version=1,
            )
        await self.session.flush()
        return should_alert

    async def _count_recent_alerts(self, *, now: datetime, window_seconds: int) -> int:
        res = await self.session.execute(
            select(WatchdogAnomalyState)
        )
        # Count anomaly types alerted recently; cheap approximation avoids scanning anomaly rows.
        cutoff = now - timedelta(seconds=window_seconds)
        count = 0
        for st in res.scalars().all():
            if st.last_alerted_at and st.last_alerted_at >= cutoff:
                count += 1
        return count

    async def _get_state(self, anomaly_type: str) -> WatchdogAnomalyState | None:
        res = await self.session.execute(
            select(WatchdogAnomalyState).where(WatchdogAnomalyState.anomaly_type == anomaly_type)
        )
        return res.scalar_one_or_none()

    def _should_alert(self, state: WatchdogAnomalyState | None, now: datetime) -> bool:
        if state is None or state.last_alerted_at is None:
            return True
        return (now - state.last_alerted_at) >= timedelta(seconds=self.policy.cooldown_seconds)
