"""Structured JSON logging with request/trace correlation.

Per docs/13-observability.md: every log line carries trace_id, and user identifiers are
hashed rather than logged raw. Never log raw document content or secrets here.
"""

from __future__ import annotations

import contextvars
import hashlib
import logging
import sys
import uuid

import structlog

_trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)


def new_trace_id() -> str:
    return uuid.uuid4().hex


def set_trace_id(trace_id: str) -> None:
    _trace_id_var.set(trace_id)


def get_trace_id() -> str:
    return _trace_id_var.get() or "unset"


def hash_user_id(user_id: str) -> str:
    """One-way, non-reversible identifier for logs — never log a raw owner_user_id."""
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]


def _add_trace_id(logger, method_name, event_dict):
    event_dict["trace_id"] = get_trace_id()
    return event_dict


def configure_logging(service_name: str) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_trace_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str):
    return structlog.get_logger(name)
