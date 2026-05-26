from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.db.models.browser.browser_artifact import BrowserArtifact
from gst_automation.db.models.browser.browser_context import BrowserContextRecord
from gst_automation.db.models.orchestration.distributed_lock import DistributedLock
from gst_automation.db.models.orchestration.job import Job
from gst_automation.db.models.orchestration.job_lease import JobLease
from gst_automation.db.models.validation.cleanup_audit import CleanupAudit
from gst_automation.db.models.validation.health_and_leaks import LeakFinding
from gst_automation.watchdog.anomaly import AnomalyRecord, AnomalyService


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CleanupInvariantReport:
    status: str
    findings: dict[str, object]


@dataclass(frozen=True, slots=True)
class CleanupInvariantScanner:
    settings: Settings

    async def scan(self, session: AsyncSession, *, run_id: uuid.UUID | None = None) -> CleanupInvariantReport:
        now = datetime.now(UTC)
        findings: dict[str, object] = {}

        # 1) Stale leases
        res = await session.execute(select(JobLease).where(JobLease.expires_at < now).limit(200))
        stale_leases = list(res.scalars().all())
        findings["stale_leases"] = [str(r.job_id) for r in stale_leases]

        # 2) Orphan/active browser contexts
        res = await session.execute(
            select(BrowserContextRecord)
            .where(BrowserContextRecord.state == "active")
            .order_by(BrowserContextRecord.created_at.asc())
            .limit(200)
        )
        active_contexts = list(res.scalars().all())
        orphan_contexts: list[dict[str, object]] = []
        for c in active_contexts:
            lease = await session.execute(
                select(JobLease).where(JobLease.job_id == c.job_id).limit(1)
            )
            lease_row = lease.scalars().first()
            job_res = await session.execute(select(Job).where(Job.id == c.job_id).limit(1))
            job = job_res.scalars().first()
            # Orphan if job completed but context still active, or missing lease.
            if (job and job.state == "completed") or lease_row is None:
                orphan_contexts.append(
                    {
                        "job_id": str(c.job_id),
                        "context_id": str(c.id),
                        "worker_name": c.worker_name,
                        "created_at": c.created_at.isoformat(),
                        "lease_present": lease_row is not None,
                        "job_state": job.state if job else None,
                    }
                )
        findings["orphan_contexts"] = orphan_contexts

        # 3) Dangling workspaces (filesystem) - best-effort.
        ws_root = Path(self.settings.work_dir) / "browser"
        dangling_ws: list[str] = []
        try:
            if ws_root.exists():
                cutoff = now - timedelta(minutes=15)
                for p in ws_root.glob("ws_*"):
                    try:
                        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=UTC)
                    except Exception:
                        continue
                    if mtime < cutoff:
                        dangling_ws.append(str(p))
        except Exception:
            pass
        findings["dangling_workspaces"] = dangling_ws[:200]

        # 4) Unindexed artifacts (filesystem -> DB) is expensive; do bounded audit:
        unindexed: list[str] = []
        artifacts_root = Path(self.settings.browser_artifacts_dir)
        try:
            if artifacts_root.exists():
                # Collect recent files only.
                cutoff = now - timedelta(days=2)
                recent_files: list[Path] = []
                for root, _dirs, files in os.walk(artifacts_root):
                    for f in files:
                        fp = Path(root) / f
                        try:
                            mtime = datetime.fromtimestamp(fp.stat().st_mtime, tz=UTC)
                        except Exception:
                            continue
                        if mtime >= cutoff:
                            recent_files.append(fp)
                    if len(recent_files) >= 500:
                        break
                # Build DB relpath set for those job/context dirs.
                relpaths = {str(p.relative_to(artifacts_root)) for p in recent_files if p.is_file()}
                if relpaths:
                    res = await session.execute(
                        select(BrowserArtifact.relpath).where(BrowserArtifact.relpath.in_(list(relpaths)))
                    )
                    indexed = {r[0] for r in res.all()}
                    for r in relpaths:
                        if r not in indexed:
                            unindexed.append(r)
        except Exception:
            pass
        findings["unindexed_artifacts_recent"] = unindexed[:200]

        # 5) Expired DB locks (fallback table)
        res = await session.execute(select(DistributedLock).where(DistributedLock.expires_at < now).limit(200))
        expired_locks = list(res.scalars().all())
        findings["expired_db_locks"] = [r.name for r in expired_locks]

        status = "ok"
        if stale_leases or orphan_contexts or dangling_ws or unindexed or expired_locks:
            status = "violation"

        audit = CleanupAudit(
            run_id=run_id,
            audit_scope="global",
            status=status,
            findings_json=json.dumps(findings, sort_keys=True, separators=(",", ":")),
        )
        session.add(audit)

        # Record anomalies for operator visibility.
        if status != "ok":
            anomaly = AnomalyService(session)
            await anomaly.record(
                AnomalyRecord(
                    anomaly_type="cleanup_invariant_violation",
                    severity="HIGH" if orphan_contexts else "WARNING",
                    score=90 if orphan_contexts else 60,
                    message="cleanup invariants violated (see cleanup_audits)",
                    details={
                        "stale_leases": len(stale_leases),
                        "orphan_contexts": len(orphan_contexts),
                        "dangling_workspaces": len(dangling_ws),
                        "unindexed_artifacts_recent": len(unindexed),
                        "expired_db_locks": len(expired_locks),
                    },
                )
            )

            session.add(
                LeakFinding(
                    leak_type="cleanup_invariant",
                    severity="HIGH" if orphan_contexts else "WARNING",
                    details_json=json.dumps(
                        {
                            "stale_leases": len(stale_leases),
                            "orphan_contexts": len(orphan_contexts),
                            "dangling_workspaces": len(dangling_ws),
                            "unindexed_artifacts_recent": len(unindexed),
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
            )

        logger.info("cleanup.scan", status=status)
        return CleanupInvariantReport(status=status, findings=findings)

