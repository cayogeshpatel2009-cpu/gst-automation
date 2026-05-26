from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable
from typing import TypeVar


T = TypeVar("T")

_LOOPS_BY_THREAD: dict[int, asyncio.AbstractEventLoop] = {}


def run_async(coro: Awaitable[T]) -> T:
    """Run an async coroutine from a sync Celery task context."""
    # Celery (solo pool) runs tasks synchronously in one process/thread. Using asyncio.run()
    # per task closes the loop, which breaks long-lived async resources (Playwright/redis/etc)
    # held in module singletons. Keep a process-global loop instead.
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running and running.is_running():
        raise RuntimeError("run_async() called with running event loop")

    tid = threading.get_ident()
    loop = _LOOPS_BY_THREAD.get(tid)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _LOOPS_BY_THREAD[tid] = loop
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)
