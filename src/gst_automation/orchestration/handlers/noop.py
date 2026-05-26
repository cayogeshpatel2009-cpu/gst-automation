from __future__ import annotations

import uuid
from dataclasses import dataclass

from gst_automation.core.logging import get_logger
from gst_automation.orchestration.handlers.base import JobHandler, JobHandlerV2
from gst_automation.orchestration.handlers.context import JobRunContext


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class NoopJobHandler(JobHandler, JobHandlerV2):
    async def run(self, *, job_id: uuid.UUID, payload_json: str) -> None:
        logger.info("job.noop", job_id=str(job_id), payload_json=payload_json)

    async def run_with_context(
        self, *, job_id: uuid.UUID, payload_json: str, ctx: JobRunContext
    ) -> None:
        _ = ctx
        logger.info("job.noop", job_id=str(job_id), payload_json=payload_json)
