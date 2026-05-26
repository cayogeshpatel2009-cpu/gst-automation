from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


QueueName = Literal["critical", "downloads", "emails", "monitoring", "maintenance", "dead_letter"]


class JobPriority:
    """Priority constants (lower number = higher priority)."""

    P1_OPERATOR: int = 1
    P2_DOWNLOAD: int = 2
    P3_EMAIL: int = 3
    P4_MONITORING: int = 4
    P5_MAINTENANCE: int = 5


class JobCreate(BaseModel):
    kind: str = Field(min_length=1, max_length=128)
    client_id: uuid.UUID | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    queue: QueueName
    priority: int = Field(ge=1, le=9, default=JobPriority.P3_EMAIL)
    idempotency_key: str | None = Field(default=None, max_length=128)

    def payload_json(self) -> str:
        return json.dumps(self.payload, sort_keys=True, separators=(",", ":"))


class JobView(BaseModel):
    id: uuid.UUID
    kind: str
    client_id: uuid.UUID | None
    state: str
    queue: str
    priority: int
    created_at: datetime
    updated_at: datetime
    next_run_at: datetime | None


class DeadLetterView(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    job_kind: str
    created_at: datetime

