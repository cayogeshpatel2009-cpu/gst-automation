from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable


@runtime_checkable
class JobHandler(Protocol):
    async def run(self, *, job_id: uuid.UUID, payload_json: str) -> None: ...


@runtime_checkable
class JobHandlerV2(Protocol):
    async def run_with_context(
        self,
        *,
        job_id: uuid.UUID,
        payload_json: str,
        ctx: "JobRunContext",
    ) -> None: ...


from gst_automation.orchestration.handlers.context import JobRunContext  # noqa: E402
