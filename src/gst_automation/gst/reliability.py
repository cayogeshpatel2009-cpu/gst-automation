from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.gst.selector_health import SelectorHealthEvent
from gst_automation.db.models.gst.session_health import GstSessionHealth


@dataclass(frozen=True, slots=True)
class SelectorReliabilityRow:
    selector_key: str
    samples: int
    ok: int
    fallback: int
    fail: int
    fallback_rate: float
    fail_rate: float
    p95_latency_ms: int
    score: int


@dataclass(frozen=True, slots=True)
class SelectorReliabilityService:
    async def snapshot(
        self,
        session: AsyncSession,
        *,
        lookback_minutes: int = 24 * 60,
        min_samples: int = 10,
        top_n: int = 200,
    ) -> list[SelectorReliabilityRow]:
        cutoff = datetime.now(UTC) - timedelta(minutes=lookback_minutes)
        res = await session.execute(
            select(
                SelectorHealthEvent.selector_key,
                func.count(SelectorHealthEvent.id),
                func.sum(func.case((SelectorHealthEvent.result == "ok", 1), else_=0)),
                func.sum(func.case((SelectorHealthEvent.result == "fallback", 1), else_=0)),
                func.sum(func.case((SelectorHealthEvent.result == "fail", 1), else_=0)),
                func.percentile_cont(0.95).within_group(SelectorHealthEvent.latency_ms),
            )
            .where(SelectorHealthEvent.created_at >= cutoff)
            .group_by(SelectorHealthEvent.selector_key)
            .order_by(func.count(SelectorHealthEvent.id).desc())
            .limit(top_n)
        )
        out: list[SelectorReliabilityRow] = []
        for key, total, ok, fb, fail, p95 in res.all():
            t = int(total or 0)
            if t < min_samples:
                continue
            ok_i = int(ok or 0)
            fb_i = int(fb or 0)
            fail_i = int(fail or 0)
            fb_rate = fb_i / max(1, t)
            fail_rate = fail_i / max(1, t)
            p95_i = int(p95 or 0)
            score = 100
            score -= int(min(60, fail_rate * 100 * 1.5))
            score -= int(min(20, fb_rate * 100 * 0.6))
            if p95_i >= 10_000:
                score -= 10
            score = max(0, min(100, score))
            out.append(
                SelectorReliabilityRow(
                    selector_key=str(key),
                    samples=t,
                    ok=ok_i,
                    fallback=fb_i,
                    fail=fail_i,
                    fallback_rate=fb_rate,
                    fail_rate=fail_rate,
                    p95_latency_ms=p95_i,
                    score=score,
                )
            )
        return out


@dataclass(frozen=True, slots=True)
class SessionReliabilityRow:
    state: str
    samples: int


@dataclass(frozen=True, slots=True)
class SessionReliabilityService:
    async def snapshot(
        self,
        session: AsyncSession,
        *,
        lookback_minutes: int = 24 * 60,
    ) -> dict[str, object]:
        cutoff = datetime.now(UTC) - timedelta(minutes=lookback_minutes)
        res = await session.execute(
            select(GstSessionHealth.state, func.count(GstSessionHealth.id))
            .where(GstSessionHealth.created_at >= cutoff)
            .group_by(GstSessionHealth.state)
            .order_by(func.count(GstSessionHealth.id).desc())
        )
        counts = {str(state): int(cnt or 0) for state, cnt in res.all()}
        total = sum(counts.values())
        authed = counts.get("authenticated", 0)
        session_expired = counts.get("session_expired", 0)
        login = counts.get("login", 0)
        otp = counts.get("otp", 0)
        captcha = counts.get("captcha", 0)
        unknown = counts.get("unknown", 0)
        success_rate = (authed / total) if total else 0.0
        return {
            "lookback_minutes": lookback_minutes,
            "total_samples": total,
            "counts": counts,
            "session_reuse_success_rate": success_rate,
            "session_expired": session_expired,
            "login": login,
            "otp": otp,
            "captcha": captcha,
            "unknown": unknown,
        }

