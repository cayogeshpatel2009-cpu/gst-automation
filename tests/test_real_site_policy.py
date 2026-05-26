from __future__ import annotations

import pytest

from gst_automation.core.settings import Settings
from gst_automation.validation.real_site_policy import RealSitePolicy, RealSitePolicyViolation


def test_real_site_policy_allows_allowlisted_prefix() -> None:
    s = Settings.model_validate(
        {
            "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
            "REAL_SITE_ALLOWLIST": "https://example.com,https://playwright.dev",
        }
    )
    p = RealSitePolicy(settings=s)
    p.assert_url_allowed("https://example.com/")


def test_real_site_policy_rejects_non_allowlisted() -> None:
    s = Settings.model_validate(
        {
            "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
            "REAL_SITE_ALLOWLIST": "https://example.com",
        }
    )
    p = RealSitePolicy(settings=s)
    with pytest.raises(RealSitePolicyViolation):
        p.assert_url_allowed("https://google.com")

