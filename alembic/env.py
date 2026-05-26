from __future__ import annotations

import json
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from alembic.ddl.postgresql import PostgresqlImpl
from sqlalchemy import Column, MetaData, PrimaryKeyConstraint, String, Table
from sqlalchemy import engine_from_config, pool

from gst_automation.core.dotenv_loader import ensure_dotenv_loaded
from gst_automation.core.env_bootstrap import resolve_env_file
from gst_automation.core.settings import Settings
from gst_automation.db.base import Base
from gst_automation.db.models.audit import AuditEvent
from gst_automation.db.models.client import Client
from gst_automation.db.models.files import StoredFile
from gst_automation.db.models.orchestration.dead_letter import DeadLetterJob
from gst_automation.db.models.orchestration.distributed_lock import DistributedLock
from gst_automation.db.models.orchestration.anomaly import WatchdogAnomaly, WatchdogAnomalyState
from gst_automation.db.models.orchestration.event import OrchestrationEvent
from gst_automation.db.models.orchestration.job import Job
from gst_automation.db.models.orchestration.job_attempt import JobAttempt
from gst_automation.db.models.orchestration.job_lease import JobLease
from gst_automation.db.models.orchestration.job_transition import JobTransition
from gst_automation.db.models.orchestration.queue_metric import QueueMetric
from gst_automation.db.models.orchestration.retry_history import RetryHistory
from gst_automation.db.models.orchestration.worker import Worker
from gst_automation.db.models.orchestration.worker_heartbeat import WorkerHeartbeat
from gst_automation.db.models.browser.browser_instance import BrowserInstance
from gst_automation.db.models.browser.browser_context import BrowserContextRecord
from gst_automation.db.models.browser.browser_artifact import BrowserArtifact
from gst_automation.db.models.browser.browser_crash import BrowserCrash
from gst_automation.db.models.portal.selector_def import PortalSelectorDef
from gst_automation.db.models.portal.session_blob import PortalSessionBlob
from gst_automation.db.models.telegram import TelegramUser, TelegramMessage, TelegramAudit

# Alembic Config object provides access to values within the .ini file.
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Ensure models are imported so metadata is populated.
target_metadata = Base.metadata

_DID_PRINT_ENV_DIAGNOSTICS = False


def _patch_postgres_version_table() -> None:
    """
    Alembic's default `alembic_version.version_num` column is `String(32)`.
    This project uses descriptive revision ids (e.g. `0007_stabilization_validation_ops`)
    which exceed 32 chars, causing `db upgrade` to fail on fresh databases.
    """

    def _version_table_impl(  # type: ignore[override]
        self: PostgresqlImpl,
        *,
        version_table: str,
        version_table_schema: str | None,
        version_table_pk: bool,
        **kw: object,
    ) -> Table:
        vt = Table(
            version_table,
            MetaData(),
            Column("version_num", String(255), nullable=False),
            schema=version_table_schema,
        )
        if version_table_pk:
            vt.append_constraint(PrimaryKeyConstraint("version_num", name=f"{version_table}_pkc"))
        return vt

    PostgresqlImpl.version_table_impl = _version_table_impl  # type: ignore[method-assign]


_patch_postgres_version_table()


def _get_migration_url() -> str:
    global _DID_PRINT_ENV_DIAGNOSTICS  # noqa: PLW0603

    ensure_dotenv_loaded(cwd=Path.cwd())
    env_path = resolve_env_file()
    settings = Settings.load()
    if not _DID_PRINT_ENV_DIAGNOSTICS:
        payload = {
            "env_file_detected": bool(env_path and env_path.is_file()),
            "resolved_env_path": str(env_path) if env_path else None,
            "cwd": str(Path.cwd()),
            "database_url_loaded": bool(getattr(settings, "database_url", None)),
            "migration_url_loaded": bool(getattr(settings, "database_migration_url", None)),
        }
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        _DID_PRINT_ENV_DIAGNOSTICS = True

    # Prefer explicit url passed via Alembic Config (e.g. `python -m gst_automation.cli.db upgrade`).
    cfg_url = config.get_main_option("sqlalchemy.url")
    url = cfg_url or (settings.database_migration_url or settings.database_url)
    if not url:
        raise RuntimeError("DATABASE_MIGRATION_URL or DATABASE_URL must be set for Alembic migrations.")
    return str(url)


def run_migrations_offline() -> None:
    url = _get_migration_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _get_migration_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 5},
        future=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
