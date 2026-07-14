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
        except Exception:
            # Without this, an unhandled exception propagates straight to Starlette's
            # default handler, which logs a raw traceback via the stdlib `logging`
            # module — untagged with trace_id and outside the structured JSON stream
            # every other log line uses. That makes failures hard to correlate against
            # the request that caused them once logs leave a single terminal (e.g. once
            # shipped to Log Analytics per docs/13-observability.md §13.3). Log
            # structured here, then re-raise so Starlette still returns its safe,
            # generic 500 body — this must never leak exception details to the client.
            logger.error(
                "request_failed",
                method=request.method,
                path=request.url.path,
                exc_info=True,
            )
            raise
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
