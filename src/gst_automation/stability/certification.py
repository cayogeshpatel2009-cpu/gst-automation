from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.settings import Settings
from gst_automation.db.models.browser.browser_artifact import BrowserArtifact
from gst_automation.db.models.browser.browser_context import BrowserContextRecord
from gst_automation.db.models.stability.replay_cert import ReplayCertification
from gst_automation.validation.cleanup_invariants import CleanupInvariantScanner
from gst_automation.validation.replay_integrity import ReplayIntegrityValidator


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CertificationService:
    settings: Settings

    async def certify_job(self, session: AsyncSession, *, job_id: uuid.UUID) -> list[ReplayCertification]:
        res = await session.execute(
            select(BrowserContextRecord).where(BrowserContextRecord.job_id == job_id).limit(20)
        )
        contexts = list(res.scalars().all())

        replay = ReplayIntegrityValidator(settings=self.settings)
        cleanup = CleanupInvariantScanner(settings=self.settings)
        cleanup_report = await cleanup.scan(session, run_id=None)

        out: list[ReplayCertification] = []
        for c in contexts:
            replay_result = await replay.validate_context(session, job_id=job_id, context_id=c.id)

            artifacts = await session.execute(
                select(BrowserArtifact.kind, BrowserArtifact.relpath)
                .where(BrowserArtifact.job_id == job_id)
                .where(BrowserArtifact.context_id == c.id)
            )
            kinds = [r[0] for r in artifacts.all()]
            artifact_ok = all(k in kinds for k in ["trace", "har", "replay"])

            report = {
                "job_id": str(job_id),
                "context_id": str(c.id),
                "replay_status": replay_result.status,
                "replay_issues": replay_result.issues,
                "artifact_kinds": sorted(set(kinds)),
                "artifact_minimum_ok": artifact_ok,
                "cleanup_status": cleanup_report.status,
            }
            status = "pass"
            if replay_result.status != "ok" or not artifact_ok or cleanup_report.status != "ok":
                status = "fail"

            payload = json.dumps(report, sort_keys=True, separators=(",", ":"))
            row = ReplayCertification(
                job_id=job_id,
                context_id=c.id,
                status=status,
                report_json=payload,
                report_sha256_hex=_sha256_hex(payload),
                created_at=datetime.now(UTC),
            )
            session.add(row)
            out.append(row)
        await session.flush()
        return out

    def export_report_path(self, *, job_id: uuid.UUID, context_id: uuid.UUID) -> Path:
        return Path(self.settings.browser_artifacts_dir) / str(job_id) / str(context_id) / "certification.json"

