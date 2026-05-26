from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.browser.browser_crash import BrowserCrash
from gst_automation.db.models.orchestration.anomaly import WatchdogAnomaly
from gst_automation.db.models.orchestration.job_lease import JobLease
from gst_automation.db.models.validation.cleanup_audit import CleanupAudit
from gst_automation.db.models.validation.health_and_leaks import ReplayIntegrityAudit
from gst_automation.db.models.validation.retention import RetentionAction
from gst_automation.db.models.stability.scoring import StabilityScore


@dataclass(frozen=True, slots=True)
class StabilityWeights:
    browser_crash: int = 25
    replay_violation: int = 20
    cleanup_violation: int = 20
    lease_recovery_signal: int = 10
    watchdog_high: int = 10
    retention_error: int = 10


@dataclass(frozen=True, slots=True)
class StabilityScoreService:
    weights: StabilityWeights = StabilityWeights()

    async def compute(
        self,
        session: AsyncSession,
        *,
        scope: str = "global",
        scope_id: uuid.UUID | None = None,
        window_minutes: int = 60,
    ) -> StabilityScore:
        now = datetime.now(UTC)
        cutoff = now - timedelta(minutes=window_minutes)

        crashes = await session.scalar(
            select(func.count(BrowserCrash.id)).where(BrowserCrash.created_at >= cutoff)
        )
        replay_bad = await session.scalar(
            select(func.count(ReplayIntegrityAudit.id))
            .where(ReplayIntegrityAudit.created_at >= cutoff)
            .where(ReplayIntegrityAudit.status != "ok")
        )
        cleanup_bad = await session.scalar(
            select(func.count(CleanupAudit.id))
            .where(CleanupAudit.created_at >= cutoff)
            .where(CleanupAudit.status != "ok")
        )
        retention_err = await session.scalar(
            select(func.count(RetentionAction.id))
            .where(RetentionAction.created_at >= cutoff)
            .where(RetentionAction.action == "error")
        )
        watchdog_high = await session.scalar(
            select(func.count(WatchdogAnomaly.id))
            .where(WatchdogAnomaly.created_at >= cutoff)
            .where(WatchdogAnomaly.severity.in_(["HIGH", "CRITICAL"]))
        )
        stale_leases = await session.scalar(
            select(func.count(JobLease.id)).where(JobLease.expires_at < now)
        )

        crashes_i = int(crashes or 0)
        replay_i = int(replay_bad or 0)
        cleanup_i = int(cleanup_bad or 0)
        retention_i = int(retention_err or 0)
        watchdog_i = int(watchdog_high or 0)
        stale_i = int(stale_leases or 0)

        penalties = {
            "browser_crash": min(100, crashes_i * self.weights.browser_crash),
            "replay_violation": min(100, replay_i * self.weights.replay_violation),
            "cleanup_violation": min(100, cleanup_i * self.weights.cleanup_violation),
            "retention_error": min(100, retention_i * self.weights.retention_error),
            "watchdog_high": min(100, watchdog_i * self.weights.watchdog_high),
            "stale_leases": min(100, stale_i * self.weights.lease_recovery_signal),
        }
        total_penalty = min(100, sum(int(v) for v in penalties.values()))
        score = max(0, 100 - total_penalty)

        details = {
            "window_minutes": window_minutes,
            "counts": {
                "browser_crashes": crashes_i,
                "replay_violations": replay_i,
                "cleanup_violations": cleanup_i,
                "retention_errors": retention_i,
                "watchdog_high": watchdog_i,
                "stale_leases": stale_i,
            },
            "penalties": penalties,
            "score": score,
        }

        row = StabilityScore(
            scope=scope,
            scope_id=scope_id,
            score=score,
            details_json=json.dumps(details, sort_keys=True, separators=(",", ":")),
        )
        session.add(row)
        await session.flush()
        return row

