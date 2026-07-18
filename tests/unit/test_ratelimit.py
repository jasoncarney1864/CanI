"""Rate limiting (docs/14 §14.8): token-bucket enforcement, probe exemption, refill, and
per-client isolation. Uses a tiny FastAPI app with the real middleware."""

from __future__ import annotations

import time

from cani_shared.middleware import RateLimitMiddleware
from fastapi import FastAPI
from starlette.testclient import TestClient


def _app(*, capacity: int, window_seconds: float) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, capacity=capacity, window_seconds=window_seconds)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


def _get(client, path, ip="203.0.113.7"):
    return client.get(path, headers={"x-forwarded-for": ip})


def test_allows_up_to_capacity_then_429():
    client = TestClient(_app(capacity=5, window_seconds=60))
    codes = [_get(client, "/ping").status_code for _ in range(5)]
    assert codes == [200] * 5
    blocked = _get(client, "/ping")
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "rate limit exceeded"
    assert int(blocked.headers["retry-after"]) >= 1


def test_healthz_is_exempt():
    client = TestClient(_app(capacity=1, window_seconds=60))
    # Exhaust the bucket on /ping, then hammer /healthz — probes must never be throttled.
    assert _get(client, "/ping").status_code == 200
    assert _get(client, "/ping").status_code == 429
    for _ in range(10):
        assert _get(client, "/healthz").status_code == 200


def test_refill_allows_again_after_window():
    # capacity 1 over a 0.2s window -> refills ~5 tokens/sec, so a short sleep restores one.
    client = TestClient(_app(capacity=1, window_seconds=0.2))
    assert _get(client, "/ping").status_code == 200
    assert _get(client, "/ping").status_code == 429
    time.sleep(0.3)
    assert _get(client, "/ping").status_code == 200


def test_clients_are_isolated():
    client = TestClient(_app(capacity=2, window_seconds=60))
    # Client A exhausts its bucket...
    assert _get(client, "/ping", ip="198.51.100.1").status_code == 200
    assert _get(client, "/ping", ip="198.51.100.1").status_code == 200
    assert _get(client, "/ping", ip="198.51.100.1").status_code == 429
    # ...client B is unaffected.
    assert _get(client, "/ping", ip="198.51.100.2").status_code == 200
    assert _get(client, "/ping", ip="198.51.100.2").status_code == 200
