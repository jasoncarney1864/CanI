"""Shared FastAPI middleware: correlation-id propagation, structured request logging, and
per-client rate limiting."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from cani_shared.logging import get_logger, hash_user_id, new_trace_id, set_trace_id

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


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-client token-bucket rate limiting for externally reachable APIs (§14.8).

    A bucket holds up to `capacity` tokens and refills at `capacity / window_seconds` per
    second; each request spends one. An empty bucket returns 429 with `Retry-After`. This
    absorbs short bursts while capping the sustained rate — the abuse-protection §14.8
    asks for on public endpoints (brute-forcing auth, hammering upload/query).

    Buckets are in-memory per process, so with N replicas the effective ceiling is
    ~N x capacity. That is fine for dev (single replica) and as approximate protection in
    general; a strict global limit would need a shared store (Redis) and is deferred.
    Health probes are exempt — throttling them would flap readiness under load.
    """

    def __init__(self, app, *, capacity: int, window_seconds: float, exclude_paths=("/healthz",)):
        super().__init__(app)
        self._capacity = float(capacity)
        self._refill_per_sec = capacity / window_seconds
        self._exclude = set(exclude_paths)
        self._retry_after = max(1, round(1 / self._refill_per_sec))
        # key -> [tokens, last_refill_monotonic]
        self._buckets: dict[str, list[float]] = {}
        # Bound memory: once this many distinct clients are tracked, drop idle (full)
        # buckets — an idle client re-creates its bucket harmlessly on next request.
        self._max_buckets = 10_000

    @staticmethod
    def _client_key(request: Request) -> str:
        # Behind an ingress/proxy the real client is the leftmost X-Forwarded-For hop;
        # direct connections fall back to the socket peer.
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._exclude:
            return await call_next(request)

        key = self._client_key(request)
        now = time.monotonic()
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self._max_buckets:
                self._evict_idle(now)
            bucket = [self._capacity, now]
            self._buckets[key] = bucket

        # Refill based on elapsed time, capped at capacity.
        bucket[0] = min(self._capacity, bucket[0] + (now - bucket[1]) * self._refill_per_sec)
        bucket[1] = now

        if bucket[0] < 1:
            logger.warning("rate_limited", path=request.url.path, client_hash=hash_user_id(key))
            return JSONResponse(
                {"detail": "rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(self._retry_after)},
            )
        bucket[0] -= 1
        return await call_next(request)

    def _evict_idle(self, now: float) -> None:
        # Remove buckets that have fully refilled (client has been quiet for a full window).
        for key in [
            k
            for k, (tokens, last) in self._buckets.items()
            if min(self._capacity, tokens + (now - last) * self._refill_per_sec) >= self._capacity
        ]:
            del self._buckets[key]
