"""Application Insights telemetry via the Azure Monitor OpenTelemetry Distro
(docs/13 §13.5/§13.7).

Deliberately optional: when APPLICATIONINSIGHTS_CONNECTION_STRING is unset every function
here is a no-op, so docker-compose runs, unit tests, and CI emit nothing to Azure and need
no credentials. Setting the connection string (via the cani-secrets Secret in AKS) is the
only thing that turns it on.

What this buys us over the existing structlog output: OpenTelemetry propagates W3C
traceparent across service boundaries, so a docs-api -> retrieval-worker query shows up in
App Insights as ONE distributed trace with its Postgres/Qdrant/OpenAI dependency calls
attached — the §13.5 "distributed tracing across hub, docs services, and workers"
requirement. The structlog JSON stream stays as-is for local dev and Container Insights.
"""

from __future__ import annotations

from cani_shared.config import Settings
from cani_shared.logging import get_logger

logger = get_logger(__name__)

_configured = False


def configure_telemetry(service_name: str, settings: Settings) -> bool:
    """Wire up Azure Monitor export + cross-service trace propagation. Returns True when
    telemetry was enabled. Safe to call once per process; later calls are ignored."""
    global _configured

    if not settings.telemetry_enabled:
        logger.info("telemetry_disabled", reason="no_connection_string", service=service_name)
        return False
    if _configured:
        return True

    # Imported lazily so the dependency is only touched when telemetry is actually on.
    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import Resource

    configure_azure_monitor(
        connection_string=settings.app_insights_connection_string,
        resource=Resource.create(
            {
                "service.name": service_name,
                # §13.7 custom dimensions: which spoke/environment a signal came from.
                "service.namespace": "cani",
                "deployment.environment": settings.env,
            }
        ),
        sampling_ratio=settings.telemetry_sampling_ratio,
        # Restrict stdlib-logging capture to the (unused) "cani" logger namespace. The
        # default captures the root logger, which turns the exporter's own azure.core
        # INFO lines into a self-feeding loop: every telemetry upload logs, that log is
        # exported, which logs again — observed as 55k+ AppTraces rows/2h of pure
        # "Transmission succeeded" noise and zero app events. App logs are structlog ->
        # stdout (PrintLoggerFactory, bypasses stdlib logging entirely) and reach the
        # workspace via Container Insights ContainerLogV2, not via this pipeline.
        logger_name="cani",
    )
    # httpx carries the traceparent on docs-api -> retrieval-worker calls, which is what
    # stitches the two services into a single distributed trace.
    HTTPXClientInstrumentor().instrument()

    _configured = True
    logger.info("telemetry_enabled", service=service_name, sampling_ratio=settings.telemetry_sampling_ratio)
    return True


def instrument_fastapi(app) -> None:
    """Emit a server span per request (adds request/latency/failure telemetry). No-op if
    telemetry was never configured, so the same call is safe in every environment."""
    if not _configured:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz")
