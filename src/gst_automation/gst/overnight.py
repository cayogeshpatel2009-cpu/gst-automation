from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from celery import Celery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.settings import Settings
from gst_automation.db.models.client import Client
from gst_automation.db.models.clients.client_config import ClientConfig
from gst_automation.gst.download_verifier import Gstr2bDownloadVerifier
from gst_automation.gst.monthly_tracker import MonthlyTrackerService
from gst_automation.orchestration.dto import JobCreate, JobPriority
from gst_automation.orchestration.services.orchestrator_service import OrchestratorService
from gst_automation.storage.folder_manager import FolderManager


@dataclass(frozen=True, slots=True)
class OvernightTickResult:
    window_open: bool
    enqueued: int
    skipped_already_ok: int
    skipped_outside_window: int
    errors: list[dict[str, object]]
    job_ids: list[str]


@dataclass(frozen=True, slots=True)
class OvernightScheduler:
    settings: Settings
    session: AsyncSession
    celery: Celery

    def _window_open(self, now: datetime) -> bool:
        # Execution Window: 15th -> 20th monthly (inclusive).
        return 15 <= int(now.day) <= 20

    async def tick(self, *, financial_year: str, period_yyyy_mm: str) -> OvernightTickResult:
        now = datetime.now(UTC)
        if not self._window_open(now):
            return OvernightTickResult(
                window_open=False,
                enqueued=0,
                skipped_already_ok=0,
                skipped_outside_window=0,
                errors=[],
                job_ids=[],
            )

        res = await self.session.execute(select(Client))
        clients = list(res.scalars().all())
        cfg_res = await self.session.execute(select(ClientConfig).where(ClientConfig.active == 1))
        cfgs = {c.client_id: c for c in cfg_res.scalars().all()}

        orch = OrchestratorService(session=self.session, celery=self.celery)
        tracker = MonthlyTrackerService(self.session)
        verifier = Gstr2bDownloadVerifier()

        enqueued = 0
        skipped_already_ok = 0
        errors: list[dict[str, object]] = []
        job_ids: list[str] = []

        for c in clients:
            cfg = cfgs.get(c.id)
            if cfg is None or c.status != "active":
                continue

            # Skip already-ok tracker entries.
            existing = await tracker.get(client_id=c.id, period=period_yyyy_mm)
            if existing is not None and existing.status == "ok":
                skipped_already_ok += 1
                continue

            # Skip if file already exists and validates.
            layout = FolderManager(folder_root=Path(cfg.folder_root)).layout(
                client_name=c.display_name, gstin=c.gstin, fy=financial_year, period_yyyy_mm=period_yyyy_mm
            )
            expected = layout.gstr2b_dir / f"GSTR2B_{c.gstin}_{period_yyyy_mm}.xlsx"
            if expected.exists() and verifier.verify(expected).ok:
                await tracker.upsert(
                    client_id=c.id,
                    period=period_yyyy_mm,
                    status="ok",
                    job_id=existing.job_id if existing else None,
                    details={"reason": "file_already_present", "path": str(expected)},
                )
                skipped_already_ok += 1
                continue

            # Enqueue idempotently per client-period (prevents duplicate runs on restarts).
            try:
                jid = await orch.create_and_enqueue(
                    JobCreate(
                        kind="gstr2b_download",
                        queue="downloads",
                        priority=int(cfg.priority or JobPriority.P2_DOWNLOAD),
                        client_id=c.id,
                        idempotency_key=f"gstr2b:{c.id}:{period_yyyy_mm}",
                        payload={
                            "client_id": str(c.id),
                            "financial_year": financial_year,
                            "period_yyyy_mm": period_yyyy_mm,
                        },
                    ),
                    actor="overnight_scheduler",
                )
                await tracker.upsert(
                    client_id=c.id,
                    period=period_yyyy_mm,
                    status="queued",
                    job_id=jid,
                    details={"financial_year": financial_year},
                )
                enqueued += 1
                job_ids.append(str(jid))
            except Exception as exc:  # noqa: BLE001
                errors.append({"client_id": str(c.id), "gstin": c.gstin, "error": str(exc)})

        return OvernightTickResult(
            window_open=True,
            enqueued=enqueued,
            skipped_already_ok=skipped_already_ok,
            skipped_outside_window=0,
            errors=errors,
            job_ids=job_ids,
        )

