"""retry_transient: the retrieval-path hardening from the 2026-08-09 outage
(docs/sitreps/2026-08-09-qdrant-corruption-and-missing-backups.md), carried over to the
Postgres store. The contract under test: transient faults (connection-level, pool
exhaustion) are retried with bounded backoff; contract errors (SQL/programming errors,
owner-filter violations) re-raise immediately and are never retried.
"""

import psycopg
import psycopg_pool
import pytest
from cani_shared.vector.store import MissingOwnerFilterError, retry_transient


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


def test_retries_connection_fault_then_succeeds():
    rec = _Recorder(failures=[psycopg.OperationalError("connection refused")])
    assert retry_transient(rec.fn, sleep=rec.sleep) == "ok"
    assert rec.calls == 2
    assert rec.slept == [0.25]


def test_retries_pool_timeout_then_succeeds():
    rec = _Recorder(failures=[psycopg_pool.PoolTimeout("pool exhausted")])
    assert retry_transient(rec.fn, sleep=rec.sleep) == "ok"
    assert rec.calls == 2


def test_exhausts_attempts_and_reraises_last():
    fault = psycopg.OperationalError("server closed the connection unexpectedly")
    rec = _Recorder(failures=[fault, fault, fault])
    with pytest.raises(psycopg.OperationalError):
        retry_transient(rec.fn, sleep=rec.sleep)
    assert rec.calls == 3
    # Exponential and bounded: two sleeps for three attempts, never one after the last.
    assert rec.slept == [0.25, 0.5]


def test_sql_error_is_not_retried():
    rec = _Recorder(failures=[psycopg.ProgrammingError("relation does not exist")] * 2)
    with pytest.raises(psycopg.ProgrammingError):
        retry_transient(rec.fn, sleep=rec.sleep)
    assert rec.calls == 1  # a missing table does not get better with retries
    assert rec.slept == []


def test_owner_filter_violation_is_not_retried():
    # Fail-closed errors from the wrapper must surface immediately — retrying a tenant
    # isolation violation would be actively wrong, not just wasteful.
    rec = _Recorder(failures=[MissingOwnerFilterError("no owner")])
    with pytest.raises(MissingOwnerFilterError):
        retry_transient(rec.fn, sleep=rec.sleep)
    assert rec.calls == 1
