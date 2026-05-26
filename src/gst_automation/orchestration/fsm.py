from __future__ import annotations

from dataclasses import dataclass

from gst_automation.core.exceptions import GstAutomationError


class InvalidJobTransition(GstAutomationError):
    """Raised when a job state transition is not allowed."""


@dataclass(frozen=True, slots=True)
class TransitionRule:
    from_state: str
    to_state: str


class JobStateMachine:
    """Deterministic finite-state machine for job lifecycle transitions."""

    _allowed: set[tuple[str, str]] = {
        ("pending", "queued"),
        ("pending", "cancelled"),
        ("queued", "leased"),
        ("queued", "paused"),
        ("queued", "cancelled"),
        ("leased", "running"),
        ("leased", "retrying"),
        ("leased", "dead_lettered"),
        ("running", "completed"),
        ("running", "retrying"),
        ("running", "failed"),
        ("running", "dead_lettered"),
        ("retrying", "queued"),
        ("retrying", "dead_lettered"),
        ("paused", "queued"),
        ("paused", "cancelled"),
        ("failed", "retrying"),
        ("failed", "dead_lettered"),
    }

    def assert_allowed(self, *, from_state: str, to_state: str) -> None:
        if from_state == to_state:
            raise InvalidJobTransition(f"no-op transition rejected: {from_state} -> {to_state}")
        if (from_state, to_state) not in self._allowed:
            raise InvalidJobTransition(f"illegal transition: {from_state} -> {to_state}")

