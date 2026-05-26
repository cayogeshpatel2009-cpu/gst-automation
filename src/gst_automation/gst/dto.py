from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GstSafeProbeStep(BaseModel):
    kind: Literal[
        "goto",
        "wait_for_domcontentloaded",
        "wait_ms",
        "screenshot",
        "capture_dom",
        "detect_auth_state",
        "detect_captcha",
        "detect_otp",
        "measure_latency",
        "selector_probe",
    ]
    url: str | None = None
    name: str | None = None
    ms: int | None = None
    selector: str | None = None
    selector_key: str | None = None


class GstSafeProbePayload(BaseModel):
    """Read-only probe payload for GST portal (no login submission, no downloads)."""

    start_url: str = Field(min_length=1)
    steps: list[GstSafeProbeStep] = Field(default_factory=list)
    take_screenshots: bool = True
    capture_dom: bool = True
    selector_discovery: bool = True


class GstAuthSessionPayload(BaseModel):
    """Supervised authentication session acquisition (HITL, no unattended auth)."""

    start_url: str = Field(min_length=1)
    gstin: str | None = Field(default=None, max_length=32)
    client_id: str | None = None
    profile: str = Field(default="gst", max_length=64)
    ttl_days: int = Field(default=7, ge=1, le=30)
    checkpoint_timeout_seconds: int = Field(default=300, ge=30, le=3600)
