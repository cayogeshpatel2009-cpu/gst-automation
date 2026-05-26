from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AuthStateName = Literal[
    "anonymous",
    "login_page",
    "captcha_required",
    "otp_required",
    "authenticated",
    "session_expired",
    "maintenance",
    "blocked",
    "unknown",
]


@dataclass(frozen=True, slots=True)
class AuthFsm:
    """Explicit auth FSM used for supervised GST authentication."""

    state: AuthStateName

    def transition(self, observed: str) -> "AuthFsm":
        # Observations come from GstAuthDetector (login/otp/captcha/session_expired/maintenance/unknown).
        if observed == "maintenance":
            return AuthFsm("maintenance")
        if observed == "session_expired":
            return AuthFsm("session_expired")
        if observed == "login":
            return AuthFsm("login_page")
        if observed == "captcha":
            return AuthFsm("captcha_required")
        if observed == "otp":
            return AuthFsm("otp_required")
        if observed in {"authed", "authenticated"}:
            return AuthFsm("authenticated")
        return AuthFsm("unknown")
