from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.stability.readiness import ReadinessGateResult
from gst_automation.db.models.stability.scoring import StabilityScore
from gst_automation.db.models.validation.cleanup_audit import CleanupAudit
from gst_automation.db.models.validation.health_and_leaks import ReplayIntegrityAudit
from gst_automation.db.models.orchestration.job_lease import JobLease
from gst_automation.db.models.browser.browser_context import BrowserContextRecord
from sqlalchemy import func


@dataclass(frozen=True, slots=True)
class ReadinessPolicy:
    gate_name: str = "pre_gst_readiness"
    min_score_last_12h: int = 80
    min_replay_integrity_percent: int = 99
    min_cleanup_success_percent: int = 99
    require_no_stale_leases: bool = True
    require_no_active_contexts: bool = True
    require_gst_probe_allowlist: bool = True


@dataclass(frozen=True, slots=True)
class ReadinessGateService:
    policy: ReadinessPolicy = ReadinessPolicy()

    async def evaluate(self, session: AsyncSession) -> ReadinessGateResult:
        # This gate is platform-wide; GST allowlist must be configured before any GST probe.
        try:
            from gst_automation.core.settings import Settings

            settings = Settings.load()
            gst_allowlist_ok = bool(getattr(settings, "gst_probe_allowlist", ""))
        except Exception:
            gst_allowlist_ok = False
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=12)
        res = await session.execute(
            select(StabilityScore)
            .where(StabilityScore.created_at >= cutoff)
            .order_by(StabilityScore.created_at.desc())
            .limit(200)
        )
        rows = list(res.scalars().all())
        if not rows:
            report = {"reason": "no stability scores in last 12h"}
            row = ReadinessGateResult(
                gate_name=self.policy.gate_name,
                status="fail",
                score=0,
                report_json=json.dumps(report, sort_keys=True, separators=(",", ":")),
            )
            session.add(row)
            await session.flush()
            return row

        min_score = min(int(r.score) for r in rows)

        # Empirical thresholds (bounded, DB-driven).
        replay_total = int(
            (await session.scalar(select(func.count(ReplayIntegrityAudit.id)).where(ReplayIntegrityAudit.created_at >= cutoff)))
            or 0
        )
        replay_bad = int(
            (
                await session.scalar(
                    select(func.count(ReplayIntegrityAudit.id))
                    .where(ReplayIntegrityAudit.created_at >= cutoff)
                    .where(ReplayIntegrityAudit.status != "ok")
                )
            )
            or 0
        )
        replay_ok_pct = 100 if replay_total == 0 else int(100 * (replay_total - replay_bad) / replay_total)

        cleanup_total = int(
            (await session.scalar(select(func.count(CleanupAudit.id)).where(CleanupAudit.created_at >= cutoff))) or 0
        )
        cleanup_bad = int(
            (
                await session.scalar(
                    select(func.count(CleanupAudit.id))
                    .where(CleanupAudit.created_at >= cutoff)
                    .where(CleanupAudit.status != "ok")
                )
            )
            or 0
        )
        cleanup_ok_pct = 100 if cleanup_total == 0 else int(100 * (cleanup_total - cleanup_bad) / cleanup_total)

        stale_leases = int((await session.scalar(select(func.count(JobLease.id)).where(JobLease.expires_at < now))) or 0)
        active_contexts = int(
            (await session.scalar(select(func.count(BrowserContextRecord.id)).where(BrowserContextRecord.state == "active"))) or 0
        )

        status = "pass"
        if min_score < self.policy.min_score_last_12h:
            status = "fail"
        if replay_ok_pct < self.policy.min_replay_integrity_percent:
            status = "fail"
        if cleanup_ok_pct < self.policy.min_cleanup_success_percent:
            status = "fail"
        if self.policy.require_no_stale_leases and stale_leases > 0:
            status = "fail"
        if self.policy.require_no_active_contexts and active_contexts > 0:
            status = "fail"
        if self.policy.require_gst_probe_allowlist and not gst_allowlist_ok:
            status = "fail"
        report = {
            "window_hours": 12,
            "min_score": min_score,
            "threshold": self.policy.min_score_last_12h,
            "samples": len(rows),
            "replay_ok_percent": replay_ok_pct,
            "replay_total": replay_total,
            "cleanup_ok_percent": cleanup_ok_pct,
            "cleanup_total": cleanup_total,
            "stale_leases": stale_leases,
            "active_contexts": active_contexts,
            "gst_probe_allowlist_configured": gst_allowlist_ok,
        }
        row = ReadinessGateResult(
            gate_name=self.policy.gate_name,
            status=status,
            score=min_score,
            report_json=json.dumps(report, sort_keys=True, separators=(",", ":")),
        )
        session.add(row)
        await session.flush()
        return row
