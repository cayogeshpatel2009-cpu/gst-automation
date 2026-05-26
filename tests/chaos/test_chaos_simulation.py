from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from gst_automation.orchestration.fsm import JobStateMachine, InvalidJobTransition


@dataclass
class SimJob:
    id: uuid.UUID
    state: str
    version: int = 0


def apply_transition(job: SimJob, *, to_state: str) -> None:
    fsm = JobStateMachine()
    fsm.assert_allowed(from_state=job.state, to_state=to_state)
    job.state = to_state
    job.version += 1


def test_chaos_duplicate_enqueue_is_detectable_by_state_machine() -> None:
    job = SimJob(id=uuid.uuid4(), state="pending")
    apply_transition(job, to_state="queued")
    with pytest.raises(InvalidJobTransition):
        apply_transition(job, to_state="queued")


def test_chaos_lease_expiry_recovery_path_is_valid() -> None:
    # Simulates: queued -> leased -> running, then crash and recovery requeues.
    job = SimJob(id=uuid.uuid4(), state="queued")
    apply_transition(job, to_state="leased")
    apply_transition(job, to_state="running")
    # Recovery must bring it back to queued via a legal path:
    with pytest.raises(InvalidJobTransition):
        apply_transition(job, to_state="queued")
    # Recovery path in platform: running -> retrying -> queued
    apply_transition(job, to_state="retrying")
    apply_transition(job, to_state="queued")

