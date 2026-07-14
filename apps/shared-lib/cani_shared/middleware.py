"""Shared FastAPI middleware: correlation-id propagation and structured request logging."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from cani_shared.logging import get_logger, new_trace_id, set_trace_id

logger = get_logger(__name__)

TRACE_HEADER = "x-cani-trace-id"


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Propagates a correlation ID across service boundaries (§13.5).

    Incoming requests may already carry a trace ID from an upstream caller (e.g. docs-api
    calling retrieval-worker); if not, a new one is minted here at the ingress edge.
    """

    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get(TRACE_HEADER) or new_trace_id()
        set_trace_id(trace_id)
        start = time.perf_counter()
        response = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=getattr(response, "status_code", 500),
                duration_ms=round(duration_ms, 2),
            )
            if response is not None:
                response.headers[TRACE_HEADER] = trace_id
