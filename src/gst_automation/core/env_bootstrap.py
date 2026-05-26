from __future__ import annotations

import os
from pathlib import Path

ENV_FILE_ENVVAR = "GST_AUTOMATION_ENV_FILE"


def resolve_env_file(*, cwd: Path | None = None) -> Path | None:
    """
    Resolve a deterministic `.env` path for CLI/migration contexts.

    Precedence:
    1) `GST_AUTOMATION_ENV_FILE` (absolute or relative to `cwd`)
    2) First `.env` found walking upward from `cwd` (default: `Path.cwd()`)
    3) `.env` next to the nearest `pyproject.toml` walking upward from this file
    """
    base = (cwd or Path.cwd()).resolve()

    configured = os.getenv(ENV_FILE_ENVVAR)
    if configured:
        p = Path(configured).expanduser()
        if not p.is_absolute():
            p = base / p
        return p.resolve() if p.exists() else p.resolve()

    for parent in (base, *base.parents):
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate.resolve()

    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / "pyproject.toml").is_file():
            candidate = parent / ".env"
            return candidate.resolve() if candidate.is_file() else None

    return None

