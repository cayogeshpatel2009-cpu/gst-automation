from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.gst.observation import GstObservationSession
from gst_automation.db.models.gst.portal_profile import GstPortalProfile
from gst_automation.db.models.gst.session_health import GstSessionHealth
from gst_automation.db.models.validation.health_and_leaks import ReplayIntegrityAudit


@dataclass(frozen=True, slots=True)
class GstReadinessReport:
    score: int
    details: dict[str, object]


@dataclass(frozen=True, slots=True)
class GstReadinessAnalyzer:
    async def analyze(self, session: AsyncSession, *, lookback_hours: int = 24) -> GstReadinessReport:
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=lookback_hours)

        obs_total = int(
            (await session.scalar(select(func.count(GstObservationSession.id)).where(GstObservationSession.created_at >= cutoff))) or 0
        )
        obs_finished = int(
            (await session.scalar(select(func.count(GstObservationSession.id)).where(GstObservationSession.created_at >= cutoff).where(GstObservationSession.status == "finished"))) or 0
        )
        profiles = int(
            (await session.scalar(select(func.count(GstPortalProfile.id)).where(GstPortalProfile.created_at >= cutoff))) or 0
        )
        sessions = int(
            (await session.scalar(select(func.count(GstSessionHealth.id)).where(GstSessionHealth.created_at >= cutoff))) or 0
        )
        replay_total = int(
            (await session.scalar(select(func.count(ReplayIntegrityAudit.id)).where(ReplayIntegrityAudit.created_at >= cutoff))) or 0
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

        score = 100
        if obs_total == 0:
            score -= 40
        if obs_finished == 0:
            score -= 30
        if replay_ok_pct < 99:
            score -= 20
        if profiles < 5:
            score -= 10
        if sessions < 1:
            score -= 10
        score = max(0, min(100, score))

        details = {
            "lookback_hours": lookback_hours,
            "observation_total": obs_total,
            "observation_finished": obs_finished,
            "profile_snapshots": profiles,
            "session_health_samples": sessions,
            "replay_ok_percent": replay_ok_pct,
        }
        return GstReadinessReport(score=score, details=details)

