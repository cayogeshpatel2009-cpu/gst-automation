from __future__ import annotations

from gst_automation.core.exceptions import GstAutomationError


class GstAuthRequired(GstAutomationError):
    """Raised when batch execution requires operator-auth refresh (captcha/login)."""


class GstDownloadCorrupt(GstAutomationError):
    """Raised when a downloaded XLSX appears corrupt/partial and should be retried."""


class GstDownloadInvalid(GstAutomationError):
    """Raised when a downloaded XLSX is structurally valid but fails business validation (permanent)."""
