from __future__ import annotations

import os
import socket


def compute_worker_name(*, pid: int, queues: list[str]) -> str:
    explicit = os.getenv("WORKER_NAME")
    if explicit:
        return explicit
    host = socket.gethostname()
    q = ",".join(sorted(set(queues))) if queues else "default"
    return f"{host}:{pid}:{q}"

