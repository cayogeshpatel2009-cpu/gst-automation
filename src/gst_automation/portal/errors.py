from __future__ import annotations

from gst_automation.core.exceptions import GstAutomationError


class PortalAutomationError(GstAutomationError):
    """Base error for portal automation framework."""


class SelectorNotFound(PortalAutomationError):
    """Selector registry has no entry for a key/version."""


class SelectorResolutionFailed(PortalAutomationError):
    """All selector candidates failed."""


class NavigationFailed(PortalAutomationError):
    """Navigation failed after retries/recovery."""


class InteractionFailed(PortalAutomationError):
    """Interaction failed after retries/recovery."""


class PageStateUnknown(PortalAutomationError):
    """Page state could not be confidently determined."""


class SessionCorrupt(PortalAutomationError):
    """Encrypted session could not be decrypted/parsed."""

