from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, text
from alembic.config import Config
from alembic.script import ScriptDirectory

from gst_automation.core.db_diagnostics import DbTarget, validate_db_url
from gst_automation.core.exceptions import ConfigurationError
from gst_automation.core.env_diagnostics import diagnose_env
from gst_automation.core.settings import Settings
from gst_automation.db.session import Db


@dataclass(frozen=True, slots=True)
class DoctorDbReport:
    database_url_ok: bool
    database_url_target: str | None
    database_url_error: str | None
    asyncpg_reachable: bool
    asyncpg_auth_ok: bool
    asyncpg_error: str | None
    migration_url_ok: bool
    migration_url_target: str | None
    migration_url_error: str | None
    migration_reachable: bool
    migration_auth_ok: bool
    migration_error: str | None
    server_info: dict[str, str] | None


@dataclass(frozen=True, slots=True)
class DoctorSchemaReport:
    ok: bool
    head_revision: str | None
    db_revision: str | None
    required_tables_missing: list[str]
    tables: list[str]
    error: str | None


@dataclass(frozen=True, slots=True)
class DoctorEnvReport:
    env_file_detected: bool
    resolved_env_path: str | None
    cwd: str
    database_url_loaded: bool
    migration_url_loaded: bool


def doctor_env(settings: Settings) -> DoctorEnvReport:
    d = diagnose_env(cwd=Path.cwd()).as_dict()
    return DoctorEnvReport(
        env_file_detected=bool(d.get("env_file_detected")),
        resolved_env_path=str(d.get("resolved_env_path")) if d.get("resolved_env_path") else None,
        cwd=str(d.get("cwd") or ""),
        database_url_loaded=bool(getattr(settings, "database_url", None)),
        migration_url_loaded=bool(getattr(settings, "database_migration_url", None)),
    )


def _classify_db_exc(exc: BaseException) -> tuple[bool, bool, str]:
    msg = str(exc)
    lower = msg.lower()
    # Coarse classification without importing asyncpg internals.
    if "password authentication failed" in lower or "invalidpassworderror" in lower:
        return True, False, msg
    if "connection refused" in lower or "could not connect" in lower or "name or service not known" in lower:
        return False, False, msg
    return False, False, msg


async def doctor_db(settings: Settings) -> DoctorDbReport:
    # Parse/validate URLs
    db_target: DbTarget | None = None
    db_err: str | None = None
    mig_target: DbTarget | None = None
    mig_err: str | None = None

    try:
        db_target = validate_db_url(str(settings.database_url), label="DATABASE_URL")
        db_ok = True
    except Exception as exc:  # noqa: BLE001
        db_ok = False
        db_err = str(exc)

    try:
        if not settings.database_migration_url:
            raise ConfigurationError("DATABASE_MIGRATION_URL missing")
        mig_target = validate_db_url(str(settings.database_migration_url), label="DATABASE_MIGRATION_URL")
        mig_ok = True
    except Exception as exc:  # noqa: BLE001
        mig_ok = False
        mig_err = str(exc)

    # Connectivity checks
    asyncpg_reachable = False
    asyncpg_auth_ok = False
    asyncpg_error: str | None = None
    server_info: dict[str, str] | None = None

    if db_ok:
        db = Db(str(settings.database_url))
        try:
            await db.ping()
            asyncpg_reachable = True
            asyncpg_auth_ok = True
            # Also fetch current db/user for diagnostics.
            async with db._engine.connect() as conn:  # noqa: SLF001
                res = await conn.execute(text("SELECT current_database(), current_user"))
                row = res.first()
                if row:
                    server_info = {"current_database": str(row[0]), "current_user": str(row[1])}
        except Exception as exc:  # noqa: BLE001
            reach, auth, msg = _classify_db_exc(exc)
            asyncpg_reachable = reach
            asyncpg_auth_ok = auth
            asyncpg_error = msg
        finally:
            await db.close()

    migration_reachable = False
    migration_auth_ok = False
    migration_error: str | None = None

    if mig_ok and settings.database_migration_url:
        try:
            eng = create_engine(
                str(settings.database_migration_url),
                pool_pre_ping=True,
                connect_args={"connect_timeout": 5},
                future=True,
            )
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            migration_reachable = True
            migration_auth_ok = True
        except Exception as exc:  # noqa: BLE001
            reach, auth, msg = _classify_db_exc(exc)
            migration_reachable = reach
            migration_auth_ok = auth
            migration_error = msg
        finally:
            try:
                eng.dispose()
            except Exception:
                pass

    return DoctorDbReport(
        database_url_ok=db_ok,
        database_url_target=db_target.display if db_target else None,
        database_url_error=db_err,
        asyncpg_reachable=asyncpg_reachable,
        asyncpg_auth_ok=asyncpg_auth_ok,
        asyncpg_error=asyncpg_error,
        migration_url_ok=mig_ok,
        migration_url_target=mig_target.display if mig_target else None,
        migration_url_error=mig_err,
        migration_reachable=migration_reachable,
        migration_auth_ok=migration_auth_ok,
        migration_error=migration_error,
        server_info=server_info,
    )


def doctor_schema(settings: Settings) -> DoctorSchemaReport:
    head: str | None = None
    try:
        cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(cfg)
        head = script.get_current_head()
    except Exception:
        head = None

    if not settings.database_migration_url:
        return DoctorSchemaReport(
            ok=False,
            head_revision=head,
            db_revision=None,
            required_tables_missing=[],
            tables=[],
            error="DATABASE_MIGRATION_URL missing",
        )

    try:
        validate_db_url(str(settings.database_migration_url), label="DATABASE_MIGRATION_URL")
    except Exception as exc:  # noqa: BLE001
        return DoctorSchemaReport(
            ok=False,
            head_revision=head,
            db_revision=None,
            required_tables_missing=[],
            tables=[],
            error=str(exc),
        )

    required = ["clients", "client_configs", "client_credential_refs", "jobs", "alembic_version"]
    tables: list[str] = []
    missing: list[str] = []
    db_rev: str | None = None

    try:
        eng = create_engine(
            str(settings.database_migration_url),
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5},
            future=True,
        )
        with eng.connect() as conn:
            # List tables.
            res = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public' ORDER BY table_name"
                )
            )
            tables = [str(r[0]) for r in res.fetchall()]

            # Alembic revision.
            if "alembic_version" in tables:
                r2 = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
                row = r2.first()
                db_rev = str(row[0]) if row and row[0] else None

        for t in required:
            if t not in tables:
                missing.append(t)
        ok = (not missing) and (head is None or db_rev == head)
        err = None
        if missing:
            err = "missing tables (migrations not applied?)"
        elif head and db_rev and db_rev != head:
            err = f"db revision {db_rev} != head {head}"
        return DoctorSchemaReport(
            ok=ok,
            head_revision=head,
            db_revision=db_rev,
            required_tables_missing=missing,
            tables=tables,
            error=err,
        )
    except Exception as exc:  # noqa: BLE001
        return DoctorSchemaReport(
            ok=False,
            head_revision=head,
            db_revision=db_rev,
            required_tables_missing=[],
            tables=tables,
            error=str(exc),
        )
    finally:
        try:
            eng.dispose()
        except Exception:
            pass
