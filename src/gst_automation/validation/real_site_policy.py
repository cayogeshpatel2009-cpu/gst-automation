from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from gst_automation.core.exceptions import GstAutomationError
from gst_automation.core.settings import Settings


class RealSitePolicyViolation(GstAutomationError):
    """Raised when real-site validation violates safety policy."""


@dataclass(frozen=True, slots=True)
class RealSitePolicy:
    settings: Settings

    def allowlisted_prefixes(self) -> list[str]:
        raw = self.settings.real_site_allowlist
        return [p.strip().rstrip("/") for p in raw.split(",") if p.strip()]

    def assert_url_allowed(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"https", "http"}:
            raise RealSitePolicyViolation("only http/https allowed")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise RealSitePolicyViolation("http only allowed for localhost")

        url_norm = url.rstrip("/")
        for prefix in self.allowlisted_prefixes():
            if url_norm.startswith(prefix):
                return
        raise RealSitePolicyViolation("target not in allowlist")

