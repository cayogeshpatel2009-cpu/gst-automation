from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import NoReturn

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import OperationalError

from gst_automation.core.dotenv_loader import ensure_dotenv_loaded
from gst_automation.core.env_diagnostics import diagnose_env
from gst_automation.core.settings import Settings
from gst_automation.core.exceptions import ConfigurationError


def _alembic_config(settings: Settings) -> Config:
    cfg = Config("alembic.ini")
    # Alembic reads env vars in alembic/env.py; keep cfg minimal and explicit.
    url = settings.database_migration_url or settings.database_url
    cfg.set_main_option("sqlalchemy.url", str(url))
    return cfg


def _usage() -> NoReturn:
    raise SystemExit("Usage: python -m gst_automation.cli.db [upgrade|downgrade|current|history] [--sql]")


def _print_db_error(err: BaseException) -> None:
    print("[DB ERROR]")
    print("Unable to connect to PostgreSQL for migrations.")
    print("Check:")
    print("- Is Docker Desktop / Postgres running?")
    print("- DATABASE_URL / DATABASE_MIGRATION_URL")
    print("- POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB (docker-compose.yml)")
    print(f"Details: {err}")


def _print_env_diagnostics(settings: Settings) -> None:
    d = diagnose_env(cwd=Path.cwd())
    payload = d.as_dict()
    payload["settings_database_url_present"] = bool(getattr(settings, "database_url", None))
    payload["settings_migration_url_present"] = bool(getattr(settings, "database_migration_url", None))
    print("[env] " + json.dumps(payload, sort_keys=True), file=sys.stderr)


async def _run(argv: list[str]) -> None:
    ensure_dotenv_loaded(cwd=Path.cwd())
    settings = Settings.load()
    _print_env_diagnostics(settings)
    cfg = _alembic_config(settings)
    if len(argv) < 2:
        _usage()
    cmd = argv[1]
    sql_mode = ("--sql" in argv[2:])
    if cmd == "upgrade":
        command.upgrade(cfg, "head", sql=sql_mode)
    elif cmd == "downgrade":
        command.downgrade(cfg, "-1", sql=sql_mode)
    elif cmd == "current":
        command.current(cfg)
    elif cmd == "history":
        command.history(cfg)
    else:
        _usage()


def main() -> None:
    try:
        asyncio.run(_run(sys.argv))
    except ConfigurationError as exc:
        print("[CONFIG ERROR]")
        print(str(exc))
        raise SystemExit(2) from None
    except OperationalError as exc:
        _print_db_error(exc)
        raise SystemExit(2) from None
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "password authentication failed" in msg or "invalidpassworderror" in msg:
            _print_db_error(exc)
            raise SystemExit(2) from None
        # Unknown error: still avoid a traceback in operator mode.
        print("[ERROR]")
        print(str(exc))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
