"""Telemetry must be strictly opt-in: with no APPLICATIONINSIGHTS_CONNECTION_STRING the
helpers are no-ops that never import or activate the Azure exporter. That property is what
keeps docker-compose, CI, and unit tests free of Azure credentials and egress.
"""

import pytest
from cani_shared import telemetry
from cani_shared.config import Settings
from fastapi import FastAPI

_BASE = {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_DB": "cani",
    "POSTGRES_USER": "cani",
    "POSTGRES_PASSWORD": "pw",
    "QDRANT_URL": "http://localhost:6333",
    "QDRANT_COLLECTION": "c",
    "AZURE_STORAGE_CONNECTION_STRING": "UseDevelopmentStorage=true",
    "CANI_TOKEN_SIGNING_SECRET": "x" * 32,
    "CANI_SESSION_SECRET": "y" * 32,
}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**_BASE, **overrides})


@pytest.fixture(autouse=True)
def _reset_configured(monkeypatch):
    # configure_telemetry latches on a module global; isolate each test from the others.
    monkeypatch.setattr(telemetry, "_configured", False)


def test_disabled_when_connection_string_unset():
    assert _settings().telemetry_enabled is False
    assert telemetry.configure_telemetry("svc", _settings()) is False


def test_enabled_flag_flips_with_connection_string():
    s = _settings(APPLICATIONINSIGHTS_CONNECTION_STRING="InstrumentationKey=abc;IngestionEndpoint=https://x/")
    assert s.telemetry_enabled is True


def test_configure_does_not_touch_azure_exporter_when_disabled(monkeypatch):
    """Guards the opt-in contract at the seam that matters: if the exporter were
    configured despite no connection string, this blows up instead of silently
    shipping telemetry (or failing) in CI."""

    def _boom(*args, **kwargs):
        raise AssertionError("configure_azure_monitor must not run without a connection string")

    monkeypatch.setattr("azure.monitor.opentelemetry.configure_azure_monitor", _boom)
    assert telemetry.configure_telemetry("svc", _settings()) is False


def test_instrument_fastapi_is_noop_when_not_configured():
    # Must not raise even though telemetry was never configured.
    telemetry.instrument_fastapi(FastAPI())
