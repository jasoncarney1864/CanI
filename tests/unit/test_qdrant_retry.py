"""retry_transient: the retrieval-path hardening from the 2026-08-09 outage
(docs/sitreps/2026-08-09-qdrant-corruption-and-missing-backups.md). The contract under
test: transient faults (network-level, 5xx) are retried with bounded backoff; contract
errors (4xx, owner-filter violations) re-raise immediately and are never retried.
"""

import httpx
import pytest
from cani_shared.vector.qdrant_client import (
    MissingOwnerFilterError,
    retry_transient,
)
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse


def _unexpected(status_code: int) -> UnexpectedResponse:
    return UnexpectedResponse(
        status_code=status_code, reason_phrase="x", content=b"", headers=httpx.Headers()
    )


class _Recorder:
    """Counts calls and sleeps without any real waiting."""

    def __init__(self, failures: list[Exception]):
        self._failures = list(failures)
        self.calls = 0
        self.slept: list[float] = []

    def fn(self):
        self.calls += 1
        if self._failures:
            raise self._failures.pop(0)
        return "ok"

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


def test_succeeds_first_try_no_sleep():
    rec = _Recorder(failures=[])
    assert retry_transient(rec.fn, sleep=rec.sleep) == "ok"
    assert rec.calls == 1
    assert rec.slept == []


def test_retries_network_fault_then_succeeds():
    rec = _Recorder(failures=[ResponseHandlingException(httpx.ConnectError("boom"))])
    assert retry_transient(rec.fn, sleep=rec.sleep) == "ok"
    assert rec.calls == 2
    assert rec.slept == [0.25]


def test_retries_5xx_then_succeeds():
    rec = _Recorder(failures=[_unexpected(503)])
    assert retry_transient(rec.fn, sleep=rec.sleep) == "ok"
    assert rec.calls == 2


def test_exhausts_attempts_and_reraises_last():
    fault = ResponseHandlingException(httpx.ReadTimeout("slow"))
    rec = _Recorder(failures=[fault, fault, fault])
    with pytest.raises(ResponseHandlingException):
        retry_transient(rec.fn, sleep=rec.sleep)
    assert rec.calls == 3
    # Exponential and bounded: two sleeps for three attempts, never one after the last.
    assert rec.slept == [0.25, 0.5]


def test_4xx_is_not_retried():
    rec = _Recorder(failures=[_unexpected(401), _unexpected(401)])
    with pytest.raises(UnexpectedResponse):
        retry_transient(rec.fn, sleep=rec.sleep)
    assert rec.calls == 1  # a bad API key does not get better with retries
    assert rec.slept == []


def test_owner_filter_violation_is_not_retried():
    # Fail-closed errors from the wrapper must surface immediately — retrying a tenant
    # isolation violation would be actively wrong, not just wasteful.
    rec = _Recorder(failures=[MissingOwnerFilterError("no owner")])
    with pytest.raises(MissingOwnerFilterError):
        retry_transient(rec.fn, sleep=rec.sleep)
    assert rec.calls == 1
