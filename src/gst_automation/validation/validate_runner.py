from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from celery import Celery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.db.models.orchestration.job import Job
from gst_automation.db.models.validation.validation_run import ValidationRun
from gst_automation.stability.readiness import ReadinessGateService, ReadinessPolicy
from gst_automation.stability.scoring_service import StabilityScoreService
from gst_automation.validation.assertions import ExecutionAssertionEngine
from gst_automation.validation.cleanup_invariants import CleanupInvariantScanner
from gst_automation.validation.dto import PortalSmokePayload
from gst_automation.validation.executor import ValidationExecutor
from gst_automation.validation.replay_integrity import ReplayIntegrityValidator
from gst_automation.validation.run_service import ValidationRunService
from gst_automation.validation.suites import ValidationSuites
from gst_automation.stability.soak_campaign import SoakCampaignConfig, SoakCampaignEngine


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ValidationCase:
    name: str
    payload: PortalSmokePayload
    expected: str  # ok|fail


def _simulation_cases() -> list[ValidationCase]:
    return [
        ValidationCase("login_flow", ValidationSuites.basic_smoke(), "ok"),
        ValidationCase("slow", PortalSmokePayload(start_path="/slow", actions=[]), "ok"),
        ValidationCase("modal_storm", ValidationSuites.chaos_modal_storm(), "ok"),
        ValidationCase("redirect_loop", ValidationSuites.chaos_redirect_loop(), "fail"),
        ValidationCase("broken_selector", ValidationSuites.selector_drift(), "fail"),
        ValidationCase("session_expired", PortalSmokePayload(start_path="/session-expired", actions=[]), "ok"),
        ValidationCase("error_spike", PortalSmokePayload(start_path="/error-spike", actions=[]), "fail"),
        ValidationCase("download_corrupt", PortalSmokePayload(start_path="/download-corrupt", actions=[]), "ok"),
        ValidationCase("partial_render", PortalSmokePayload(start_path="/partial-render", actions=[]), "ok"),
        ValidationCase("maintenance", PortalSmokePayload(start_path="/maintenance", actions=[]), "fail"),
    ]


@dataclass(frozen=True, slots=True)
class ValidationResult:
    run_id: uuid.UUID
    ok: bool
    summary: dict[str, object]


@dataclass(frozen=True, slots=True)
class SimulationValidationRunner:
    settings: Settings
    celery: Celery

    async def validate_smoke(self, session: AsyncSession, *, parallel: int = 1) -> ValidationResult:
        run_svc = ValidationRunService(session=session, celery=self.celery)
        run_id = await run_svc.create_run(
            run_kind="validate_smoke",
            scenario="test_portal",
            config={"parallel": parallel},
        )

        cases = _simulation_cases()
        job_ids: list[uuid.UUID] = []
        expected: dict[str, str] = {}
        for c in cases:
            for _ in range(parallel):
                jid = await run_svc.enqueue_portal_smoke(run_id=run_id, payload=c.payload, actor="validate_smoke")
                job_ids.append(jid)
                expected[str(jid)] = c.expected

        await session.commit()
        wait = await ValidationExecutor().wait_for_jobs(session, job_ids=job_ids, timeout_seconds=900)

        # Replay integrity audits (best-effort).
        replay = ReplayIntegrityValidator(settings=self.settings)
        replay_violations = 0
        for jid in job_ids:
            results = await replay.validate_job(session, job_id=jid)
            for r in results:
                if r.status != "ok":
                    replay_violations += 1

        cleanup = await CleanupInvariantScanner(settings=self.settings).scan(session, run_id=run_id)
        assertions = await ExecutionAssertionEngine().run_for_jobs(session, job_ids=job_ids)
        score = await StabilityScoreService().compute(session, scope="run", scope_id=run_id, window_minutes=60)

        # Expected vs actual.
        res = await session.execute(select(Job.id, Job.state).where(Job.id.in_(job_ids)))
        mismatches: list[dict[str, object]] = []
        for jid, state in res.all():
            exp = expected.get(str(jid), "ok")
            ok = (state == "completed") if exp == "ok" else (state in {"failed", "dead_letter"})
            if not ok:
                mismatches.append({"job_id": str(jid), "expected": exp, "state": state})

        ok = not wait.still_running and not mismatches and assertions.ok and cleanup.status == "ok" and replay_violations == 0
        summary = {
            "completed": len(wait.completed),
            "failed": len(wait.failed),
            "still_running": [str(x) for x in wait.still_running],
            "expected_mismatches": mismatches,
            "cleanup_status": cleanup.status,
            "assertions_ok": assertions.ok,
            "replay_violations": replay_violations,
            "stability_score": score.score,
        }
        await session.execute(
            ValidationRun.__table__.update()
            .where(ValidationRun.id == run_id)
            .values(summary_json=json.dumps(summary, sort_keys=True, separators=(",", ":")), status="finished", ended_at=datetime.now(UTC))
        )

        await session.commit()
        logger.info("validate.smoke.done", ok=ok, run_id=str(run_id))
        return ValidationResult(run_id=run_id, ok=ok, summary=summary)

    async def readiness_gate(self, session: AsyncSession) -> dict[str, object]:
        row = await ReadinessGateService(policy=ReadinessPolicy(min_score_last_12h=80)).evaluate(session)
        await session.commit()
        return {"gate_name": row.gate_name, "status": row.status, "score": row.score, "report_json": row.report_json}

    async def validate_replay(self, session: AsyncSession, *, limit_jobs: int = 25) -> dict[str, object]:
        # Replay integrity validation for most recent portal_smoke jobs.
        res = await session.execute(
            select(Job.id)
            .where(Job.kind == "portal_smoke")
            .order_by(Job.created_at.desc())
            .limit(limit_jobs)
        )
        job_ids = [r[0] for r in res.all()]
        replay = ReplayIntegrityValidator(settings=self.settings)
        violations = 0
        audited = 0
        for jid in job_ids:
            results = await replay.validate_job(session, job_id=jid)
            audited += 1
            if any(r.status != "ok" for r in results):
                violations += 1
        await session.commit()
        return {"audited_jobs": audited, "jobs_with_violations": violations, "integrity_percent": (0 if audited == 0 else int(100 * (audited - violations) / audited))}

    async def validate_chaos(self, session: AsyncSession, *, parallel: int = 1) -> ValidationResult:
        run_svc = ValidationRunService(session=session, celery=self.celery)
        run_id = await run_svc.create_run(
            run_kind="validate_chaos",
            scenario="test_portal",
            config={"parallel": parallel},
        )
        def _chaos(scenario: str) -> PortalSmokePayload:
            return PortalSmokePayload(
                start_path="/login",
                chaos={"scenario": scenario, "at_step": 0, "seed": 1},
                actions=[],
            )

        cases = [
            ValidationCase("redirect_storm", ValidationSuites.chaos_redirect_loop(), "fail"),
            ValidationCase("modal_storm", ValidationSuites.chaos_modal_storm(), "ok"),
            ValidationCase("network_offline", _chaos("network_offline"), "fail"),
            ValidationCase("playwright_disconnect", _chaos("playwright_disconnect"), "fail"),
            ValidationCase("chromium_crash", _chaos("chromium_crash"), "fail"),
            ValidationCase("page_freeze", _chaos("page_freeze"), "ok"),
            ValidationCase("memory_pressure", _chaos("memory_pressure"), "ok"),
            ValidationCase("download_corrupt", PortalSmokePayload(start_path="/download-corrupt", chaos={"scenario": "download_corrupt", "at_step": 0, "seed": 0}, actions=[]), "ok"),
        ]
        job_ids: list[uuid.UUID] = []
        expected: dict[str, str] = {}
        for c in cases:
            for _ in range(parallel):
                jid = await run_svc.enqueue_portal_smoke(run_id=run_id, payload=c.payload, actor="validate_chaos")
                job_ids.append(jid)
                expected[str(jid)] = c.expected
        await session.commit()
        wait = await ValidationExecutor().wait_for_jobs(session, job_ids=job_ids, timeout_seconds=900)
        replay = ReplayIntegrityValidator(settings=self.settings)
        replay_violations = 0
        for jid in job_ids:
            results = await replay.validate_job(session, job_id=jid)
            if any(r.status != "ok" for r in results):
                replay_violations += 1
        cleanup = await CleanupInvariantScanner(settings=self.settings).scan(session, run_id=run_id)
        assertions = await ExecutionAssertionEngine().run_for_jobs(session, job_ids=job_ids)
        score = await StabilityScoreService().compute(session, scope="run", scope_id=run_id, window_minutes=60)
        res = await session.execute(select(Job.id, Job.state).where(Job.id.in_(job_ids)))
        mismatches: list[dict[str, object]] = []
        for jid, state in res.all():
            exp = expected.get(str(jid), "ok")
            ok_state = (state == "completed") if exp == "ok" else (state in {"failed", "dead_letter"})
            if not ok_state:
                mismatches.append({"job_id": str(jid), "expected": exp, "state": state})
        ok = not wait.still_running and not mismatches and assertions.ok and cleanup.status == "ok"
        summary = {
            "completed": len(wait.completed),
            "failed": len(wait.failed),
            "still_running": [str(x) for x in wait.still_running],
            "expected_mismatches": mismatches,
            "cleanup_status": cleanup.status,
            "assertions_ok": assertions.ok,
            "replay_violations_jobs": replay_violations,
            "stability_score": score.score,
        }
        await session.execute(
            ValidationRun.__table__.update()
            .where(ValidationRun.id == run_id)
            .values(summary_json=json.dumps(summary, sort_keys=True, separators=(",", ":")), status="finished", ended_at=datetime.now(UTC))
        )
        await session.commit()
        return ValidationResult(run_id=run_id, ok=ok, summary=summary)

    async def validate_soak(
        self,
        session: AsyncSession,
        *,
        duration_seconds: int,
        rate_per_minute: int = 2,
        chaos_percent: int = 10,
    ) -> dict[str, object]:
        engine = SoakCampaignEngine(settings=self.settings, celery=self.celery)
        cid = await engine.start_campaign(
            session,
            cfg=SoakCampaignConfig(
                duration_seconds=duration_seconds,
                rate_per_minute=rate_per_minute,
                chaos_percent=chaos_percent,
            ),
        )
        await session.commit()
        # Run loop in-process for empirical proving; jobs still execute on workers.
        await engine.run_campaign_loop(session, campaign_id=cid)
        await session.commit()
        return {"campaign_id": str(cid), "duration_seconds": duration_seconds, "rate_per_minute": rate_per_minute, "chaos_percent": chaos_percent}

    async def validate_recovery(self, session: AsyncSession) -> dict[str, object]:
        # Recovery probe: enqueue a retryable timeout (Playwright TimeoutError is mapped to time_budget_exceeded).
        run_svc = ValidationRunService(session=session, celery=self.celery)
        run_id = await run_svc.create_run(
            run_kind="validate_recovery",
            scenario="timeout_retry",
            config={},
        )
        payload = PortalSmokePayload(
            start_path="/slow",
            chaos={"scenario": "navigation_timeout", "at_step": 0, "seed": 0},
            actions=[],
        )
        jid = await run_svc.enqueue_portal_smoke(run_id=run_id, payload=payload, actor="validate_recovery")
        await session.commit()

        # Wait a short time for state to become retrying (or dead_letter if policy changes).
        wait = await ValidationExecutor().wait_for_jobs(session, job_ids=[jid], timeout_seconds=120, poll_seconds=2.0)
        job_res = await session.execute(select(Job.state).where(Job.id == jid))
        state = job_res.scalar() or "unknown"
        cleanup = await CleanupInvariantScanner(settings=self.settings).scan(session, run_id=run_id)
        await session.commit()
        return {"run_id": str(run_id), "job_id": str(jid), "state": state, "cleanup_status": cleanup.status, "completed": [str(x) for x in wait.completed], "failed": [str(x) for x in wait.failed], "still_running": [str(x) for x in wait.still_running]}
