from __future__ import annotations

from dataclasses import dataclass

from gst_automation.validation.dto import ChaosConfig, PortalSmokeAction, PortalSmokePayload, RealSiteSmokeAction, RealSiteSmokePayload


@dataclass(frozen=True, slots=True)
class ValidationSuites:
    """Scenario catalog for chaos/stress/recovery validation.

    This module is intentionally configuration-only: it describes deterministic workloads
    that can be scheduled via the existing `/orchestration/jobs` API as `portal_smoke`
    jobs, and analyzed via `/validation/*` APIs.
    """

    @staticmethod
    def basic_smoke() -> PortalSmokePayload:
        return PortalSmokePayload(
            start_path="/login",
            actions=[
                PortalSmokeAction(kind="fill", selector="[data-testid='login-username']", value="demo_user"),
                PortalSmokeAction(kind="fill", selector="[data-testid='login-password']", value="demo_pass"),
                PortalSmokeAction(kind="click", selector_key="login.submit"),
                PortalSmokeAction(kind="expect_text", text="OTP"),
                PortalSmokeAction(kind="click", selector_key="otp.submit"),
                PortalSmokeAction(kind="expect_text", text="Captcha"),
                PortalSmokeAction(kind="download", selector_key="download.link"),
                PortalSmokeAction(kind="screenshot", name="after_download"),
            ],
        )

    @staticmethod
    def chaos_redirect_loop() -> PortalSmokePayload:
        return PortalSmokePayload(
            start_path="/login",
            chaos=ChaosConfig(scenario="redirect_storm", at_step=1, seed=1),
            actions=[
                PortalSmokeAction(kind="screenshot", name="before_chaos"),
                PortalSmokeAction(kind="goto", text="/test-portal/redirect-loop"),
            ],
        )

    @staticmethod
    def chaos_modal_storm() -> PortalSmokePayload:
        return PortalSmokePayload(
            start_path="/modal-storm",
            chaos=ChaosConfig(scenario="modal_storm", at_step=0, seed=2),
            actions=[PortalSmokeAction(kind="screenshot", name="modals")],
        )

    @staticmethod
    def selector_drift() -> PortalSmokePayload:
        return PortalSmokePayload(
            start_path="/broken-selector",
            actions=[PortalSmokeAction(kind="click", selector_key="login.submit")],
        )

    @staticmethod
    def maintenance_spike() -> PortalSmokePayload:
        return PortalSmokePayload(
            start_path="/maintenance",
            actions=[PortalSmokeAction(kind="expect_text", text="Maintenance")],
        )

    @staticmethod
    def real_site_example_com() -> RealSiteSmokePayload:
        return RealSiteSmokePayload(
            start_url="https://example.com",
            actions=[
                RealSiteSmokeAction(kind="expect_title_contains", text="Example"),
                RealSiteSmokeAction(kind="screenshot", name="example_home"),
            ],
        )
