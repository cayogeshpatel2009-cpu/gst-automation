from __future__ import annotations

from gst_automation.orchestration.router import QueueRouter


def test_router_escalates_critical_for_p1() -> None:
    r = QueueRouter()
    q = r.route(kind="noop", requested_queue="downloads", priority=1)
    assert q == "critical"

