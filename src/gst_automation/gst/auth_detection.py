from __future__ import annotations

from dataclasses import dataclass

from playwright.async_api import Page


@dataclass(frozen=True, slots=True)
class AuthState:
    state: str  # unknown/login/otp/captcha/authed/session_expired/maintenance
    details: dict[str, object]


@dataclass(frozen=True, slots=True)
class GstAuthDetector:
    """Heuristic auth-flow detector (no submission)."""

    async def detect(self, page: Page) -> AuthState:
        url = page.url
        title = await page.title()
        # Avoid expensive full-body extraction which can hang on large/active pages.
        try:
            body = await page.evaluate("() => (document.body && document.body.innerText ? document.body.innerText.slice(0, 5000) : '')")
        except Exception:
            body = ""

        # Maintenance signals
        if "maintenance" in body.lower() or "temporarily unavailable" in body.lower():
            return AuthState("maintenance", {"url": url, "title": title})

        # Login-ish signals
        has_password = await page.locator("input[type='password']").count()
        has_username = await page.locator("input[type='text'],input[name*='user' i],input[id*='user' i]").count()
        if has_password:
            return AuthState("login", {"url": url, "title": title, "password_inputs": int(has_password)})

        # OTP-ish signals
        has_otp = await page.locator("input[inputmode='numeric'],input[name*='otp' i],input[id*='otp' i]").count()
        if has_otp and ("otp" in body.lower() or "one time" in body.lower()):
            return AuthState("otp", {"url": url, "title": title})

        # Captcha-ish signals
        has_captcha = await page.locator("iframe[src*='captcha' i], img[alt*='captcha' i], img[src*='captcha' i]").count()
        has_captcha_input = await page.locator(
            "input[name*='captcha' i],input[id*='captcha' i],input[placeholder*='characters' i]"
        ).count()
        has_captcha_text = await page.locator("text=/type the characters you see/i").count()
        if has_captcha or "captcha" in body.lower() or has_captcha_input or has_captcha_text:
            return AuthState("captcha", {"url": url, "title": title})

        # Session-expired signals
        if "session" in body.lower() and "expired" in body.lower():
            return AuthState("session_expired", {"url": url, "title": title})

        # Authenticated-ish signals
        try:
            logout = await page.locator("text=/logout/i").count()
            if logout:
                return AuthState("authenticated", {"url": url, "title": title})
        except Exception:
            pass

        return AuthState("unknown", {"url": url, "title": title})
