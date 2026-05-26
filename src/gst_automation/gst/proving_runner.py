from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from celery import Celery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.settings import Settings
from gst_automation.db.models.orchestration.job import Job
from gst_automation.gst.execution_validator import GstExecutionValidator
from gst_automation.gst.forensics import GstForensicsPackager
from gst_automation.orchestration.dto import JobCreate, JobPriority
from gst_automation.orchestration.services.orchestrator_service import OrchestratorService


@dataclass(frozen=True, slots=True)
class ProvingResult:
    ok: bool
    job_id: uuid.UUID
    job_state: str
    execution_report_id: uuid.UUID | None
    execution_status: str | None
    score: int | None
    report: dict[str, object] | None
    forensics_relpath: str | None


@dataclass(frozen=True, slots=True)
class RealExecutionProver:
    settings: Settings
    session: AsyncSession
    celery: Celery

    async def run_one(
        self,
        *,
        client_id: uuid.UUID,
        financial_year: str,
        period_yyyy_mm: str,
        timeout_seconds: int = 1800,
        require_email_sent: bool = False,
    ) -> ProvingResult:
        orch = OrchestratorService(session=self.session, celery=self.celery)
        job_id = await orch.create_and_enqueue(
            JobCreate(
                kind="gstr2b_download",
                queue="downloads",
                priority=JobPriority.P2_DOWNLOAD,
                client_id=client_id,
                payload={
                    "client_id": str(client_id),
                    "financial_year": financial_year,
                    "period_yyyy_mm": period_yyyy_mm,
                },
            ),
            actor="real_execution_prover",
        )
        await self.session.commit()

        # Wait for completion.
        deadline = datetime.now(UTC) + timedelta(seconds=int(timeout_seconds))
        state = "unknown"
        while datetime.now(UTC) < deadline:
            row = (await self.session.execute(select(Job).where(Job.id == job_id))).scalars().first()
            state = row.state if row else "missing"
            if state in {"completed", "dead_lettered"}:
                break
            await self.session.commit()
            import asyncio

            await asyncio.sleep(2)

        # Always run post validator for proving (even if worker already did it).
        rep = await GstExecutionValidator().validate_job(
            self.session,
            job_id=job_id,
            client_id=client_id,
            period=period_yyyy_mm,
            require_email_sent=require_email_sent,
            artifacts_root=Path(self.settings.browser_artifacts_dir),
        )
        await self.session.commit()

        report_json = json.loads(rep.report_json or "{}")
        forensics_relpath: str | None = None
        if rep.status != "ok" or state != "completed":
            try:
                bundle = await GstForensicsPackager(artifacts_root=Path(self.settings.browser_artifacts_dir)).package_job(
                    self.session, job_id=job_id
                )
                await self.session.commit()
                forensics_relpath = bundle.relpath
            except Exception:
                forensics_relpath = None

        ok = (state == "completed") and (rep.status == "ok")
        return ProvingResult(
            ok=ok,
            job_id=job_id,
            job_state=state,
            execution_report_id=rep.id,
            execution_status=rep.status,
            score=rep.score,
            report=report_json,
            forensics_relpath=forensics_relpath,
        )

