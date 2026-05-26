from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def mask_password(value: str | None) -> str | None:
    if value is None:
        return None
    s = str(value)
    if s.strip() == "":
        return ""
    return "********"


def redact_client_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if "password" in out:
        out["password"] = mask_password(str(out.get("password") or ""))
    return out


@dataclass(frozen=True, slots=True)
class RedactionPolicy:
    """Central place to ensure secrets never leak into logs/telemetry/artifacts."""

    secret_fields: frozenset[str] = frozenset({"password"})

    def redact(self, payload: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in payload.items():
            if k in self.secret_fields:
                out[k] = mask_password(str(v) if v is not None else None)
            else:
                out[k] = v
        return out

