from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.settings import Settings
from gst_automation.db.models.browser.browser_artifact import BrowserArtifact
from gst_automation.db.models.browser.browser_context import BrowserContextRecord
from gst_automation.db.models.orchestration.job_attempt import JobAttempt
from gst_automation.db.models.orchestration.job_lease import JobLease


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    ts_ms: int
    kind: str
    details: dict[str, Any]


def _dt_to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


@dataclass(frozen=True, slots=True)
class TimelineService:
    settings: Settings

    async def build_for_job(self, session: AsyncSession, *, job_id: uuid.UUID) -> list[TimelineEvent]:
        events: list[TimelineEvent] = []

        # Contexts
        res = await session.execute(
            select(BrowserContextRecord).where(BrowserContextRecord.job_id == job_id).order_by(BrowserContextRecord.created_at.asc())
        )
        contexts = list(res.scalars().all())
        for c in contexts:
            events.append(
                TimelineEvent(
                    ts_ms=_dt_to_ms(c.created_at),
                    kind="context.created",
                    details={
                        "context_id": str(c.id),
                        "browser_id": str(c.browser_id),
                        "worker_name": c.worker_name,
                    },
                )
            )
            if c.closed_at:
                events.append(
                    TimelineEvent(
                        ts_ms=_dt_to_ms(c.closed_at),
                        kind="context.closed",
                        details={"context_id": str(c.id), "state": c.state},
                    )
                )

        # Attempts (retry correlation)
        res = await session.execute(
            select(JobAttempt).where(JobAttempt.job_id == job_id).order_by(JobAttempt.attempt_no.asc())
        )
        for a in res.scalars().all():
            events.append(
                TimelineEvent(
                    ts_ms=_dt_to_ms(a.started_at),
                    kind="attempt.started",
                    details={
                        "attempt_id": str(a.id),
                        "attempt_no": a.attempt_no,
                        "trace_id": a.trace_id,
                        "correlation_id": a.correlation_id,
                        "run_id": a.run_id,
                        "status": a.status,
                    },
                )
            )
            if a.finished_at:
                events.append(
                    TimelineEvent(
                        ts_ms=_dt_to_ms(a.finished_at),
                        kind="attempt.finished",
                        details={"attempt_id": str(a.id), "status": a.status},
                    )
                )

        # Lease times (approx)
        res = await session.execute(select(JobLease).where(JobLease.job_id == job_id))
        lease = res.scalars().first()
        if lease:
            events.append(
                TimelineEvent(
                    ts_ms=_dt_to_ms(lease.acquired_at),
                    kind="lease.acquired",
                    details={"lease_token": lease.lease_token, "fencing_token": int(lease.fencing_token)},
                )
            )
            events.append(
                TimelineEvent(
                    ts_ms=_dt_to_ms(lease.last_heartbeat_at),
                    kind="lease.heartbeat",
                    details={},
                )
            )

        # Artifacts (DB indexed)
        res = await session.execute(
            select(BrowserArtifact).where(BrowserArtifact.job_id == job_id).order_by(BrowserArtifact.created_at.asc())
        )
        for a in res.scalars().all():
            events.append(
                TimelineEvent(
                    ts_ms=_dt_to_ms(a.created_at),
                    kind=f"artifact.{a.kind}",
                    details={"relpath": a.relpath, "context_id": str(a.context_id), "size": a.byte_size},
                )
            )

        # Replay events (from disk) - merge into timeline.
        artifacts_root = Path(self.settings.browser_artifacts_dir)
        for c in contexts:
            replay = artifacts_root / str(job_id) / str(c.id) / "replay.jsonl"
            if not replay.exists():
                continue
            try:
                for line in replay.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    obj = json.loads(line)
                    ts_ms = int(obj.get("ts_ms", 0))
                    typ = str(obj.get("type", "replay.event"))
                    events.append(TimelineEvent(ts_ms=ts_ms, kind=typ, details={k: v for k, v in obj.items() if k != "ts_ms"}))
            except Exception:
                continue

        events.sort(key=lambda e: e.ts_ms)
        return events
