from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import shutil

from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.browser.artifacts import ArtifactManager
from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.db.models.clients.client_config import ClientConfig
from gst_automation.gst.auth_detection import GstAuthDetector
from gst_automation.gst.auth_session import GstAuthSessionEngine
from gst_automation.gst.errors import GstAuthRequired
from gst_automation.gst.operator_checkpoints import OperatorCheckpointService
from gst_automation.gst.selector_promotion import SelectorRegistryLoader
from gst_automation.gst.downloads import DownloadWatcher
from gst_automation.gst.xlsx_validation import XlsxValidator
from gst_automation.gst.download_verifier import Gstr2bDownloadVerifier, quarantine_file
from gst_automation.gst.errors import GstDownloadCorrupt, GstDownloadInvalid
from gst_automation.db.models.gst.session_health import GstSessionHealth
from gst_automation.portal.dsl import PortalDsl
from gst_automation.portal.selectors.registry import SelectorRegistry
from gst_automation.portal.selectors.resolver import SelectorResolver
from gst_automation.db.models.gst.selector_health import SelectorHealthEvent
from gst_automation.storage.folder_manager import FolderManager
from gst_automation.orchestration.dto import JobCreate, JobPriority
from gst_automation.orchestration.services.orchestrator_service import OrchestratorService
from gst_automation.celery_app.client import get_celery
import redis.asyncio as redis
from gst_automation.locks.redis_lock import RedisLockManager
from gst_automation.gst.metrics import GSTR2B_RUNS_TOTAL, GSTR2B_XLSX_VALIDATION_TOTAL
import time
from gst_automation.archive.hashing import sha256_file
from gst_automation.gst.monthly_tracker import MonthlyTrackerService


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Gstr2bDownloadPayload:
    client_id: str
    financial_year: str
    period_yyyy_mm: str


@dataclass(frozen=True, slots=True)
class Gstr2bDownloadEngine:
    settings: Settings

    async def run(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        payload_json: str,
    ) -> None:
        payload = Gstr2bDownloadPayload(**json.loads(payload_json))
        client_uuid = uuid.UUID(payload.client_id)

        # Fetch client config and base folder.
        cfg = await session.get(ClientConfig, client_uuid)
        if cfg is None:
            raise RuntimeError("client config missing")

        # Ensure deterministic folders exist.
        from gst_automation.db.models.client import Client

        client = await session.get(Client, client_uuid)
        if client is None:
            raise RuntimeError("client missing")
        layout = FolderManager(folder_root=Path(cfg.folder_root)).layout(
            client_name=client.display_name,
            gstin=client.gstin,
            fy=payload.financial_year,
            period_yyyy_mm=payload.period_yyyy_mm,
        )
        FolderManager(folder_root=Path(cfg.folder_root)).ensure(layout)

        # Duplicate prevention: if expected final file exists and verifies cleanly, skip run.
        expected_filename = f"GSTR2B_{client.gstin}_{payload.period_yyyy_mm}.xlsx"
        expected_dest = layout.gstr2b_dir / expected_filename
        if expected_dest.exists():
            v_existing = Gstr2bDownloadVerifier().verify(expected_dest)
            if v_existing.ok:
                await MonthlyTrackerService(session).upsert(
                    client_id=client_uuid,
                    period=payload.period_yyyy_mm,
                    status="skipped",
                    job_id=job_id,
                    details={"reason": "already_downloaded", "path": str(expected_dest), "sha256": v_existing.sha256_hex},
                )
                logger.info("gstr2b.skip_already_downloaded", client_id=payload.client_id, path=str(expected_dest))
                return

        r = redis.from_url(self.settings.redis_url)
        lock_mgr = RedisLockManager(r)
        lock = await lock_mgr.acquire(
            name=f"gstr2b:{client.gstin}:{payload.period_yyyy_mm}",
            owner=f"job:{job_id}",
            ttl_seconds=900,
        )
        if lock is None:
            await r.close()
            raise RuntimeError("gstr2b lock contention (duplicate run)")
        try:
            await MonthlyTrackerService(session).upsert(
                client_id=client_uuid,
                period=payload.period_yyyy_mm,
                status="running",
                job_id=job_id,
                details={"financial_year": payload.financial_year},
            )

            # Session-first auth: apply storage_state at context creation (already done by allocator).
            detector = GstAuthDetector()
            if self.settings.gst_probe_base_url:
                await page.goto(self.settings.gst_probe_base_url, wait_until="domcontentloaded")

            state = await detector.detect(page)
            # Record session health sample for stability analytics.
            session.add(
                GstSessionHealth(
                    job_id=job_id,
                    context_id=context_id,
                    state=str(state.state),
                    score=100 if state.state == "authenticated" else 0,
                    details_json=json.dumps({"url": page.url}, sort_keys=True, separators=(",", ":")),
                    created_at=datetime.now(UTC),
                )
            )
            if state.state != "authenticated":
                # Practical production behavior: attempt credential-driven gst-auth inside this SAME browser
                # context (HITL only for OTP/CAPTCHA) so the monthly run can continue without requiring a
                # separate operator step + retry.
                logger.warning("gst.auth_refresh_inline_start", client_id=payload.client_id, state=state.state, url=page.url)
                try:
                    await GstAuthSessionEngine(settings=self.settings).run(
                        session=session,
                        redis_client=r,
                        job_id=job_id,
                        context_id=context_id,
                        page=page,
                        artifacts_dir=Path(self.settings.browser_artifacts_dir) / str(job_id) / str(context_id),
                        payload_json=json.dumps(
                            {
                                "start_url": "https://services.gst.gov.in/services/login",
                                "client_id": payload.client_id,
                                "gstin": client.gstin,
                                "profile": payload.profile,
                                "ttl_days": 7,
                                "checkpoint_timeout_seconds": 900,
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("gst.auth_refresh_inline_failed", client_id=payload.client_id, err=str(exc))

                # Re-check auth state in the same context.
                try:
                    if self.settings.gst_probe_base_url:
                        await page.goto(self.settings.gst_probe_base_url, wait_until="domcontentloaded")
                except Exception:
                    pass
                state = await detector.detect(page)
                session.add(
                    GstSessionHealth(
                        job_id=job_id,
                        context_id=context_id,
                        state=str(state.state),
                        score=100 if state.state == "authenticated" else 0,
                        details_json=json.dumps({"url": page.url, "phase": "post_inline_auth"}, sort_keys=True, separators=(",", ":")),
                        created_at=datetime.now(UTC),
                    )
                )
                if state.state != "authenticated":
                    # Create operator checkpoint for explicit recovery, then fail retryably.
                    chk = OperatorCheckpointService(session)
                    checkpoint_id = await chk.create(
                        job_id=job_id,
                        context_id=context_id,
                        kind="gst_auth_refresh",
                        instructions="Inline gst-auth did not reach authenticated state. Resolve OTP/CAPTCHA via the checkpoint, or run gst-auth and retry.",
                        details={"client_id": payload.client_id, "auth_state": state.state, "url": page.url},
                    )
                    logger.warning("gst.auth_required", client_id=payload.client_id, checkpoint_id=str(checkpoint_id))
                    raise GstAuthRequired(f"auth required for client {payload.client_id}")

        # Load promoted selectors (operator-approved) and execute navigation.
            defs = await SelectorRegistryLoader().load_active_prefix(session, prefix="gst.")
            selector_registry = SelectorRegistry(definitions=defs)
            dsl = PortalDsl(
                settings=self.settings,
                artifacts=ArtifactManager(artifacts_root=Path(self.settings.browser_artifacts_dir)),
                selectors=selector_registry,
                resolver=SelectorResolver(),
            )

        # Checkpoints (selectors must be promoted by operator from observation).
            await dsl.safe_click(session, job_id=job_id, context_id=context_id, page=page, selector_key="gst.nav.returns")
            await dsl.safe_click(session, job_id=job_id, context_id=context_id, page=page, selector_key="gst.nav.gstr2b")

        # FY/month selection are portal-specific; keys are expected to be promoted.
            await dsl.safe_click(session, job_id=job_id, context_id=context_id, page=page, selector_key="gst.gstr2b.fy_dropdown")
            await dsl.safe_click(session, job_id=job_id, context_id=context_id, page=page, selector_key=f"gst.gstr2b.fy_option.{payload.financial_year}")

            await dsl.safe_click(session, job_id=job_id, context_id=context_id, page=page, selector_key="gst.gstr2b.period_dropdown")
            await dsl.safe_click(session, job_id=job_id, context_id=context_id, page=page, selector_key=f"gst.gstr2b.period_option.{payload.period_yyyy_mm}")

        # Generate/download (idempotent if already generated).
            try:
                await dsl.safe_click(session, job_id=job_id, context_id=context_id, page=page, selector_key="gst.gstr2b.generate")
            except Exception:
                pass

        # Download.
            download_def = selector_registry.latest(key="gst.gstr2b.download_excel")
            t0 = time.monotonic()
            try:
                resolved, idx, total = await dsl.resolver.resolve_detailed(
                    page, download_def, timeout_ms=self.settings.browser_action_timeout_ms
                )
                latency_ms = int((time.monotonic() - t0) * 1000)
                session.add(
                    SelectorHealthEvent(
                        job_id=job_id,
                        context_id=context_id,
                        selector_key=download_def.key,
                        selector_version=int(download_def.version),
                        result="ok" if idx == 0 else "fallback",
                        candidate_index=int(idx),
                        candidates_total=int(total),
                        latency_ms=latency_ms,
                        details_json=json.dumps({"url": page.url}, sort_keys=True, separators=(",", ":")),
                        created_at=datetime.now(UTC),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                latency_ms = int((time.monotonic() - t0) * 1000)
                session.add(
                    SelectorHealthEvent(
                        job_id=job_id,
                        context_id=context_id,
                        selector_key=download_def.key,
                        selector_version=int(download_def.version),
                        result="fail",
                        candidate_index=0,
                        candidates_total=len(download_def.candidates),
                        latency_ms=latency_ms,
                        details_json=json.dumps(
                            {"url": page.url, "err": str(exc)}, sort_keys=True, separators=(",", ":")
                        ),
                        created_at=datetime.now(UTC),
                    )
                )
                raise
            artifacts_dir = Path(self.settings.browser_artifacts_dir) / str(job_id) / str(context_id)
            watcher = DownloadWatcher(settings=self.settings, artifacts=ArtifactManager(artifacts_root=Path(self.settings.browser_artifacts_dir)))
            tmp_download_dir = artifacts_dir / "downloads"
            filename = f"GSTR2B_{client.gstin}_{payload.period_yyyy_mm}.xlsx"
            dl = await watcher.click_and_wait(
                session,
                job_id=job_id,
                context_id=context_id,
                page=page,
                click_selector=resolved,
                dest_dir=tmp_download_dir,
                filename=filename,
            )

        # Validate XLSX.
            # Keep legacy validator for basic checks, but prefer stricter verifier for corruption/partial detection.
            v0 = XlsxValidator().validate(dl.path)
            v = Gstr2bDownloadVerifier().verify(dl.path)
            if not (v0.ok and v.ok):
                GSTR2B_XLSX_VALIDATION_TOTAL.labels(result="fail").inc()
                try:
                    q = quarantine_file(src=dl.path, quarantine_dir=artifacts_dir / "quarantine")
                    logger.warning(
                        "gstr2b.download_quarantined",
                        client_id=payload.client_id,
                        period=payload.period_yyyy_mm,
                        path=str(q),
                        reasons=v.reasons,
                    )
                except Exception:
                    pass
                if v.classification == "retryable" or v.classification == "corrupt":
                    raise GstDownloadCorrupt(f"xlsx download corrupt/partial ({'; '.join(v.reasons)})")
                raise GstDownloadInvalid(f"xlsx download invalid ({'; '.join(v.reasons) if v.reasons else 'unknown'})")
            GSTR2B_XLSX_VALIDATION_TOTAL.labels(result="ok").inc()

            # Finalize to client folder (keep artifact copy for replay/forensics).
            dest = expected_dest
            tmp_dest = dest.with_suffix(dest.suffix + ".tmp")
            if tmp_dest.exists():
                tmp_dest.unlink(missing_ok=True)
            shutil.copy2(dl.path, tmp_dest)
            final_sha = sha256_file(tmp_dest)
            if final_sha != dl.sha256_hex:
                # Keep tmp for forensics; fail for retry.
                raise RuntimeError("stored file checksum mismatch")
            # Verify finalized tmp before commit (corruption/partial detection).
            vf = Gstr2bDownloadVerifier().verify(tmp_dest)
            if not vf.ok:
                try:
                    q2 = quarantine_file(src=tmp_dest, quarantine_dir=layout.downloads_dir / "QUARANTINE")
                    logger.warning(
                        "gstr2b.finalized_quarantined",
                        client_id=payload.client_id,
                        period=payload.period_yyyy_mm,
                        path=str(q2),
                        reasons=vf.reasons,
                    )
                except Exception:
                    pass
                raise GstDownloadCorrupt(f"finalized file verification failed ({'; '.join(vf.reasons)})")
            tmp_dest.replace(dest)
            logger.info("gstr2b.stored", client_id=payload.client_id, path=str(dest), sha256=dl.sha256_hex)

        # Enqueue email delivery (optional).
            if cfg.client_email:
                celery = get_celery()
                orch = OrchestratorService(session=session, celery=celery)
                await orch.create_and_enqueue(
                    JobCreate(
                        kind="email_delivery",
                        queue="emails",
                        priority=JobPriority.P3_EMAIL,
                        payload={
                            "client_id": payload.client_id,
                            "to_email": cfg.client_email,
                            "cc_email": cfg.cc_email,
                            "subject": f"GSTR-2B {client.gstin} {payload.period_yyyy_mm}",
                            "body": "Attached: GSTR-2B Excel.",
                            "attachment_path": str(dest),
                            "filename": dest.name,
                            "idempotency_key": f"gstr2b:{payload.client_id}:{payload.period_yyyy_mm}:{dl.sha256_hex}",
                        },
                    ),
                    actor="gstr2b_download",
                )
            GSTR2B_RUNS_TOTAL.labels(result="ok").inc()
            await MonthlyTrackerService(session).upsert(
                client_id=client_uuid,
                period=payload.period_yyyy_mm,
                status="ok",
                job_id=job_id,
                details={"path": str(dest), "sha256": dl.sha256_hex},
            )
        except Exception:
            GSTR2B_RUNS_TOTAL.labels(result="error").inc()
            try:
                await MonthlyTrackerService(session).upsert(
                    client_id=client_uuid,
                    period=payload.period_yyyy_mm,
                    status="failed",
                    job_id=job_id,
                    details={"financial_year": payload.financial_year},
                )
            except Exception:
                pass
            raise
        finally:
            try:
                await lock_mgr.release(lock)
            finally:
                await r.close()
