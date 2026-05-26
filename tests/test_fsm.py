from __future__ import annotations

import pytest

from gst_automation.orchestration.fsm import InvalidJobTransition, JobStateMachine


def test_fsm_rejects_illegal_transition() -> None:
    fsm = JobStateMachine()
    with pytest.raises(InvalidJobTransition):
        fsm.assert_allowed(from_state="pending", to_state="running")


def test_fsm_rejects_noop_transition() -> None:
    fsm = JobStateMachine()
    with pytest.raises(InvalidJobTransition):
        fsm.assert_allowed(from_state="queued", to_state="queued")


def test_fsm_allows_expected_transition() -> None:
    fsm = JobStateMachine()
    fsm.assert_allowed(from_state="queued", to_state="leased")

