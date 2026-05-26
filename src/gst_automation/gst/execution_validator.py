from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.email.delivery import EmailDelivery
from gst_automation.db.models.browser.browser_artifact import BrowserArtifact
from gst_automation.db.models.gst.execution import GstExecutionReport
from gst_automation.db.models.gst.selector_health import SelectorHealthEvent
from gst_automation.db.models.orchestration.job import Job
from gst_automation.db.models.validation.cleanup_audit import CleanupAudit
from gst_automation.db.models.validation.health_and_leaks import ReplayIntegrityAudit
from gst_automation.gst.xlsx_validation import XlsxValidator


@dataclass(frozen=True, slots=True)
class GstExecutionValidator:
    async def validate_job(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        client_id: uuid.UUID,
        period: str,
        require_email_sent: bool = False,
        artifacts_root: Path | None = None,
    ) -> GstExecutionReport:
        job = await session.get(Job, job_id)
        status = "ok"
        score = 100
        details: dict[str, object] = {"job_state": job.state if job else None}

        # Selector health for this job
        res = await session.execute(
            select(
                func.count(SelectorHealthEvent.id),
                func.sum(func.case((SelectorHealthEvent.result == "fail", 1), else_=0)),
                func.sum(func.case((SelectorHealthEvent.result == "fallback", 1), else_=0)),
                func.max(SelectorHealthEvent.latency_ms),
                func.percentile_cont(0.95).within_group(SelectorHealthEvent.latency_ms),
            ).where(SelectorHealthEvent.job_id == job_id)
        )
        total, fails, fallbacks, max_ms, p95_ms = res.one()
        sel_total = int(total or 0)
        sel_fails = int(fails or 0)
        sel_fallbacks = int(fallbacks or 0)
        details["selector_samples"] = sel_total
        details["selector_fails"] = sel_fails
        details["selector_fallbacks"] = sel_fallbacks
        details["selector_max_latency_ms"] = int(max_ms or 0)
        details["selector_p95_latency_ms"] = int(p95_ms or 0)
        if sel_fails > 0:
            status = "violation"
            score -= 35
        elif sel_total > 0 and (sel_fallbacks / max(1, sel_total)) >= 0.3:
            status = "violation"
            score -= 10
        if int(p95_ms or 0) >= 10_000:
            status = "violation"
            score -= 10

        # Download + XLSX validation (best-effort from artifacts)
        res = await session.execute(
            select(BrowserArtifact).where(BrowserArtifact.job_id == job_id).where(BrowserArtifact.kind == "download").limit(5)
        )
        downloads = list(res.scalars().all())
        details["download_artifacts"] = len(downloads)
        xlsx_ok = False
        xlsx_details: dict[str, object] = {"checked": False}
        if downloads:
            # Prefer the largest download artifact (avoids picking tiny error HTML renamed as xlsx).
            best = sorted(downloads, key=lambda a: int(a.byte_size or 0), reverse=True)[0]
            xlsx_path = Path(best.relpath)
            if not xlsx_path.is_absolute() and artifacts_root is not None:
                xlsx_path = artifacts_root / xlsx_path
            xlsx_details["path"] = str(xlsx_path)
            if xlsx_path.exists() and xlsx_path.suffix.lower() == ".xlsx" and xlsx_path.stat().st_size >= 10_000:
                xlsx_details["checked"] = True
                v = XlsxValidator().validate(xlsx_path)
                xlsx_ok = bool(v.ok)
                xlsx_details.update(
                    {
                        "ok": v.ok,
                        "sheet_names": v.sheet_names,
                        "min_rows_ok": v.min_rows_ok,
                        "byte_size": v.byte_size,
                    }
                )
        details["xlsx_validation"] = xlsx_details
        if xlsx_details.get("checked") and not xlsx_ok:
            status = "violation"
            score -= 25

        # Replay integrity
        res = await session.execute(
            select(ReplayIntegrityAudit).where(ReplayIntegrityAudit.job_id == job_id).order_by(ReplayIntegrityAudit.created_at.desc()).limit(5)
        )
        replay_rows = list(res.scalars().all())
        replay_ok = all(r.status == "ok" for r in replay_rows) if replay_rows else True
        if not replay_ok:
            status = "violation"
            score -= 20
        details["replay_ok"] = replay_ok

        # Cleanup audit in last 10 minutes
        cutoff = datetime.now(UTC) - timedelta(minutes=10)
        res = await session.execute(
            select(CleanupAudit).where(CleanupAudit.created_at >= cutoff).order_by(CleanupAudit.created_at.desc()).limit(1)
        )
        ca = res.scalars().first()
        if ca and ca.status != "ok":
            status = "violation"
            score -= 20
        details["cleanup_status_recent"] = ca.status if ca else None

        # Email status (optional)
        if require_email_sent:
            res = await session.execute(
                select(EmailDelivery)
                .where(EmailDelivery.client_id == client_id)
                .order_by(EmailDelivery.created_at.desc())
                .limit(5)
            )
            emails = list(res.scalars().all())
            sent = any(e.status == "sent" for e in emails)
            if not sent:
                status = "violation"
                score -= 10
            details["email_sent_recent"] = sent

        if job and job.state not in {"completed"}:
            status = "error"
            score = min(score, 30)

        row = GstExecutionReport(
            job_id=job_id,
            client_id=client_id,
            period=period,
            status=status,
            score=max(0, min(100, score)),
            report_json=json.dumps(details, sort_keys=True, separators=(",", ":")),
        )
        session.add(row)
        await session.flush()
        return row
