from __future__ import annotations

import json
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.browser.artifacts import ArtifactManager
from gst_automation.db.models.browser.browser_context import BrowserContextRecord
from gst_automation.db.models.browser.browser_artifact import BrowserArtifact
from gst_automation.db.models.email.delivery import EmailDelivery
from gst_automation.db.models.gst.execution import GstExecutionReport
from gst_automation.db.models.gst.selector_health import SelectorHealthEvent
from gst_automation.db.models.orchestration.job import Job
from gst_automation.db.models.orchestration.job_attempt import JobAttempt
from gst_automation.db.models.orchestration.retry_history import RetryHistory


def _json_bytes(obj: object) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


@dataclass(frozen=True, slots=True)
class ForensicsBundleResult:
    path: Path
    relpath: str
    context_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class GstForensicsPackager:
    artifacts_root: Path

    async def package_job(self, session: AsyncSession, *, job_id: uuid.UUID) -> ForensicsBundleResult:
        job = await session.get(Job, job_id)
        if job is None:
            raise RuntimeError("job not found")

        res = await session.execute(
            select(BrowserContextRecord).where(BrowserContextRecord.job_id == job_id).order_by(BrowserContextRecord.created_at.asc()).limit(20)
        )
        contexts = list(res.scalars().all())
        primary_context_id = contexts[0].id if contexts else uuid.UUID(int=0)

        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        out_dir = self.artifacts_root / str(job_id) / "forensics"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"forensics_{stamp}.zip"

        # DB snapshots
        attempts = list(
            (await session.execute(select(JobAttempt).where(JobAttempt.job_id == job_id).order_by(JobAttempt.attempt_no.asc()))).scalars().all()
        )
        retries = list(
            (await session.execute(select(RetryHistory).where(RetryHistory.job_id == job_id).order_by(RetryHistory.created_at.asc()))).scalars().all()
        )
        selector_events = list(
            (await session.execute(select(SelectorHealthEvent).where(SelectorHealthEvent.job_id == job_id).order_by(SelectorHealthEvent.created_at.asc()))).scalars().all()
        )
        reports = list(
            (await session.execute(select(GstExecutionReport).where(GstExecutionReport.job_id == job_id).order_by(GstExecutionReport.created_at.asc()))).scalars().all()
        )
        emails = []
        if job.client_id:
            emails = list(
                (await session.execute(select(EmailDelivery).where(EmailDelivery.client_id == job.client_id).order_by(EmailDelivery.created_at.desc()).limit(20))).scalars().all()
            )

        # Include indexed artifact list
        artifacts = list(
            (await session.execute(select(BrowserArtifact).where(BrowserArtifact.job_id == job_id))).scalars().all()
        )

        with zipfile.ZipFile(out_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("db/job.json", _json_bytes({"id": str(job.id), "kind": job.kind, "state": job.state, "payload_json": job.payload_json}))
            zf.writestr(
                "db/attempts.json",
                _json_bytes(
                    [
                        {
                            "id": str(a.id),
                            "attempt_no": a.attempt_no,
                            "status": a.status,
                            "started_at": a.started_at.isoformat() if a.started_at else None,
                            "finished_at": a.finished_at.isoformat() if a.finished_at else None,
                            "trace_id": a.trace_id,
                            "correlation_id": a.correlation_id,
                            "run_id": a.run_id,
                            "error_class": a.error_class,
                            "error_message": a.error_message,
                        }
                        for a in attempts
                    ]
                ),
            )
            zf.writestr(
                "db/retries.json",
                _json_bytes(
                    [
                        {
                            "id": str(r.id),
                            "classification": r.classification,
                            "backoff_seconds": r.backoff_seconds,
                            "jitter_seconds": r.jitter_seconds,
                            "reason": r.reason,
                            "scheduled_at": r.scheduled_at.isoformat(),
                            "created_at": r.created_at.isoformat(),
                        }
                        for r in retries
                    ]
                ),
            )
            zf.writestr(
                "db/selector_health_events.json",
                _json_bytes(
                    [
                        {
                            "id": str(e.id),
                            "context_id": str(e.context_id),
                            "selector_key": e.selector_key,
                            "selector_version": e.selector_version,
                            "result": e.result,
                            "candidate_index": e.candidate_index,
                            "candidates_total": e.candidates_total,
                            "latency_ms": e.latency_ms,
                            "details_json": e.details_json,
                            "created_at": e.created_at.isoformat(),
                        }
                        for e in selector_events
                    ]
                ),
            )
            zf.writestr(
                "db/execution_reports.json",
                _json_bytes(
                    [
                        {
                            "id": str(r.id),
                            "status": r.status,
                            "score": r.score,
                            "report_json": r.report_json,
                            "created_at": r.created_at.isoformat(),
                        }
                        for r in reports
                    ]
                ),
            )
            zf.writestr(
                "db/email_deliveries.json",
                _json_bytes(
                    [
                        {
                            "id": str(e.id),
                            "status": e.status,
                            "to_email": e.to_email,
                            "cc_email": e.cc_email,
                            "subject": e.subject,
                            "attachment_path": e.attachment_path,
                            "idempotency_key": e.idempotency_key,
                            "error": e.error,
                            "created_at": e.created_at.isoformat(),
                            "sent_at": e.sent_at.isoformat() if e.sent_at else None,
                        }
                        for e in emails
                    ]
                ),
            )
            zf.writestr(
                "db/artifacts_index.json",
                _json_bytes(
                    [
                        {
                            "context_id": str(a.context_id),
                            "kind": a.kind,
                            "relpath": a.relpath,
                            "sha256_hex": a.sha256_hex,
                            "byte_size": a.byte_size,
                        }
                        for a in artifacts
                    ]
                ),
            )

            # Include on-disk artifacts per context.
            for c in contexts:
                root = self.artifacts_root / str(job_id) / str(c.id)
                if not root.exists():
                    continue
                for p in root.rglob("*"):
                    if not p.is_file():
                        continue
                    # Prevent bundling the bundle itself if rerun.
                    if p == out_path:
                        continue
                    rel = p.relative_to(self.artifacts_root)
                    zf.write(p, arcname=str(Path("artifacts") / rel))

        relpath = str(out_path.relative_to(self.artifacts_root))
        # Index as a normal artifact for operator retrieval.
        await ArtifactManager(artifacts_root=self.artifacts_root).record_file(
            session,
            job_id=job_id,
            context_id=primary_context_id,
            kind="forensics_bundle",
            path=out_path,
            relpath=relpath,
        )
        return ForensicsBundleResult(path=out_path, relpath=relpath, context_id=primary_context_id)
