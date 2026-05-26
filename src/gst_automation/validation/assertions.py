from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.db.models.browser.browser_artifact import BrowserArtifact
from gst_automation.db.models.browser.browser_context import BrowserContextRecord
from gst_automation.db.models.orchestration.job import Job
from gst_automation.db.models.orchestration.job_attempt import JobAttempt
from gst_automation.db.models.orchestration.job_lease import JobLease
from gst_automation.db.models.orchestration.worker_heartbeat import WorkerHeartbeat


logger = get_logger(__name__)


Severity = Literal["INFO", "WARNING", "HIGH", "CRITICAL"]


@dataclass(frozen=True, slots=True)
class AssertionFinding:
    check: str
    severity: Severity
    message: str
    details: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AssertionReport:
    ok: bool
    findings: list[AssertionFinding]

    def to_json(self) -> str:
        payload = {
            "ok": self.ok,
            "findings": [
                {
                    "check": f.check,
                    "severity": f.severity,
                    "message": f.message,
                    "details": f.details,
                }
                for f in self.findings
            ],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class ExecutionAssertionEngine:
    """Runtime assertions for validation runs (DB-first, bounded scans)."""

    max_findings: int = 200

    async def run_for_jobs(
        self,
        session: AsyncSession,
        *,
        job_ids: list[uuid.UUID],
        heartbeat_max_gap_seconds: int = 120,
    ) -> AssertionReport:
        findings: list[AssertionFinding] = []
        now = datetime.now(UTC)

        # Stale leases (global, not just provided job ids).
        stale = (await session.execute(select(JobLease).where(JobLease.expires_at < now).limit(50))).scalars().all()
        if stale:
            findings.append(
                AssertionFinding(
                    check="stale_leases",
                    severity="HIGH",
                    message="stale leases present (lease recovery should reclaim)",
                    details={"count": len(stale), "job_ids": [str(r.job_id) for r in stale[:25]]},
                )
            )

        # Active contexts for completed jobs => leak.
        res = await session.execute(
            select(BrowserContextRecord)
            .where(BrowserContextRecord.job_id.in_(job_ids))
            .where(BrowserContextRecord.state == "active")
            .limit(200)
        )
        active_contexts = list(res.scalars().all())
        if active_contexts:
            findings.append(
                AssertionFinding(
                    check="active_contexts",
                    severity="HIGH",
                    message="browser contexts still active for validation jobs",
                    details={"contexts": [str(c.id) for c in active_contexts[:50]]},
                )
            )

        # Minimum artifacts: trace, har, replay should exist for each context (best-effort).
        for job_id in job_ids[:50]:
            ctx_res = await session.execute(
                select(BrowserContextRecord).where(BrowserContextRecord.job_id == job_id).limit(20)
            )
            contexts = list(ctx_res.scalars().all())
            for c in contexts:
                art_res = await session.execute(
                    select(BrowserArtifact.kind)
                    .where(BrowserArtifact.job_id == job_id)
                    .where(BrowserArtifact.context_id == c.id)
                )
                kinds = {r[0] for r in art_res.all()}
                missing = [k for k in ["trace", "har", "replay"] if k not in kinds]
                if missing:
                    findings.append(
                        AssertionFinding(
                            check="missing_artifacts",
                            severity="WARNING",
                            message="context missing minimum artifacts",
                            details={"job_id": str(job_id), "context_id": str(c.id), "missing": missing},
                        )
                    )
                    if len(findings) >= self.max_findings:
                        break
            if len(findings) >= self.max_findings:
                break

        # Stuck jobs: queued/leased/retrying beyond a threshold.
        stuck_cutoff = now - timedelta(minutes=10)
        stuck = (
            await session.execute(
                select(Job)
                .where(Job.id.in_(job_ids))
                .where(Job.state.in_(["queued", "leased", "retrying"]))
                .where(Job.state_updated_at < stuck_cutoff)
                .limit(50)
            )
        ).scalars().all()
        if stuck:
            findings.append(
                AssertionFinding(
                    check="stuck_jobs",
                    severity="HIGH",
                    message="jobs appear stuck (state not updated recently)",
                    details={"jobs": [{"job_id": str(j.id), "state": j.state} for j in stuck]},
                )
            )

        # Worker heartbeat gaps (best-effort): for workers that touched these jobs.
        attempt_res = await session.execute(
            select(JobAttempt.worker_name)
            .where(JobAttempt.job_id.in_(job_ids))
            .limit(200)
        )
        workers = sorted({r[0] for r in attempt_res.all() if r[0]})
        for w in workers[:20]:
            hb_res = await session.execute(
                select(func.max(WorkerHeartbeat.heartbeat_at)).where(WorkerHeartbeat.worker_name == w)
            )
            last = hb_res.scalar()
            if last is None:
                findings.append(
                    AssertionFinding(
                        check="missing_heartbeats",
                        severity="WARNING",
                        message="no worker heartbeats found for worker",
                        details={"worker_name": w},
                    )
                )
                continue
            gap = (now - last).total_seconds()
            if gap > heartbeat_max_gap_seconds:
                findings.append(
                    AssertionFinding(
                        check="heartbeat_gap",
                        severity="WARNING",
                        message="worker heartbeat gap exceeds threshold",
                        details={"worker_name": w, "gap_seconds": int(gap)},
                    )
                )

        ok = not any(f.severity in {"HIGH", "CRITICAL"} for f in findings)
        logger.info("validation.assertions", ok=ok, findings=len(findings))
        return AssertionReport(ok=ok, findings=findings[: self.max_findings])

