"""Unhandled exceptions must produce a structured, trace_id-correlated log line (not just
a raw traceback dump outside the JSON log stream), and must never leak exception details
to the HTTP client (§14.8: secure defaults for error handling)."""

import json

from cani_shared.logging import configure_logging
from cani_shared.middleware import TRACE_HEADER, TraceIdMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient

configure_logging("test-middleware")

app = FastAPI()
app.add_middleware(TraceIdMiddleware)


@app.get("/boom")
def boom():
    raise RuntimeError("something exploded internally")


@app.get("/ok")
def ok():
    return {"status": "fine"}


client = TestClient(app, raise_server_exceptions=False)


def test_unhandled_exception_returns_generic_500_without_leaking_details():
    response = client.get("/boom")
    assert response.status_code == 500
    assert "something exploded internally" not in response.text
    assert "RuntimeError" not in response.text


def test_unhandled_exception_logs_structured_failure_with_trace_id(capsys):
    client.get("/boom", headers={TRACE_HEADER: "known-trace-id-123"})
    captured = capsys.readouterr()

    failure_lines = [line for line in captured.out.splitlines() if '"event": "request_failed"' in line]
    assert failure_lines, f"expected a request_failed log line, got stdout:\n{captured.out}"

    payload = json.loads(failure_lines[-1])
    assert payload["trace_id"] == "known-trace-id-123"
    assert payload["path"] == "/boom"
    assert payload["level"] == "error"
    assert "RuntimeError" in payload.get("exception", "")


def test_successful_request_does_not_log_failure(capsys):
    response = client.get("/ok")
    assert response.status_code == 200
    captured = capsys.readouterr()
    assert '"event": "request_failed"' not in captured.out
