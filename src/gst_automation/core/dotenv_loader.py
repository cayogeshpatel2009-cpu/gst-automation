from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gst_automation.core.env_bootstrap import resolve_env_file


@dataclass(frozen=True, slots=True)
class DotenvLoadResult:
    env_path: Path | None
    loaded: bool
    keys_loaded: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "env_path": str(self.env_path) if self.env_path else None,
            "loaded": self.loaded,
            "keys_loaded": list(self.keys_loaded),
        }


def _parse_env_line(line: str) -> tuple[str, str] | None:
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    if s.startswith("export "):
        s = s[len("export ") :].strip()
    if "=" not in s:
        return None
    key, val = s.split("=", 1)
    key = key.strip()
    val = val.strip()
    if not key:
        return None
    # Strip inline comments only when value is unquoted.
    if val and val[0] not in {"'", '"'} and " #" in val:
        val = val.split(" #", 1)[0].rstrip()
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        val = val[1:-1]
    return key, val


def load_dotenv(*, cwd: Path | None = None, override: bool = False) -> DotenvLoadResult:
    """
    Minimal `.env` loader (no external dependency) to ensure CLI/migration
    contexts see the same env as app runtime.

    - Does not override existing env vars unless override=True
    - Ignores invalid lines
    """
    base = (cwd or Path.cwd()).resolve()
    env_path = resolve_env_file(cwd=base)
    if env_path is None or not env_path.is_file():
        return DotenvLoadResult(env_path=env_path, loaded=False, keys_loaded=[])

    keys_loaded: list[str] = []
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_env_line(raw)
            if not parsed:
                continue
            k, v = parsed
            if not override and os.getenv(k) not in {None, ""}:
                continue
            os.environ[k] = v
            keys_loaded.append(k)
    except Exception:
        return DotenvLoadResult(env_path=env_path, loaded=False, keys_loaded=[])

    return DotenvLoadResult(env_path=env_path, loaded=True, keys_loaded=keys_loaded)


def ensure_dotenv_loaded(*, cwd: Path | None = None) -> DotenvLoadResult:
    # Default safe behavior: never override exported env vars.
    return load_dotenv(cwd=cwd, override=False)

