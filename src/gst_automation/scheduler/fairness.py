from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from gst_automation.db.models.orchestration.job import Job


@dataclass(frozen=True, slots=True)
class FairnessPolicy:
    per_client_concurrency: int
    max_enqueue_per_tick: int


class FairScheduler:
    """Weighted fair scheduling over runnable jobs with per-client limits."""

    def __init__(self, policy: FairnessPolicy) -> None:
        self._policy = policy

    def select(
        self,
        *,
        runnable: list[Job],
        inflight_by_client: dict[uuid.UUID, int],
        now: datetime,
    ) -> list[Job]:
        _ = now
        # Partition by client_id to avoid monopolization; None client_id treated as its own bucket.
        buckets: dict[uuid.UUID, list[Job]] = {}
        for job in runnable:
            cid = job.client_id or uuid.UUID("00000000-0000-0000-0000-000000000000")
            buckets.setdefault(cid, []).append(job)

        for cid, jobs in buckets.items():
            # Prefer queued over retrying, then higher priority, then older first.
            jobs.sort(
                key=lambda j: (
                    0 if j.state == "queued" else 1,
                    j.priority,
                    j.created_at,
                )
            )

        selected: list[Job] = []
        # Round-robin over client buckets.
        client_ids = sorted(buckets.keys(), key=str)
        idx = 0
        while len(selected) < self._policy.max_enqueue_per_tick and client_ids:
            cid = client_ids[idx % len(client_ids)]
            idx += 1
            inflight = inflight_by_client.get(cid, 0)
            if inflight >= self._policy.per_client_concurrency:
                continue
            q = buckets[cid]
            if not q:
                client_ids = [x for x in client_ids if x != cid]
                continue
            job = q.pop(0)
            selected.append(job)
            inflight_by_client[cid] = inflight + 1
        return selected

