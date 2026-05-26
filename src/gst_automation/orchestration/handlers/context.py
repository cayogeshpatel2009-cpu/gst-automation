from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.browser.session import BrowserSession
from gst_automation.core.settings import Settings
from gst_automation.orchestration.events import EventContext


@dataclass(frozen=True, slots=True)
class JobRunContext:
    """Runtime context passed to job handlers that need real execution primitives.

    This is intentionally a thin wrapper around existing platform components:
    - lease/fencing are enforced via existing repositories/guards
    - browser isolation comes from ContextIsolationEngine
    - observability uses existing EventContext ids on the attempt
    """

    settings: Settings
    session: AsyncSession
    worker_name: str
    worker_generation: int
    lease_token: str
    fencing_token: int
    attempt_id: uuid.UUID
    attempt_no: int
    event_ctx: EventContext
    browser_session: BrowserSession

