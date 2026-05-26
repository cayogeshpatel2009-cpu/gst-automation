from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
import time

import redis
import uvicorn

from gst_automation.celery_app.client import get_celery
from gst_automation.core.settings import Settings
from gst_automation.db.session import Db
from gst_automation.validation.browser_health import BrowserHealthService
from gst_automation.validation.cleanup_invariants import CleanupInvariantScanner
from gst_automation.validation.replay_integrity import ReplayIntegrityValidator
from gst_automation.validation.retention import RetentionService
from gst_automation.validation.run_service import ValidationRunService
from gst_automation.validation.suites import ValidationSuites
from gst_automation.validation.timeline import TimelineService
from gst_automation.db.models.validation.validation_run import ValidationRunJob
from sqlalchemy import select
from gst_automation.stability.soak_campaign import SoakCampaignConfig, SoakCampaignEngine
from gst_automation.stability.scoring_service import StabilityScoreService
from gst_automation.stability.replay_diff import ReplayDiffEngine
from gst_automation.stability.readiness import ReadinessGateService
from gst_automation.stability.certification import CertificationService
from gst_automation.validation.validate_runner import SimulationValidationRunner
from gst_automation.orchestration.dto import JobCreate, JobPriority
from gst_automation.orchestration.services.orchestrator_service import OrchestratorService
from gst_automation.validation.dto import RealSiteSmokePayload
from gst_automation.gst.dto import GstSafeProbePayload
from gst_automation.gst.dto import GstAuthSessionPayload
from gst_automation.gst.observation import GstObservationPayload
from gst_automation.gst.assisted_gstr2b import AssistedGstr2bPayload
from gst_automation.clients.excel_template import ClientMasterTemplate
from gst_automation.clients.import_pipeline import ClientImportPipeline
from gst_automation.clients.readiness import build_readiness_report
from gst_automation.gst.batch import Gstr2bBatchRequest, Gstr2bBatchService
from gst_automation.email.reliability import EmailReliabilityService
from gst_automation.gst.proving_runner import RealExecutionProver
from gst_automation.gst.reliability import SelectorReliabilityService, SessionReliabilityService
from gst_automation.gst.overnight import OvernightScheduler
from gst_automation.gst.stability_gates import ProductionReadinessGate
from gst_automation.validation.doctor import doctor_db, doctor_env, doctor_schema
from gst_automation.validation.telegram_verify import TelegramRoundTripVerifier
from gst_automation.validation.telegram_ping import TelegramPingValidator
from gst_automation.core.exceptions import ConfigurationError
from gst_automation.portal.sessions import SessionManager
from gst_automation.db.models.portal.session_blob import PortalSessionBlob
from gst_automation.db.models.portal.selector_def import PortalSelectorDef
from sqlalchemy import desc, select


def _json(obj: object) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))


def _print_step(name: str, ok: bool, *, details: str | None = None, hint: str | None = None) -> None:
    tag = "OK" if ok else "FAIL"
    print(f"[{tag}] {name}")
    if details:
        print(f"  {details}")
    if hint:
        print(f"  hint: {hint}")


def _docker_available() -> tuple[bool, str | None, str | None]:
    exe = shutil.which("docker")
    if not exe:
        return False, None, "docker not found on PATH"
    try:
        proc = subprocess.run(
            [exe, "info"],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return False, exe, str(exc)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        return False, exe, msg or f"docker info failed (exit {proc.returncode})"
    return True, exe, None


def _redis_ping(url: str) -> tuple[bool, str | None]:
    try:
        r = redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        res = r.ping()
        return bool(res), None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


async def _fastapi_import_and_lifespan_check() -> tuple[bool, str | None]:
    try:
        from gst_automation.app.main import build_app
        from gst_automation.app.lifespan import lifespan as _lifespan

        app = build_app()
        agen = _lifespan(app)
        await agen.__anext__()
        await agen.aclose()
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _celery_import_check() -> tuple[bool, str | None]:
    try:
        from gst_automation.cli.worker import celery_app  # noqa: F401

        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _pytest_collect_check() -> tuple[bool, str | None]:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip()
            return False, msg or f"pytest collect failed (exit {proc.returncode})"
        # Treat collection warnings as non-fatal; include them as details.
        warnings = proc.stderr.strip() if proc.stderr else ""
        return True, warnings or None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


async def _cmd_full_check(args: argparse.Namespace) -> None:
    settings = Settings.load()
    ok_all = True
    results: dict[str, object] = {}

    # 1) env loading
    env_rep = doctor_env(settings)
    env_ok = bool(env_rep.env_file_detected and env_rep.database_url_loaded and env_rep.migration_url_loaded)
    ok_all = ok_all and env_ok
    _print_step(
        "env loading",
        env_ok,
        details=f"env_file={env_rep.resolved_env_path} database_url_loaded={env_rep.database_url_loaded} migration_url_loaded={env_rep.migration_url_loaded}",
        hint="Check .env / DATABASE_URL / DATABASE_MIGRATION_URL" if not env_ok else None,
    )
    results["env"] = asdict(env_rep)

    # 2) docker availability (best-effort, no compose side effects)
    if not args.skip_docker:
        d_ok, d_exe, d_err = _docker_available()
        ok_all = ok_all and d_ok
        _print_step(
            "docker availability",
            d_ok,
            details=f"docker_exe={d_exe}" if d_exe else None,
            hint=d_err if not d_ok else None,
        )
        results["docker"] = {"ok": d_ok, "docker_exe": d_exe, "error": d_err}

    # 3) postgres + migration url connectivity
    db_rep = await doctor_db(settings)
    db_ok = bool(db_rep.database_url_ok and db_rep.asyncpg_reachable and db_rep.asyncpg_auth_ok)
    mig_ok = bool(db_rep.migration_url_ok and db_rep.migration_reachable and db_rep.migration_auth_ok)
    ok_all = ok_all and db_ok and mig_ok
    _print_step(
        "postgres connectivity (asyncpg)",
        db_ok,
        details=db_rep.database_url_target,
        hint=db_rep.asyncpg_error if not db_ok else None,
    )
    _print_step(
        "postgres connectivity (migrations)",
        mig_ok,
        details=db_rep.migration_url_target,
        hint=db_rep.migration_error if not mig_ok else None,
    )
    results["doctor_db"] = asdict(db_rep)

    # 4) redis connectivity
    redis_ok, redis_err = _redis_ping(settings.redis_url)
    ok_all = ok_all and redis_ok
    _print_step(
        "redis connectivity",
        redis_ok,
        details=settings.redis_url,
        hint=redis_err if not redis_ok else None,
    )
    results["redis"] = {"ok": redis_ok, "url": settings.redis_url, "error": redis_err}

    # 5) alembic revision + required tables
    schema_rep = doctor_schema(settings)
    schema_ok = bool(schema_rep.ok)
    ok_all = ok_all and schema_ok
    _print_step(
        "alembic alignment + required tables",
        schema_ok,
        details=f"db_rev={schema_rep.db_revision} head={schema_rep.head_revision} missing={schema_rep.required_tables_missing}",
        hint=schema_rep.error if not schema_ok else None,
    )
    results["doctor_schema"] = asdict(schema_rep)

    # 6) FastAPI import + lifespan startup/shutdown
    api_ok, api_err = await _fastapi_import_and_lifespan_check()
    ok_all = ok_all and api_ok
    _print_step("fastapi import + lifespan", api_ok, hint=api_err if not api_ok else None)
    results["fastapi"] = {"ok": api_ok, "error": api_err}

    # 7) Celery worker import safety
    c_ok, c_err = _celery_import_check()
    ok_all = ok_all and c_ok
    _print_step("celery import", c_ok, hint=c_err if not c_ok else None)
    results["celery"] = {"ok": c_ok, "error": c_err}

    # 8) onboarding parser + client-master validate
    xlsx_path = Path(args.client_master)
    if not xlsx_path.is_file():
        ok_all = False
        _print_step(
            "client-master validate",
            False,
            details=str(xlsx_path),
            hint="Missing workbook. Generate template: python -m gst_automation.validation client-master template",
        )
        results["client_master"] = {"ok": False, "path": str(xlsx_path), "error": "missing file"}
    else:
        db = Db(settings.database_url)
        try:
            async with db.session() as session:
                rep = await ClientImportPipeline(settings=settings).import_xlsx(session, path=xlsx_path, dry_run=True)
                cm_ok = bool(rep.ok)
                ok_all = ok_all and cm_ok
                _print_step(
                    "client-master validate",
                    cm_ok,
                    details=f"path={xlsx_path} would_create={rep.summary.get('would_create')} would_update={rep.summary.get('would_update')}",
                    hint=str(rep.row_errors[:1]) if not cm_ok else None,
                )
                results["client_master"] = {"ok": cm_ok, "path": str(xlsx_path), "summary": rep.summary, "row_errors": rep.row_errors}
        except Exception as exc:  # noqa: BLE001
            ok_all = False
            _print_step("client-master validate", False, details=str(xlsx_path), hint=str(exc))
            results["client_master"] = {"ok": False, "path": str(xlsx_path), "error": str(exc)}
        finally:
            await db.close()

    # 9) pytest collection
    p_ok, p_details = _pytest_collect_check()
    ok_all = ok_all and p_ok
    _print_step(
        "pytest collection",
        p_ok,
        details="warnings present" if (p_ok and p_details) else None,
        hint=p_details if (not p_ok) else None,
    )
    results["pytest_collect"] = {"ok": p_ok, "details": p_details}

    _json({"ok": ok_all, "results": results})
    raise SystemExit(0 if ok_all else 2)


async def _cmd_smoke_runtime(args: argparse.Namespace) -> None:
    settings = Settings.load()
    ok_all = True
    results: dict[str, object] = {}

    # Boot minimal API runtime and ping health endpoints, then shut down cleanly.
    app = __import__("gst_automation.app.main", fromlist=["build_app"]).build_app()
    config = uvicorn.Config(
        app,
        host=args.host,
        port=int(args.port),
        log_config=None,
        lifespan="on",
    )
    server = uvicorn.Server(config)

    async def _run_server() -> None:
        await server.serve()

    task = asyncio.create_task(_run_server())

    import httpx

    try:
        base = f"http://{args.host}:{int(args.port)}"
        async with httpx.AsyncClient(timeout=3.0) as client:
            up = False
            for _ in range(30):
                try:
                    r = await client.get(f"{base}/health/live")
                    if r.status_code == 200:
                        up = True
                        break
                except Exception:
                    await asyncio.sleep(1)
            _print_step("api boot", up, details=base, hint="API did not become ready" if not up else None)
            results["api_boot"] = {"ok": up, "base": base}
            ok_all = ok_all and up

            if up:
                r2 = await client.get(f"{base}/health/ready")
                ready_ok = (r2.status_code == 200)
                _print_step("api /health/ready", ready_ok, hint=r2.text if not ready_ok else None)
                results["api_health_ready"] = {"ok": ready_ok, "status": r2.status_code, "body": r2.text}
                ok_all = ok_all and ready_ok
    finally:
        server.should_exit = True
        await task

    # Out-of-band direct Redis ping (no API coupling).
    redis_ok, redis_err = _redis_ping(settings.redis_url)
    ok_all = ok_all and redis_ok
    _print_step("redis ping", redis_ok, details=settings.redis_url, hint=redis_err if not redis_ok else None)
    results["redis"] = {"ok": redis_ok, "url": settings.redis_url, "error": redis_err}

    _json({"ok": ok_all, "results": results})
    raise SystemExit(0 if ok_all else 2)


async def _cmd_gst_session_audit(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    now = datetime.now(UTC)
    ok_all = True
    out: dict[str, object] = {"ok": True, "checked": []}

    async with db.session() as session:
        client_id = uuid.UUID(args.client_id) if args.client_id else None
        profile = args.profile
        res = await session.execute(
            select(PortalSessionBlob)
            .where(PortalSessionBlob.client_id == client_id)
            .where(PortalSessionBlob.profile == profile)
            .order_by(desc(PortalSessionBlob.created_at))
            .limit(1)
        )
        blob = res.scalars().first()
        if blob is None:
            ok_all = False
            _print_step(
                "gst session exists",
                False,
                details=f"client_id={args.client_id or 'None'} profile={profile}",
                hint="Acquire session via supervised flow: python -m gst_automation.validation gst-auth ...",
            )
            out["checked"].append({"name": "session_exists", "ok": False})
        else:
            expired = bool(blob.expires_at and blob.expires_at <= now)
            _print_step(
                "gst session expiry",
                not expired,
                details=f"expires_at={blob.expires_at.isoformat() if blob.expires_at else None}",
                hint="Session expired; run supervised auth refresh" if expired else None,
            )
            ok_all = ok_all and (not expired)
            out["checked"].append({"name": "session_expiry", "ok": (not expired), "expires_at": blob.expires_at.isoformat() if blob.expires_at else None})

            # Decrypt + basic shape check
            try:
                state = await SessionManager(settings=settings).load_latest_storage_state(
                    session, client_id=client_id, profile=profile
                )
                shape_ok = bool(state and isinstance(state, dict) and ("cookies" in state or "origins" in state))
                _print_step(
                    "gst session decrypt/shape",
                    shape_ok,
                    hint="Decrypted session missing expected fields (cookies/origins)" if not shape_ok else None,
                )
                ok_all = ok_all and shape_ok
                out["checked"].append({"name": "session_decrypt_shape", "ok": shape_ok})
            except Exception as exc:  # noqa: BLE001
                ok_all = False
                _print_step("gst session decrypt/shape", False, hint=str(exc))
                out["checked"].append({"name": "session_decrypt_shape", "ok": False, "error": str(exc)})

    await db.close()
    out["ok"] = ok_all
    _json(out)
    raise SystemExit(0 if ok_all else 2)


async def _cmd_gstr2b_selector_audit(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    ok_all = True
    required: list[str] = [
        "gst.nav.returns",
        "gst.nav.gstr2b",
        "gst.gstr2b.fy_dropdown",
        "gst.gstr2b.period_dropdown",
        "gst.gstr2b.generate",
        "gst.gstr2b.download_excel",
        f"gst.gstr2b.fy_option.{args.financial_year}",
        f"gst.gstr2b.period_option.{args.period}",
    ]

    async with db.session() as session:
        res = await session.execute(select(PortalSelectorDef.key).where(PortalSelectorDef.active == 1))
        active = {str(k) for k in res.scalars().all()}
    await db.close()

    missing = [k for k in required if k not in active]
    for k in required:
        _print_step(f"selector {k}", (k in active), hint="Promote selectors from observation before real runs" if (k in missing) else None)
    ok_all = ok_all and (len(missing) == 0)
    _json({"ok": ok_all, "missing": missing, "required": required})
    raise SystemExit(0 if ok_all else 2)


def _print_db_error(err: BaseException) -> None:
    print("[DB ERROR]")
    print("Unable to authenticate with PostgreSQL.")
    print("Check:")
    print("- POSTGRES_PASSWORD")
    print("- DATABASE_URL / DATABASE_MIGRATION_URL")
    print("- docker compose postgres env vars")
    print(f"Details: {err}")


async def _cmd_run(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    celery = get_celery()
    async with db.session() as session:
        svc = ValidationRunService(session=session, celery=celery)

        run_id = await svc.create_run(
            run_kind=args.scenario,
            scenario=args.profile or "default",
            config={
                "requested_at": datetime.now(UTC).isoformat(),
                "parallel": args.parallel,
                "duration_seconds": args.duration_seconds,
                "rate_per_minute": args.rate_per_minute,
                "total_jobs": args.total_jobs,
            },
        )
        job_ids: list[str] = []

        if args.scenario in {"smoke", "chaos"}:
            if args.scenario == "smoke":
                payload = ValidationSuites.basic_smoke()
            else:
                profile = (args.profile or "redirect").lower()
                payload = {
                    "redirect": ValidationSuites.chaos_redirect_loop(),
                    "modal": ValidationSuites.chaos_modal_storm(),
                    "selector_drift": ValidationSuites.selector_drift(),
                }.get(profile, ValidationSuites.chaos_redirect_loop())
            for _ in range(int(args.parallel)):
                job_id = await svc.enqueue_portal_smoke(run_id=run_id, payload=payload)
                job_ids.append(str(job_id))

        elif args.scenario == "stress":
            payload = ValidationSuites.basic_smoke()
            total = int(args.total_jobs or max(1, int(args.parallel)))
            for _ in range(total):
                job_id = await svc.enqueue_portal_smoke(run_id=run_id, payload=payload)
                job_ids.append(str(job_id))

        elif args.scenario == "soak":
            duration = int(args.duration_seconds or 6 * 3600)
            rate = float(args.rate_per_minute or 2.0)
            payload_smoke = ValidationSuites.basic_smoke()
            payload_chaos = ValidationSuites.chaos_redirect_loop()
            start = datetime.now(UTC)
            i = 0
            while int((datetime.now(UTC) - start).total_seconds()) < duration:
                # Deterministic mix: every 10th job uses chaos payload.
                payload = payload_chaos if (i % 10 == 0) else payload_smoke
                job_id = await svc.enqueue_portal_smoke(run_id=run_id, payload=payload)
                job_ids.append(str(job_id))
                i += 1
                await session.commit()
                sleep_s = max(1.0, 60.0 / max(rate, 0.1))
                await asyncio.sleep(sleep_s)

        else:
            raise SystemExit(f"unknown scenario: {args.scenario}")
        await session.commit()

    await db.close()
    _json({"run_id": str(run_id), "job_ids": job_ids})


async def _cmd_real_site(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    celery = get_celery()
    payload = (
        ValidationSuites.real_site_example_com()
        if args.target == "example"
        else RealSiteSmokePayload(start_url=args.url, actions=[])
    )
    async with db.session() as session:
        orch = OrchestratorService(session=session, celery=celery)
        job_id = await orch.create_and_enqueue(
            JobCreate(kind="real_site_smoke", queue="downloads", priority=JobPriority.P4_MONITORING, payload=payload.model_dump()),
            actor="validation_cli",
        )
        await session.commit()
    await db.close()
    _json({"job_id": str(job_id), "start_url": payload.start_url})


async def _cmd_gst_probe(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    celery = get_celery()
    start_url = args.url or settings.gst_probe_base_url
    if not start_url:
        raise SystemExit("GST_PROBE_BASE_URL not set and --url not provided")
    payload = GstSafeProbePayload(start_url=start_url, steps=[])
    async with db.session() as session:
        orch = OrchestratorService(session=session, celery=celery)
        job_id = await orch.create_and_enqueue(
            JobCreate(kind="gst_safe_probe", queue="downloads", priority=JobPriority.P4_MONITORING, payload=payload.model_dump()),
            actor="validation_cli",
        )
        await session.commit()
    await db.close()
    _json({"job_id": str(job_id), "start_url": start_url})


async def _cmd_gst_auth(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    celery = get_celery()
    start_url = args.url or settings.gst_probe_base_url
    if not start_url:
        raise SystemExit("GST_PROBE_BASE_URL not set and --url not provided")
    payload = GstAuthSessionPayload(
        start_url=start_url,
        gstin=args.gstin,
        client_id=args.client_id,
        profile="gst",
        ttl_days=int(args.ttl_days),
        checkpoint_timeout_seconds=int(args.timeout_seconds),
    )
    async with db.session() as session:
        orch = OrchestratorService(session=session, celery=celery)
        job_id = await orch.create_and_enqueue(
            JobCreate(kind="gst_auth_session", queue="downloads", priority=JobPriority.P1_OPERATOR, payload=payload.model_dump()),
            actor="validation_cli",
        )
        await session.commit()
    await db.close()
    _json({"job_id": str(job_id), "start_url": start_url, "gstin": args.gstin})


async def _cmd_gst_observe(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    celery = get_celery()
    start_url = args.url or settings.gst_probe_base_url
    if not start_url:
        raise SystemExit("GST_PROBE_BASE_URL not set and --url not provided")
    payload = GstObservationPayload(
        start_url=start_url,
        checkpoint_timeout_seconds=int(args.timeout_seconds),
        notes=args.notes or "",
    )
    async with db.session() as session:
        orch = OrchestratorService(session=session, celery=celery)
        job_id = await orch.create_and_enqueue(
            JobCreate(
                kind="gst_observation_session",
                queue="downloads",
                priority=JobPriority.P1_OPERATOR,
                payload=asdict(payload),
            ),
            actor="validation_cli",
        )
        await session.commit()
    await db.close()
    _json({"job_id": str(job_id), "start_url": start_url})


def _open_file_best_effort(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
            return
    except Exception:
        pass
    try:
        subprocess.run(["xdg-open", str(path)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _cmd_captcha_watch(args: argparse.Namespace) -> None:
    """Operator-friendly watcher for deterministic CAPTCHA artifacts produced by gst-auth."""
    settings = Settings.load()
    captcha_path = Path(settings.data_dir) / "current_captcha.png"
    page_path = Path(settings.data_dir) / "current_auth_page.png"
    state_path = Path(settings.data_dir) / "captcha_state.json"

    last_mtime: float | None = None
    refreshes = 0
    failures = 0
    last_status: str | None = None

    print(f"[watch] captcha={captcha_path}")
    print(f"[watch] page={page_path}")
    print(f"[watch] state={state_path}")
    print("[watch] Ctrl+C to stop.")

    while True:
        try:
            if state_path.exists():
                try:
                    obj = json.loads(state_path.read_text(encoding="utf-8"))
                    refreshes = int(obj.get("refresh_count") or 0)
                    failures = int(obj.get("failure_count") or 0)
                    last_status = str(obj.get("status") or "")
                except Exception:
                    pass

            if captcha_path.exists():
                mtime = captcha_path.stat().st_mtime
                if last_mtime is None or mtime != last_mtime:
                    last_mtime = mtime
                    ts = datetime.now().strftime("%H:%M:%S")
                    print(f"[captcha] updated {ts} status={last_status} refreshes={refreshes} failures={failures}")
                    if not args.no_open:
                        _open_file_best_effort(captcha_path)
            time.sleep(float(args.interval_seconds))
        except KeyboardInterrupt:
            raise SystemExit(0) from None


async def _cmd_assisted_gstr2b(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    celery = get_celery()
    payload = AssistedGstr2bPayload(
        client_id=args.client_id,
        profile="gst",
        start_url=args.url or settings.gst_probe_base_url or "",
        checkpoint_timeout_seconds=int(args.timeout_seconds),
    )
    async with db.session() as session:
        orch = OrchestratorService(session=session, celery=celery)
        job_id = await orch.create_and_enqueue(
            JobCreate(
                kind="assisted_gstr2b_execution",
                queue="downloads",
                priority=JobPriority.P1_OPERATOR,
                payload=json.loads(json.dumps(payload.__dict__)),
            ),
            actor="validation_cli",
        )
        await session.commit()
    await db.close()
    _json({"job_id": str(job_id)})


async def _cmd_client_template(args: argparse.Namespace) -> None:
    path = Path(args.path)
    ClientMasterTemplate(path=path).write()
    _json({"ok": True, "path": str(path)})


async def _cmd_client_import(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    async with db.session() as session:
        rep = await ClientImportPipeline(settings=settings).import_xlsx(
            session, path=Path(args.path), dry_run=bool(args.dry_run)
        )
        if rep.ok and not args.dry_run:
            await session.commit()
        _json(
            {
                "ok": rep.ok,
                "created": rep.created,
                "updated": rep.updated,
                "row_errors": rep.row_errors,
                "summary": rep.summary,
                "preview": rep.preview,
            }
        )
    await db.close()


async def _cmd_gstr2b_batch(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    celery = get_celery()
    async with db.session() as session:
        svc = Gstr2bBatchService(session=session, celery=celery)
        res = await svc.enqueue_for_active_clients(
            Gstr2bBatchRequest(financial_year=args.financial_year, period_yyyy_mm=args.period),
            actor="gstr2b_batch",
        )
        await session.commit()
        _json({"enqueued": res.enqueued, "job_ids": [str(x) for x in res.job_ids]})
    await db.close()


async def _cmd_client_validate(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    async with db.session() as session:
        rep = await ClientImportPipeline(settings=settings).import_xlsx(session, path=Path(args.path), dry_run=True)
        _json({"ok": rep.ok, "row_errors": rep.row_errors, "summary": rep.summary, "preview": rep.preview})
    await db.close()


async def _cmd_onboarding_status(_args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    async with db.session() as session:
        rep = await build_readiness_report(session, settings=settings)
        _json(rep.to_dict())
    await db.close()


async def _cmd_execution_readiness(_args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    async with db.session() as session:
        rep = await build_readiness_report(session, settings=settings)
        _json(rep.to_dict())
    await db.close()

async def _cmd_telegram_verify(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    async with db.session() as session:
        res = await TelegramRoundTripVerifier(settings=settings, session=session).run(
            timeout_seconds=int(args.timeout_seconds),
            debug=bool(args.debug),
        )
        _json(res)
        await session.commit()
    await db.close()


async def _cmd_telegram_ping(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    async with db.session() as session:
        res = await TelegramPingValidator(settings=settings, session=session).run(timeout_seconds=int(args.timeout_seconds))
        _json(res)
        await session.commit()
    await db.close()


async def _cmd_prove_one(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    celery = get_celery()
    async with db.session() as session:
        prover = RealExecutionProver(settings=settings, session=session, celery=celery)
        res = await prover.run_one(
            client_id=uuid.UUID(args.client_id),
            financial_year=args.financial_year,
            period_yyyy_mm=args.period,
            timeout_seconds=int(args.timeout_seconds),
            require_email_sent=bool(args.require_email_sent),
        )
        _json(
            {
                "ok": res.ok,
                "job_id": str(res.job_id),
                "job_state": res.job_state,
                "execution_report_id": str(res.execution_report_id) if res.execution_report_id else None,
                "execution_status": res.execution_status,
                "score": res.score,
                "report": res.report,
                "forensics_relpath": res.forensics_relpath,
            }
        )
        await session.commit()
    await db.close()


async def _cmd_prove_batch(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    celery = get_celery()
    async with db.session() as session:
        # Enqueue for all active clients; operator can cap by running on a filtered client master if needed.
        svc = Gstr2bBatchService(session=session, celery=celery)
        res = await svc.enqueue_for_active_clients(
            Gstr2bBatchRequest(financial_year=args.financial_year, period_yyyy_mm=args.period),
            actor="prove_batch",
        )
        await session.commit()
        _json({"enqueued": res.enqueued, "job_ids": [str(x) for x in res.job_ids]})
    await db.close()


async def _cmd_reliability_snapshot(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    async with db.session() as session:
        selectors = await SelectorReliabilityService().snapshot(session, lookback_minutes=int(args.lookback_minutes))
        sessions = await SessionReliabilityService().snapshot(session, lookback_minutes=int(args.lookback_minutes))
        _json(
            {
                "selectors": [
                    {
                        "selector_key": r.selector_key,
                        "samples": r.samples,
                        "fallback_rate": r.fallback_rate,
                        "fail_rate": r.fail_rate,
                        "p95_latency_ms": r.p95_latency_ms,
                        "score": r.score,
                    }
                    for r in selectors
                ],
                "sessions": sessions,
            }
        )
        await session.commit()
    await db.close()


async def _cmd_overnight_tick(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    celery = get_celery()
    async with db.session() as session:
        res = await OvernightScheduler(settings=settings, session=session, celery=celery).tick(
            financial_year=args.financial_year,
            period_yyyy_mm=args.period,
        )
        await session.commit()
        _json(
            {
                "window_open": res.window_open,
                "enqueued": res.enqueued,
                "skipped_already_ok": res.skipped_already_ok,
                "errors": res.errors,
                "job_ids": res.job_ids,
            }
        )
    await db.close()


async def _cmd_production_gates(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    async with db.session() as session:
        res = await ProductionReadinessGate().evaluate(session, lookback_hours=int(args.lookback_hours))
        await session.commit()
        _json({"ok": res.ok, "score": res.score, "details": res.details})
    await db.close()


async def _cmd_doctor_db(_args: argparse.Namespace) -> None:
    settings = Settings.load()
    rep = await doctor_db(settings)
    _json(
        {
            "database_url": {
                "ok": rep.database_url_ok,
                "target": rep.database_url_target,
                "error": rep.database_url_error,
            },
            "asyncpg": {
                "reachable": rep.asyncpg_reachable,
                "auth_ok": rep.asyncpg_auth_ok,
                "error": rep.asyncpg_error,
                "server_info": rep.server_info,
            },
            "migration_url": {
                "ok": rep.migration_url_ok,
                "target": rep.migration_url_target,
                "error": rep.migration_url_error,
            },
            "migration": {
                "reachable": rep.migration_reachable,
                "auth_ok": rep.migration_auth_ok,
                "error": rep.migration_error,
            },
        }
    )


async def _cmd_doctor_schema(_args: argparse.Namespace) -> None:
    settings = Settings.load()
    rep = doctor_schema(settings)
    _json(
        {
            "ok": rep.ok,
            "head_revision": rep.head_revision,
            "db_revision": rep.db_revision,
            "required_tables_missing": rep.required_tables_missing,
            "tables": rep.tables[:200],
            "error": rep.error,
            "hint": "Run: python -m gst_automation.cli.db upgrade" if (not rep.ok) else None,
        }
    )


async def _cmd_doctor_env(_args: argparse.Namespace) -> None:
    settings = Settings.load()
    rep = doctor_env(settings)
    _json(
        {
            "env_file_detected": rep.env_file_detected,
            "database_url_loaded": rep.database_url_loaded,
            "migration_url_loaded": rep.migration_url_loaded,
            "resolved_env_path": rep.resolved_env_path,
            "cwd": rep.cwd,
        }
    )


async def _cmd_replay(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    async with db.session() as session:
        ts = TimelineService(settings=settings)
        uid = uuid.UUID(args.run_or_job_id)
        res = await session.execute(select(ValidationRunJob.job_id).where(ValidationRunJob.run_id == uid))
        job_ids = [r[0] for r in res.all()]
        if not job_ids:
            # Treat as direct job_id.
            events = await ts.build_for_job(session, job_id=uid)
            _json([{"ts_ms": e.ts_ms, "kind": e.kind, "details": e.details} for e in events])
        else:
            out: dict[str, object] = {"run_id": str(uid), "jobs": {}}
            for jid in job_ids[: int(args.limit_jobs)]:
                events = await ts.build_for_job(session, job_id=jid)
                out["jobs"][str(jid)] = [{"ts_ms": e.ts_ms, "kind": e.kind} for e in events[-200:]]
            _json(out)
    await db.close()


async def _cmd_cleanup_audit(_args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    async with db.session() as session:
        report = await CleanupInvariantScanner(settings=settings).scan(session)
        await session.commit()
        _json({"status": report.status, "findings": report.findings})
    await db.close()


async def _cmd_browser_health(_args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    async with db.session() as session:
        rows = await BrowserHealthService().snapshot(session)
        await session.commit()
        _json([{"browser_id": str(r.browser_id), "score": r.score, "details": r.details} for r in rows])
    await db.close()


async def _cmd_retention_audit(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    async with db.session() as session:
        res = await RetentionService(settings=settings).enforce(session, dry_run=not args.execute)
        await session.commit()
        _json({"dry_run": (not args.execute), "deleted": res.deleted, "kept": res.kept, "errors": res.errors})
    await db.close()


async def _cmd_email_reconcile(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    celery = get_celery()
    async with db.session() as session:
        enq = await EmailReliabilityService().reconcile_failed(
            session,
            celery=celery,
            min_age_minutes=int(args.min_age_minutes),
            limit=int(args.limit),
        )
        await session.commit()
        _json({"enqueued": int(enq)})
    await db.close()


async def _cmd_replay_integrity(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    async with db.session() as session:
        validator = ReplayIntegrityValidator(settings=settings)
        results = await validator.validate_job(session, job_id=uuid.UUID(args.job_id))
        await session.commit()
        _json([{"status": r.status, "issues": r.issues} for r in results])
    await db.close()


async def _cmd_campaign_start(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    celery = get_celery()
    async with db.session() as session:
        engine = SoakCampaignEngine(settings=settings, celery=celery)
        cid = await engine.start_campaign(
            session,
            cfg=SoakCampaignConfig(
                duration_seconds=int(args.duration_seconds),
                rate_per_minute=int(args.rate_per_minute),
                chaos_percent=int(args.chaos_percent),
            ),
        )
        await session.commit()
        if args.run_loop:
            await engine.run_campaign_loop(session, campaign_id=cid)
            await session.commit()
    await db.close()
    _json({"campaign_id": str(cid)})


async def _cmd_score(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    async with db.session() as session:
        row = await StabilityScoreService().compute(session, window_minutes=int(args.window_minutes))
        await session.commit()
        _json({"id": str(row.id), "score": row.score, "created_at": row.created_at.isoformat()})
    await db.close()


async def _cmd_replay_diff(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    l = uuid.UUID(args.left_job_id)
    r = uuid.UUID(args.right_job_id)
    async with db.session() as session:
        engine = ReplayDiffEngine(settings=settings)
        res = await engine.diff_jobs(session, left_job_id=l, right_job_id=r)
        await engine.record_report(session, left_job_id=l, right_job_id=r, result=res)
        await session.commit()
        _json({"status": res.status, "diff": res.diff})
    await db.close()


async def _cmd_readiness(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    async with db.session() as session:
        row = await ReadinessGateService().evaluate(session)
        await session.commit()
        _json({"gate_name": row.gate_name, "status": row.status, "score": row.score, "report_json": row.report_json})
    await db.close()


async def _cmd_certify(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    async with db.session() as session:
        rows = await CertificationService(settings=settings).certify_job(session, job_id=uuid.UUID(args.job_id))
        await session.commit()
        _json([{"context_id": str(r.context_id), "status": r.status, "sha256": r.report_sha256_hex} for r in rows])
    await db.close()


async def _cmd_validate_smoke(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    celery = get_celery()
    async with db.session() as session:
        runner = SimulationValidationRunner(settings=settings, celery=celery)
        res = await runner.validate_smoke(session, parallel=int(args.parallel))
        gate = await runner.readiness_gate(session)
        _json({"ok": res.ok, "run_id": str(res.run_id), "summary": res.summary, "readiness": gate})
    await db.close()


async def _cmd_validate_chaos(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    celery = get_celery()
    async with db.session() as session:
        runner = SimulationValidationRunner(settings=settings, celery=celery)
        res = await runner.validate_chaos(session, parallel=int(args.parallel))
        _json({"ok": res.ok, "run_id": str(res.run_id), "summary": res.summary})
    await db.close()


async def _cmd_validate_soak(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    celery = get_celery()
    async with db.session() as session:
        runner = SimulationValidationRunner(settings=settings, celery=celery)
        res = await runner.validate_soak(
            session,
            duration_seconds=int(args.duration_seconds),
            rate_per_minute=int(args.rate_per_minute),
            chaos_percent=int(args.chaos_percent),
        )
        _json(res)
    await db.close()


async def _cmd_validate_replay(args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    celery = get_celery()
    async with db.session() as session:
        runner = SimulationValidationRunner(settings=settings, celery=celery)
        res = await runner.validate_replay(session, limit_jobs=int(args.limit_jobs))
        _json(res)
    await db.close()


async def _cmd_validate_recovery(_args: argparse.Namespace) -> None:
    settings = Settings.load()
    db = Db(settings.database_url)
    celery = get_celery()
    async with db.session() as session:
        runner = SimulationValidationRunner(settings=settings, celery=celery)
        res = await runner.validate_recovery(session)
        _json(res)
    await db.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gst_automation.validation", description="Operational validation runner CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="enqueue validation scenarios via orchestration")
    run.add_argument("scenario", choices=["smoke", "chaos", "soak", "stress"])
    run.add_argument("--parallel", type=int, default=1)
    run.add_argument("--profile", type=str, default=None)
    run.add_argument("--duration-seconds", type=int, default=None, help="soak duration (default 6h)")
    run.add_argument("--rate-per-minute", type=float, default=None, help="soak jobs/min (default 2)")
    run.add_argument("--total-jobs", type=int, default=None, help="stress total jobs to enqueue")
    run.set_defaults(func=_cmd_run)

    rs = sub.add_parser("real-site", help="enqueue a safe real-site smoke job (allowlist enforced)")
    rs.add_argument("--target", choices=["example"], default="example")
    rs.add_argument("--url", type=str, default="https://example.com")
    rs.set_defaults(func=_cmd_real_site)

    gp = sub.add_parser("gst-probe", help="enqueue GST-safe read-only probe (allowlist enforced via GST_PROBE_ALLOWLIST)")
    gp.add_argument("--url", type=str, default=None)
    gp.set_defaults(func=_cmd_gst_probe)

    ga = sub.add_parser("gst-auth", help="enqueue supervised GST auth session acquisition (HITL, no unattended auth)")
    ga.add_argument("--url", type=str, default=None)
    ga.add_argument("--gstin", type=str, default=None)
    ga.add_argument("--client-id", type=str, default=None)
    ga.add_argument("--ttl-days", type=int, default=7)
    ga.add_argument("--timeout-seconds", type=int, default=600)
    ga.set_defaults(func=_cmd_gst_auth)

    go = sub.add_parser("gst-observe", help="enqueue GST observation session (operator-driven, records full workflow)")
    go.add_argument("--url", type=str, default=None)
    go.add_argument("--timeout-seconds", type=int, default=7200)
    go.add_argument("--notes", type=str, default="")
    go.set_defaults(func=_cmd_gst_observe)

    cw = sub.add_parser("captcha-watch", help="watch current_captcha.png produced by gst-auth (operator helper)")
    cw.add_argument("--interval-seconds", type=float, default=1.0)
    cw.add_argument("--no-open", action="store_true", help="do not auto-open captcha image on update")
    cw.set_defaults(func=_cmd_captcha_watch)

    ag = sub.add_parser("assisted-gstr2b", help="enqueue assisted GSTR-2B execution (session required, HITL fallback)")
    ag.add_argument("--client-id", type=str, default=None)
    ag.add_argument("--url", type=str, default=None)
    ag.add_argument("--timeout-seconds", type=int, default=600)
    ag.set_defaults(func=_cmd_assisted_gstr2b)

    cm = sub.add_parser("client-master", help="client master XLSX operations")
    cm_sub = cm.add_subparsers(dest="client_cmd", required=True)
    tmpl = cm_sub.add_parser("template", help="generate client_master_template.xlsx template")
    tmpl.add_argument("--path", type=str, default="client_master_template.xlsx")
    tmpl.set_defaults(func=_cmd_client_template)
    imp = cm_sub.add_parser("import", help="import client_master.xlsx into DB/Vault")
    imp.add_argument("path", type=str, help="path to filled client master XLSX")
    imp.add_argument("--dry-run", action="store_true")
    imp.set_defaults(func=_cmd_client_import)
    val = cm_sub.add_parser("validate", help="validate client_master.xlsx (no DB writes)")
    val.add_argument("path", type=str, help="path to filled client master XLSX")
    val.set_defaults(func=_cmd_client_validate)

    ob = sub.add_parser("onboarding-status", help="report onboarding status for all clients")
    ob.set_defaults(func=_cmd_onboarding_status)

    ex = sub.add_parser("execution-readiness", help="report execution readiness for all clients")
    ex.set_defaults(func=_cmd_execution_readiness)

    tv = sub.add_parser("telegram-verify", help="verify Telegram bot connectivity (round-trip)")
    tv.add_argument("--timeout-seconds", dest="timeout_seconds", type=int, default=180)
    tv.add_argument("--debug", dest="debug", action="store_true", help="print raw updates while polling")
    tv.set_defaults(func=_cmd_telegram_verify)

    tp = sub.add_parser("telegram-ping", help="operator-driven Telegram /ping proof (requires polling running)")
    tp.add_argument("--timeout-seconds", dest="timeout_seconds", type=int, default=60)
    tp.set_defaults(func=_cmd_telegram_ping)

    prove = sub.add_parser("prove", help="real execution proving tools (requires workers running)")
    prove_sub = prove.add_subparsers(dest="prove_cmd", required=True)
    one = prove_sub.add_parser("gstr2b-one", help="run one real client end-to-end (unattended proving)")
    one.add_argument("--client-id", dest="client_id", required=True)
    one.add_argument("--financial-year", dest="financial_year", required=True)
    one.add_argument("--period", dest="period", required=True, help="YYYY-MM")
    one.add_argument("--timeout-seconds", dest="timeout_seconds", type=int, default=1800)
    one.add_argument("--require-email-sent", dest="require_email_sent", action="store_true")
    one.set_defaults(func=_cmd_prove_one)

    batch = prove_sub.add_parser("gstr2b-batch", help="enqueue batch for all active clients (prove mode)")
    batch.add_argument("--financial-year", dest="financial_year", required=True)
    batch.add_argument("--period", dest="period", required=True, help="YYYY-MM")
    batch.set_defaults(func=_cmd_prove_batch)

    rel = prove_sub.add_parser("reliability", help="snapshot selector/session reliability metrics")
    rel.add_argument("--lookback-minutes", dest="lookback_minutes", type=int, default=24 * 60)
    rel.set_defaults(func=_cmd_reliability_snapshot)

    ov = prove_sub.add_parser("overnight-tick", help="enqueue overnight monthly runs (15th-20th only)")
    ov.add_argument("--financial-year", dest="financial_year", required=True)
    ov.add_argument("--period", dest="period", required=True, help="YYYY-MM")
    ov.set_defaults(func=_cmd_overnight_tick)

    gates = prove_sub.add_parser("gates", help="evaluate production readiness gates")
    gates.add_argument("--lookback-hours", dest="lookback_hours", type=int, default=24)
    gates.set_defaults(func=_cmd_production_gates)

    b = sub.add_parser("gstr2b-batch", help="enqueue gstr2b_download for all active clients")
    b.add_argument("--financial-year", type=str, required=True)
    b.add_argument("--period", type=str, required=True, help="YYYY-MM")
    b.set_defaults(func=_cmd_gstr2b_batch)

    replay = sub.add_parser("replay", help="reconstruct timeline for a job_id (forensics)")
    replay.add_argument("run_or_job_id")
    replay.add_argument("--limit-jobs", type=int, default=5)
    replay.set_defaults(func=_cmd_replay)

    cleanup = sub.add_parser("cleanup-audit", help="scan cleanup invariants and record audit")
    cleanup.set_defaults(func=_cmd_cleanup_audit)

    health = sub.add_parser("browser-health", help="snapshot browser health scoring")
    health.set_defaults(func=_cmd_browser_health)

    retention = sub.add_parser("retention-audit", help="audit/enforce retention policies (dry-run default)")
    retention.add_argument("--execute", action="store_true", help="actually delete TTL-expired artifacts")
    retention.set_defaults(func=_cmd_retention_audit)

    er = sub.add_parser("email-reconcile", help="re-enqueue failed email deliveries (idempotent)")
    er.add_argument("--min-age-minutes", type=int, default=5)
    er.add_argument("--limit", type=int, default=50)
    er.set_defaults(func=_cmd_email_reconcile)

    ri = sub.add_parser("replay-integrity", help="validate replay integrity for a job_id")
    ri.add_argument("job_id")
    ri.set_defaults(func=_cmd_replay_integrity)

    camp = sub.add_parser("campaign", help="manage soak campaigns")
    camp_sub = camp.add_subparsers(dest="campaign_cmd", required=True)
    camp_start = camp_sub.add_parser("start", help="create a soak campaign and optionally run the loop")
    camp_start.add_argument("--duration-seconds", type=int, default=6 * 3600)
    camp_start.add_argument("--rate-per-minute", type=int, default=2)
    camp_start.add_argument("--chaos-percent", type=int, default=10)
    camp_start.add_argument("--run-loop", action="store_true", help="run campaign loop in this process")
    camp_start.set_defaults(func=_cmd_campaign_start)

    score = sub.add_parser("score", help="compute stability score snapshot")
    score.add_argument("--window-minutes", type=int, default=60)
    score.set_defaults(func=_cmd_score)

    diff = sub.add_parser("replay-diff", help="compare two job timelines")
    diff.add_argument("left_job_id")
    diff.add_argument("right_job_id")
    diff.set_defaults(func=_cmd_replay_diff)

    ready = sub.add_parser("readiness", help="evaluate readiness gate")
    ready.set_defaults(func=_cmd_readiness)

    cert = sub.add_parser("certify", help="generate forensic certification for a job")
    cert.add_argument("job_id")
    cert.set_defaults(func=_cmd_certify)

    validate = sub.add_parser("validate", help="execute internal validation + assertions")
    validate_sub = validate.add_subparsers(dest="validate_cmd", required=True)
    v_smoke = validate_sub.add_parser("smoke", help="run full internal test-portal smoke suite")
    v_smoke.add_argument("--parallel", type=int, default=1)
    v_smoke.set_defaults(func=_cmd_validate_smoke)
    v_chaos = validate_sub.add_parser("chaos", help="run deterministic chaos suite")
    v_chaos.add_argument("--parallel", type=int, default=1)
    v_chaos.set_defaults(func=_cmd_validate_chaos)
    v_soak = validate_sub.add_parser("soak", help="run a bounded soak validation in-process scheduler")
    v_soak.add_argument("--duration-seconds", type=int, default=30 * 60)
    v_soak.add_argument("--rate-per-minute", type=int, default=2)
    v_soak.add_argument("--chaos-percent", type=int, default=10)
    v_soak.set_defaults(func=_cmd_validate_soak)
    v_replay = validate_sub.add_parser("replay", help="audit replay integrity for recent jobs")
    v_replay.add_argument("--limit-jobs", type=int, default=25)
    v_replay.set_defaults(func=_cmd_validate_replay)
    v_recovery = validate_sub.add_parser("recovery", help="run recovery probe validation")
    v_recovery.set_defaults(func=_cmd_validate_recovery)

    doctor = sub.add_parser("doctor", help="diagnostics")
    doctor_sub = doctor.add_subparsers(dest="doctor_cmd", required=True)
    ddb = doctor_sub.add_parser("db", help="validate DB config and connectivity")
    ddb.set_defaults(func=_cmd_doctor_db)
    ds = doctor_sub.add_parser("schema", help="validate schema/migrations and required tables")
    ds.set_defaults(func=_cmd_doctor_schema)
    denv = doctor_sub.add_parser("env", help="validate .env resolution and env var loading")
    denv.set_defaults(func=_cmd_doctor_env)

    fc = sub.add_parser("full-check", help="run deterministic full system verification")
    fc.add_argument(
        "--client-master",
        default="client_master.xlsx",
        help="path to a filled client master workbook (default: client_master.xlsx)",
    )
    fc.add_argument("--skip-docker", action="store_true", help="skip docker availability check")
    fc.set_defaults(func=_cmd_full_check)

    sr = sub.add_parser("smoke-runtime", help="boot minimal API, ping health, shutdown cleanly")
    sr.add_argument("--host", default="127.0.0.1")
    sr.add_argument("--port", type=int, default=8000)
    sr.set_defaults(func=_cmd_smoke_runtime)

    gsa = sub.add_parser("gst-session-audit", help="audit persisted GST session reuse prerequisites")
    gsa.add_argument("--client-id", default=None, help="client UUID (default: None for global session profile)")
    gsa.add_argument("--profile", default="gst")
    gsa.set_defaults(func=_cmd_gst_session_audit)

    gsel = sub.add_parser("gstr2b-selector-audit", help="audit required selector keys for gstr2b_download")
    gsel.add_argument("--financial-year", required=True)
    gsel.add_argument("--period", required=True, help="YYYY-MM")
    gsel.set_defaults(func=_cmd_gstr2b_selector_audit)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        asyncio.run(args.func(args))
    except ConfigurationError as exc:
        print("[CONFIG ERROR]")
        print(str(exc))
        raise SystemExit(2) from exc
    except Exception as exc:  # noqa: BLE001
        if os.getenv("GST_AUTOMATION_DEBUG") == "1":
            raise
        msg = str(exc).lower()
        if "password authentication failed" in msg or "invalidpassworderror" in msg:
            _print_db_error(exc)
            raise SystemExit(2) from None
        print("[ERROR]")
        print(str(exc))
        raise SystemExit(1) from None
