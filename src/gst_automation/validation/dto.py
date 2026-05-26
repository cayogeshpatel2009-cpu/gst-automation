from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PortalSmokeAction(BaseModel):
    kind: Literal[
        "goto",
        "click",
        "fill",
        "expect_text",
        "download",
        "sleep_ms",
        "screenshot",
    ]
    selector: str | None = None
    selector_key: str | None = None
    selector_version: int | None = None
    text: str | None = None
    value: str | None = None
    name: str | None = None


class ChaosConfig(BaseModel):
    """Deterministic chaos configuration for validation workflows."""

    scenario: Literal[
        "none",
        "navigation_timeout",
        "playwright_disconnect",
        "chromium_crash",
        "network_offline",
        "redirect_storm",
        "modal_storm",
        "download_corrupt",
        "page_freeze",
        "memory_pressure",
    ] = "none"
    at_step: int | None = Field(default=None, description="0-based action index to trigger chaos at")
    seed: int = 0


class PortalSmokePayload(BaseModel):
    """Payload for `portal_smoke` jobs (safe infrastructure validation only)."""

    base_url: str = Field(default="http://127.0.0.1:8000/test-portal")
    start_path: str = Field(default="/login")
    actions: list[PortalSmokeAction] = Field(default_factory=list)
    chaos: ChaosConfig = Field(default_factory=ChaosConfig)
    record_har: bool = True
    record_console: bool = True
    take_screenshots: bool = True


class RealSiteSmokeAction(BaseModel):
    kind: Literal["goto", "screenshot", "sleep_ms", "expect_title_contains", "expect_text"]
    url: str | None = None
    text: str | None = None
    name: str | None = None
    value: int | None = None


class RealSiteSmokePayload(BaseModel):
    """Payload for `real_site_smoke` jobs (navigation-only, safety guarded)."""

    start_url: str
    actions: list[RealSiteSmokeAction] = Field(default_factory=list)
    allow_downloads: bool = False
