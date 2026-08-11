"""Application Insights instrumentation -- opt-in via
APPLICATIONINSIGHTS_CONNECTION_STRING, never active on Render.

Milestone 5 finding (AZURE_MIGRATION/MILESTONE_4_KNOWN issues): Azure
Container Apps does not auto-instrument Python applications the way App
Service does, so Application Insights received zero application-level
telemetry despite being fully provisioned. This module closes that gap
with OpenTelemetry auto-instrumentation (FastAPI, SQLAlchemy, httpx,
logging), gated entirely on whether a connection string is configured --
Render has no Application Insights resource and never sets this
environment variable, so `configure(app)` is a no-op there, byte-for-byte
the same behavior as before this milestone.
"""

import logging

from fastapi import FastAPI

from app.config import settings

logger = logging.getLogger("payreality.observability")


def configure(app: FastAPI) -> None:
    if not settings.applicationinsights_connection_string:
        return

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        configure_azure_monitor(connection_string=settings.applicationinsights_connection_string)
        FastAPIInstrumentor.instrument_app(app)
        logger.info("application_insights_instrumented")
    except Exception:
        # Telemetry is observability, not a request-serving dependency --
        # a misconfigured connection string should never be why the API
        # fails to boot. Same failure posture as main.py's other startup
        # hooks (signing key registration, owner bootstrap).
        logger.exception("application_insights_instrumentation_failed")
