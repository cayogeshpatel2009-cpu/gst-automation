from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.gst.execution import GstExecutionReport
from gst_automation.db.models.validation.cleanup_audit import CleanupAudit
from gst_automation.gst.reliability import SelectorReliabilityService, SessionReliabilityService


@dataclass(frozen=True, slots=True)
class ProductionGateConfig:
    min_session_reuse_success_rate: float = 0.85
    min_selector_score_avg: float = 85.0
    min_execution_ok_rate: float = 0.90
    min_cleanup_ok_rate: float = 0.95


@dataclass(frozen=True, slots=True)
class ProductionGateResult:
    ok: bool
    score: int
    details: dict[str, object]


@dataclass(frozen=True, slots=True)
class ProductionReadinessGate:
    config: ProductionGateConfig = ProductionGateConfig()

    async def evaluate(self, session: AsyncSession, *, lookback_hours: int = 24) -> ProductionGateResult:
        cutoff = datetime.now(UTC) - timedelta(hours=lookback_hours)

        sess = await SessionReliabilityService().snapshot(session, lookback_minutes=lookback_hours * 60)
        selector_rows = await SelectorReliabilityService().snapshot(session, lookback_minutes=lookback_hours * 60)
        selector_avg = (sum(r.score for r in selector_rows) / len(selector_rows)) if selector_rows else 0.0

        res = await session.execute(
            select(
                func.count(GstExecutionReport.id),
                func.sum(func.case((GstExecutionReport.status == "ok", 1), else_=0)),
            ).where(GstExecutionReport.created_at >= cutoff)
        )
        total_exec, ok_exec = res.one()
        total_exec_i = int(total_exec or 0)
        ok_exec_i = int(ok_exec or 0)
        exec_ok_rate = (ok_exec_i / total_exec_i) if total_exec_i else 0.0

        res2 = await session.execute(
            select(
                func.count(CleanupAudit.id),
                func.sum(func.case((CleanupAudit.status == "ok", 1), else_=0)),
            ).where(CleanupAudit.created_at >= cutoff)
        )
        total_c, ok_c = res2.one()
        total_c_i = int(total_c or 0)
        ok_c_i = int(ok_c or 0)
        cleanup_ok_rate = (ok_c_i / total_c_i) if total_c_i else 1.0

        score = 100
        blockers: list[str] = []

        if float(sess.get("session_reuse_success_rate") or 0.0) < self.config.min_session_reuse_success_rate:
            score -= 25
            blockers.append("session_reuse_below_threshold")
        if selector_avg < self.config.min_selector_score_avg:
            score -= 25
            blockers.append("selector_reliability_below_threshold")
        if total_exec_i > 0 and exec_ok_rate < self.config.min_execution_ok_rate:
            score -= 30
            blockers.append("execution_ok_rate_below_threshold")
        if total_c_i > 0 and cleanup_ok_rate < self.config.min_cleanup_ok_rate:
            score -= 10
            blockers.append("cleanup_ok_rate_below_threshold")

        score = max(0, min(100, score))
        ok = not blockers
        return ProductionGateResult(
            ok=ok,
            score=score,
            details={
                "lookback_hours": lookback_hours,
                "blockers": blockers,
                "session": sess,
                "selector_avg_score": selector_avg,
                "execution_total": total_exec_i,
                "execution_ok_rate": exec_ok_rate,
                "cleanup_total": total_c_i,
                "cleanup_ok_rate": cleanup_ok_rate,
            },
        )

