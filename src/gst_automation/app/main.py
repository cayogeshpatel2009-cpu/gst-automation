from __future__ import annotations

from fastapi import FastAPI

from gst_automation.app.lifespan import lifespan
from gst_automation.app.routes.health import router as health_router
from gst_automation.app.routes.metrics import router as metrics_router
from gst_automation.app.routes.orchestration import router as orchestration_router
from gst_automation.app.routes.orchestration_state import router as orchestration_state_router
from gst_automation.app.routes.dlq import router as dlq_router
from gst_automation.app.routes.events import router as events_router
from gst_automation.app.routes.browser_ops import router as browser_ops_router
from gst_automation.app.routes.portal_framework import router as portal_framework_router
from gst_automation.app.routes.test_portal import router as test_portal_router
from gst_automation.app.routes.validation import router as validation_router
from gst_automation.app.routes.stability import router as stability_router
from gst_automation.app.routes.gst_readiness import router as gst_readiness_router
from gst_automation.app.routes.operator import router as operator_router
from gst_automation.app.routes.auth import router as auth_router
from gst_automation.app.routes.clients import router as clients_router
from gst_automation.app.routes.gst_selectors import router as gst_selectors_router
from gst_automation.app.routes.hardening import router as hardening_router
from gst_automation.app.routes.telegram import router as telegram_router
from gst_automation.app.middleware.test_portal_faults import TestPortalFaultInjectorMiddleware


def build_app() -> FastAPI:
    app = FastAPI(title="GST Automation Platform", version="0.1.0", lifespan=lifespan)
    app.add_middleware(TestPortalFaultInjectorMiddleware)
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(orchestration_router)
    app.include_router(orchestration_state_router)
    app.include_router(dlq_router)
    app.include_router(events_router)
    app.include_router(browser_ops_router)
    app.include_router(portal_framework_router)
    app.include_router(test_portal_router)
    app.include_router(validation_router)
    app.include_router(stability_router)
    app.include_router(gst_readiness_router)
    app.include_router(operator_router)
    app.include_router(auth_router)
    app.include_router(clients_router)
    app.include_router(gst_selectors_router)
    app.include_router(hardening_router)
    app.include_router(telegram_router)
    return app
