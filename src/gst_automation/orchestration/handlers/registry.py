from __future__ import annotations

from dataclasses import dataclass

from gst_automation.orchestration.handlers.base import JobHandler
from gst_automation.orchestration.handlers.noop import NoopJobHandler
from gst_automation.orchestration.handlers.portal_smoke import PortalSmokeJobHandler
from gst_automation.orchestration.handlers.real_site_smoke import RealSiteSmokeJobHandler
from gst_automation.orchestration.handlers.gst_safe_probe import GstSafeProbeJobHandler
from gst_automation.orchestration.handlers.gst_auth_session import GstAuthSessionJobHandler
from gst_automation.orchestration.handlers.gst_observation_session import GstObservationSessionJobHandler
from gst_automation.orchestration.handlers.assisted_gstr2b_execution import AssistedGstr2bExecutionJobHandler
from gst_automation.orchestration.handlers.gstr2b_download import Gstr2bDownloadJobHandler
from gst_automation.orchestration.handlers.email_delivery import EmailDeliveryJobHandler


@dataclass(frozen=True, slots=True)
class HandlerRegistry:
    """Registry for job handlers by `job.kind`."""

    handlers: dict[str, JobHandler]

    @classmethod
    def build_default(cls) -> "HandlerRegistry":
        # Phase 2 provides platform infrastructure; business handlers arrive in later phases.
        return cls(
            handlers={
                "noop": NoopJobHandler(),
                "portal_smoke": PortalSmokeJobHandler(),
                "real_site_smoke": RealSiteSmokeJobHandler(),
                "gst_safe_probe": GstSafeProbeJobHandler(),
                "gst_auth_session": GstAuthSessionJobHandler(),
                "gst_observation_session": GstObservationSessionJobHandler(),
                "assisted_gstr2b_execution": AssistedGstr2bExecutionJobHandler(),
                "gstr2b_download": Gstr2bDownloadJobHandler(),
                "email_delivery": EmailDeliveryJobHandler(),
            }
        )

    def get(self, kind: str) -> JobHandler | None:
        return self.handlers.get(kind)
