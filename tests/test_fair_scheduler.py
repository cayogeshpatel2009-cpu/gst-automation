from __future__ import annotations

import uuid
from datetime import UTC, datetime

from gst_automation.db.models.orchestration.job import Job
from gst_automation.scheduler.fairness import FairScheduler, FairnessPolicy


def _job(*, client_id: uuid.UUID, state: str, priority: int, created_at: datetime) -> Job:
    j = Job(
        client_id=client_id,
        kind="noop",
        payload_json="{}",
        state=state,
        queue="downloads",
        priority=priority,
        next_run_at=created_at,
    )
    j.id = uuid.uuid4()
    j.created_at = created_at
    j.updated_at = created_at
    j.state_updated_at = created_at
    j.version = 0
    return j


def test_fair_scheduler_round_robins_clients() -> None:
    now = datetime.now(UTC)
    c1 = uuid.uuid4()
    c2 = uuid.uuid4()
    runnable = [
        _job(client_id=c1, state="queued", priority=2, created_at=now),
        _job(client_id=c1, state="queued", priority=2, created_at=now),
        _job(client_id=c2, state="queued", priority=2, created_at=now),
    ]
    scheduler = FairScheduler(FairnessPolicy(per_client_concurrency=1, max_enqueue_per_tick=10))
    selected = scheduler.select(runnable=runnable, inflight_by_client={}, now=now)
    # Should select one from each client first.
    assert len(selected) == 2
    assert {s.client_id for s in selected} == {c1, c2}

