from __future__ import annotations

import asyncio
import hashlib

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def _stable_int(s: str) -> int:
    return int(hashlib.sha256(s.encode("utf-8")).hexdigest()[:8], 16)


class TestPortalFaultInjectorMiddleware(BaseHTTPMiddleware):
    """Deterministic failure injection for `/test-portal/*` routes.

    Controls (query params):
    - `fi_delay_ms`: add fixed latency
    - `fi_error_code`: error status (default 500)
    - `fi_fail_pct`: deterministic failure percentage [0..100] based on `fi_seed` + request id
    - `fi_seed`: deterministic seed (default 0)
    - `rid`: request id (required for deterministic failure decisions)
    """

    def __init__(self, app: object, prefix: str = "/test-portal") -> None:
        super().__init__(app)
        self.prefix = prefix

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not request.url.path.startswith(self.prefix):
            return await call_next(request)

        q = request.query_params
        delay_ms = int(q.get("fi_delay_ms", "0") or "0")
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)

        fail_pct = int(q.get("fi_fail_pct", "0") or "0")
        if fail_pct > 0:
            seed = int(q.get("fi_seed", "0") or "0")
            rid = q.get("rid") or request.headers.get("x-request-id")
            # Refuse to do probabilistic failures without an explicit request id.
            if rid:
                score = _stable_int(f"{seed}:{rid}:{request.url.path}") % 100
                if score < fail_pct:
                    code = int(q.get("fi_error_code", "500") or "500")
                    return JSONResponse(
                        status_code=code,
                        content={
                            "error": "test_portal_fault_injected",
                            "path": request.url.path,
                            "rid": rid,
                            "seed": seed,
                            "score": score,
                            "fail_pct": fail_pct,
                        },
                    )

        return await call_next(request)
