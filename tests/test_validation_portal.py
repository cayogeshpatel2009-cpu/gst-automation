from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from gst_automation.app.middleware.test_portal_faults import TestPortalFaultInjectorMiddleware
from gst_automation.app.routes.test_portal import router as test_portal_router
from gst_automation.orchestration.handlers.registry import HandlerRegistry
from gst_automation.validation.cli_main import build_parser


@pytest.mark.asyncio
async def test_test_portal_login_has_expected_testids() -> None:
    app = FastAPI()
    app.add_middleware(TestPortalFaultInjectorMiddleware)
    app.include_router(test_portal_router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/test-portal/login")
        assert res.status_code == 200
        html = res.text
        assert "data-testid=\"login-username\"" in html
        assert "data-testid=\"login-password\"" in html
        assert "data-testid=\"login-submit\"" in html


@pytest.mark.asyncio
async def test_test_portal_fault_injector_can_force_failure() -> None:
    app = FastAPI()
    app.add_middleware(TestPortalFaultInjectorMiddleware)
    app.include_router(test_portal_router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/test-portal/login?fi_fail_pct=100&rid=req1")
        assert res.status_code == 500
        assert res.json()["error"] == "test_portal_fault_injected"


def test_handler_registry_includes_portal_smoke() -> None:
    reg = HandlerRegistry.build_default()
    assert reg.get("portal_smoke") is not None


def test_validation_cli_parses_commands() -> None:
    p = build_parser()
    args = p.parse_args(["run", "smoke", "--parallel", "2"])
    assert args.cmd == "run"
    assert args.scenario == "smoke"
    assert args.parallel == 2
