from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from gst_automation.core.exceptions import GstAutomationError
from gst_automation.core.settings import Settings


class GstSafePolicyViolation(GstAutomationError):
    """Raised when GST probing attempts a forbidden action/target."""


@dataclass(frozen=True, slots=True)
class GstSafePolicy:
    settings: Settings

    def allowlisted_prefixes(self) -> list[str]:
        raw = self.settings.gst_probe_allowlist or ""
        return [p.strip().rstrip("/") for p in raw.split(",") if p.strip()]

    def assert_url_allowed(self, url: str) -> None:
        if not self.allowlisted_prefixes():
            raise GstSafePolicyViolation("GST_PROBE_ALLOWLIST is empty (refusing to probe)")
        parsed = urlparse(url)
        if parsed.scheme not in {"https", "http"}:
            raise GstSafePolicyViolation("only http/https allowed")
        # GST probe should normally be https; allow http only for local staging.
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise GstSafePolicyViolation("http only allowed for localhost")
        url_norm = url.rstrip("/")
        for prefix in self.allowlisted_prefixes():
            if url_norm.startswith(prefix):
                return
        raise GstSafePolicyViolation("GST probe target not in allowlist")

    def assert_read_only_action(self, action: str) -> None:
        # Explicit deny list: anything interactive beyond navigation and passive checks.
        forbidden = {"click", "fill", "type", "press", "check", "uncheck", "select", "set_input_files", "submit"}
        if action in forbidden:
            raise GstSafePolicyViolation(f"forbidden action in gst_safe_probe: {action}")

