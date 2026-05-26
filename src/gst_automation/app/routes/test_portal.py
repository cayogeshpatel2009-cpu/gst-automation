from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response


router = APIRouter(prefix="/test-portal", tags=["test-portal"])


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>{title}</title>
    <style>
      body {{ font-family: system-ui, sans-serif; padding: 16px; }}
      input, button {{ font-size: 16px; padding: 10px 12px; margin: 8px 0; width: 100%; max-width: 420px; }}
      .card {{ max-width: 520px; border: 1px solid #ddd; border-radius: 10px; padding: 16px; }}
      .row {{ display: flex; gap: 12px; flex-wrap: wrap; }}
      .pill {{ display: inline-block; padding: 3px 8px; border-radius: 999px; background: #f1f5f9; }}
      .modal {{ position: fixed; inset: 0; background: rgba(0,0,0,.5); display: flex; align-items: center; justify-content: center; }}
      .modal > div {{ background: white; width: min(92vw, 520px); border-radius: 12px; padding: 16px; }}
    </style>
  </head>
  <body>
    {body}
  </body>
</html>"""


@router.get("/login", response_class=HTMLResponse)
async def login(request: Request) -> HTMLResponse:
    now = datetime.now(UTC).isoformat()
    body = f"""
    <div class="card">
      <h1>Internal Test Portal</h1>
      <div class="row">
        <span class="pill" data-testid="portal-now">{now}</span>
        <span class="pill" data-testid="portal-path">{request.url.path}</span>
      </div>
      <form action="{router.prefix}/otp" method="get">
        <label>Username</label>
        <input name="u" autocomplete="username" data-testid="login-username" value="demo_user"/>
        <label>Password</label>
        <input name="p" type="password" autocomplete="current-password" data-testid="login-password" value="demo_pass"/>
        <button type="submit" data-testid="login-submit">Continue</button>
      </form>
      <a href="{router.prefix}/download" data-testid="download-link">Deterministic download</a>
    </div>
    """
    return HTMLResponse(_page("Login", body))


@router.get("/otp", response_class=HTMLResponse)
async def otp(code: str | None = None) -> HTMLResponse:
    body = f"""
    <div class="card">
      <h1>OTP</h1>
      <p data-testid="otp-hint">Use any 6 digits</p>
      <form action="{router.prefix}/captcha" method="get">
        <input name="code" inputmode="numeric" data-testid="otp-code" value="{code or ''}" />
        <button type="submit" data-testid="otp-submit">Verify</button>
      </form>
    </div>
    """
    return HTMLResponse(_page("OTP", body))


@router.get("/captcha", response_class=HTMLResponse)
async def captcha() -> HTMLResponse:
    body = f"""
    <div class="card">
      <h1>Captcha</h1>
      <p data-testid="captcha-placeholder">CAPTCHA placeholder (no solving in validation)</p>
      <a href="{router.prefix}/download" data-testid="download-link">Go to download</a>
    </div>
    """
    return HTMLResponse(_page("Captcha", body))


@router.get("/download")
async def download(
    corrupt: Annotated[bool, Query()] = False,
) -> Response:
    # Deterministic payload.
    payload = b"GST-AUTOMATION-TEST-PORTAL\nkind=download\nstatus=ok\n"
    if corrupt:
        payload = b"CORRUPT\n"
    headers = {"Content-Disposition": 'attachment; filename="test_portal_download.txt"'}
    return Response(content=payload, media_type="text/plain", headers=headers)


@router.get("/slow", response_class=HTMLResponse)
async def slow(
    delay_ms: Annotated[int, Query(ge=0, le=60000)] = 1500,
) -> HTMLResponse:
    await asyncio.sleep(delay_ms / 1000.0)
    return HTMLResponse(_page("Slow", f"<div class='card'><h1>Slow</h1><p>delay_ms={delay_ms}</p></div>"))


@router.get("/redirect-loop")
async def redirect_loop(count: Annotated[int, Query(ge=0, le=200)] = 0) -> RedirectResponse:
    # Intentionally loops to exercise redirect recovery and max-redirect handling.
    nxt = count + 1
    return RedirectResponse(url=f"{router.prefix}/redirect-loop?count={nxt}", status_code=302)


@router.get("/modal-storm", response_class=HTMLResponse)
async def modal_storm(storm: Annotated[int, Query(ge=0, le=1)] = 1) -> HTMLResponse:
    body = f"""
    <div class="card">
      <h1>Modal Storm</h1>
      <button type="button" data-testid="modal-open" onclick="openMany()">Open modals</button>
      <div id="root"></div>
    </div>
    <script>
      function openModal(i) {{
        const el = document.createElement('div');
        el.className = 'modal';
        el.innerHTML = `<div><h2>Modal ${'{'}i{'}'}</h2><button onclick="this.closest('.modal').remove()">Close</button></div>`;
        document.body.appendChild(el);
      }}
      function openMany() {{
        for (let i = 0; i < 8; i++) openModal(i);
      }}
      if ({storm} === 1) setTimeout(openMany, 50);
    </script>
    """
    return HTMLResponse(_page("Modal Storm", body))


@router.get("/broken-selector", response_class=HTMLResponse)
async def broken_selector() -> HTMLResponse:
    # Uses non-standard testids to simulate DOM drift.
    body = """
    <div class="card">
      <h1>Broken Selector</h1>
      <button data-testid="login-submit-v2">Different selector than expected</button>
    </div>
    """
    return HTMLResponse(_page("Broken Selector", body))


@router.get("/session-expired", response_class=HTMLResponse)
async def session_expired() -> HTMLResponse:
    body = f"""
    <div class="card">
      <h1>Session Expired</h1>
      <p data-testid="session-expired">Your session has expired.</p>
      <a href="{router.prefix}/login">Back to login</a>
    </div>
    """
    res = HTMLResponse(_page("Session Expired", body))
    res.delete_cookie("test_portal_session")
    return res


@router.get("/maintenance", response_class=HTMLResponse)
async def maintenance() -> HTMLResponse:
    body = f"<div class='card'><h1>Maintenance</h1><p data-testid='maintenance'>Down for maintenance.</p></div>"
    return HTMLResponse(_page("Maintenance", body), status_code=503)


@router.get("/error-spike")
async def error_spike(spike: Annotated[int, Query(ge=0, le=1)] = 1) -> Response:
    if spike == 1:
        return PlainTextResponse("intermittent error spike", status_code=500)
    return PlainTextResponse("ok")


@router.get("/partial-render", response_class=HTMLResponse)
async def partial_render() -> HTMLResponse:
    # Intentionally malformed HTML for DOM readiness edge cases.
    return HTMLResponse("<html><body><h1>Partial Render</h1><div id='root'>", status_code=200)


@router.get("/download-corrupt")
async def download_corrupt() -> Response:
    return await download(corrupt=True)
