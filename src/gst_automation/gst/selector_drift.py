from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.gst.selector_health import SelectorHealthEvent
from gst_automation.watchdog.anomaly import AnomalyRecord, AnomalyService


@dataclass(frozen=True, slots=True)
class SelectorDriftSnapshot:
    key: str
    fail_rate: float
    fallback_rate: float
    p95_latency_ms: int
    samples: int


@dataclass(frozen=True, slots=True)
class SelectorDriftDetector:
    async def snapshot(
        self,
        session: AsyncSession,
        *,
        lookback_minutes: int = 60,
        min_samples: int = 20,
        top_n: int = 50,
    ) -> list[SelectorDriftSnapshot]:
        now = datetime.now(UTC)
        cutoff = now - timedelta(minutes=lookback_minutes)

        res = await session.execute(
            select(
                SelectorHealthEvent.selector_key,
                func.count(SelectorHealthEvent.id),
                func.sum(func.case((SelectorHealthEvent.result == "fail", 1), else_=0)),
                func.sum(func.case((SelectorHealthEvent.result == "fallback", 1), else_=0)),
                func.percentile_cont(0.95).within_group(SelectorHealthEvent.latency_ms),
            )
            .where(SelectorHealthEvent.created_at >= cutoff)
            .group_by(SelectorHealthEvent.selector_key)
            .order_by(func.count(SelectorHealthEvent.id).desc())
            .limit(top_n)
        )
        out: list[SelectorDriftSnapshot] = []
        for key, total, fails, fallbacks, p95 in res.all():
            total_i = int(total or 0)
            if total_i < min_samples:
                continue
            fail_i = int(fails or 0)
            fb_i = int(fallbacks or 0)
            out.append(
                SelectorDriftSnapshot(
                    key=str(key),
                    fail_rate=(fail_i / total_i) if total_i else 0.0,
                    fallback_rate=(fb_i / total_i) if total_i else 0.0,
                    p95_latency_ms=int(p95 or 0),
                    samples=total_i,
                )
            )
        return out

    async def record_anomalies(self, session: AsyncSession) -> int:
        snaps = await self.snapshot(session)
        raised = 0
        anomaly = AnomalyService(session)
        for s in snaps:
            if s.fail_rate >= 0.2 or s.fallback_rate >= 0.5 or s.p95_latency_ms >= 10_000:
                await anomaly.record(
                    AnomalyRecord(
                        anomaly_type="selector_drift",
                        severity="HIGH" if s.fail_rate >= 0.2 else "WARNING",
                        score=80 if s.fail_rate >= 0.2 else 50,
                        message="selector drift detected",
                        details={
                            "key": s.key,
                            "fail_rate": s.fail_rate,
                            "fallback_rate": s.fallback_rate,
                            "p95_latency_ms": s.p95_latency_ms,
                            "samples": s.samples,
                        },
                    )
                )
                raised += 1
        return raised

