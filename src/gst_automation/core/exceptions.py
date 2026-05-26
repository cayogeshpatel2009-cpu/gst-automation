from __future__ import annotations


class GstAutomationError(Exception):
    """Base exception for the platform."""


class ConfigurationError(GstAutomationError):
    """Raised when configuration is missing or invalid."""


class StartupValidationError(GstAutomationError):
    """Raised when startup validation fails."""


class VaultError(GstAutomationError):
    """Raised when secret storage/retrieval fails."""


class ArchiveError(GstAutomationError):
    """Raised when immutable archive operations fail."""


class StorageError(GstAutomationError):
    """Raised when local storage operations fail."""

