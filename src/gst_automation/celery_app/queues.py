from __future__ import annotations

from kombu import Exchange, Queue


EXCHANGE = Exchange("gst", type="direct")

QUEUES: tuple[Queue, ...] = (
    Queue("critical", EXCHANGE, routing_key="critical", max_priority=9),
    Queue("downloads", EXCHANGE, routing_key="downloads", max_priority=9),
    Queue("emails", EXCHANGE, routing_key="emails", max_priority=9),
    Queue("monitoring", EXCHANGE, routing_key="monitoring", max_priority=9),
    Queue("maintenance", EXCHANGE, routing_key="maintenance", max_priority=9),
    Queue("dead_letter", EXCHANGE, routing_key="dead_letter", max_priority=9),
)

