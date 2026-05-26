from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.db.models.browser.browser_context import BrowserContextRecord
from gst_automation.db.models.browser.browser_crash import BrowserCrash
from gst_automation.db.models.browser.browser_instance import BrowserInstance
from gst_automation.db.models.validation.health_and_leaks import BrowserHealthSnapshot
from gst_automation.watchdog.anomaly import AnomalyRecord, AnomalyService


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BrowserHealthRow:
    browser_id: uuid.UUID
    score: int
    details: dict[str, object]


@dataclass(frozen=True, slots=True)
class BrowserHealthService:
    async def snapshot(self, session: AsyncSession, *, lookback_minutes: int = 60) -> list[BrowserHealthRow]:
        now = datetime.now(UTC)
        cutoff = now - timedelta(minutes=lookback_minutes)
        res = await session.execute(
            select(BrowserInstance).where(BrowserInstance.state.in_(["online", "retiring"])).limit(200)
        )
        browsers = list(res.scalars().all())
        out: list[BrowserHealthRow] = []
        for b in browsers:
            contexts_res = await session.execute(
                select(func.count(BrowserContextRecord.id))
                .where(BrowserContextRecord.browser_id == b.id)
                .where(BrowserContextRecord.created_at >= cutoff)
            )
            contexts = int(contexts_res.scalar() or 0)
            crashes_res = await session.execute(
                select(func.count(BrowserCrash.id))
                .where(BrowserCrash.browser_id == b.id)
                .where(BrowserCrash.created_at >= cutoff)
            )
            crashes = int(crashes_res.scalar() or 0)
            age_seconds = int((now - b.created_at).total_seconds())

            score = 100
            score -= min(50, crashes * 15)
            score -= min(30, int(contexts / 5) * 5)
            score -= 10 if age_seconds > 3600 else 0
            score = max(0, min(100, score))
            details = {"age_seconds": age_seconds, "contexts_1h": contexts, "crashes_1h": crashes, "state": b.state}

            session.add(
                BrowserHealthSnapshot(
                    browser_id=b.id,
                    score=score,
                    details_json=json.dumps(details, sort_keys=True, separators=(",", ":")),
                )
            )
            out.append(BrowserHealthRow(browser_id=b.id, score=score, details=details))

            if score <= 40:
                await AnomalyService(session).record(
                    AnomalyRecord(
                        anomaly_type="browser_health_low",
                        severity="HIGH",
                        score=90,
                        message="browser health score low (consider retirement/restart)",
                        details={"browser_id": str(b.id), **details, "score": score},
                    )
                )

        logger.info("browser.health_snapshots", count=len(out))
        return out

