import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.logging_config import configure_logging
from app.routers import (
    agents,
    ai_authority_builder,
    ai_policy_builder,
    assurance,
    auth as auth_router,
    capability_tokens,
    enforcement_bindings,
    enterprise_systems,
    evidence,
    facts,
    integration_contracts,
    integration_identities,
    integration_runtime,
    intents,
    organization as organization_router,
    organization_lifecycle,
    organization_structure,
    policies,
    policy_drafting,
    policy_simulation,
    principals,
    runtime_policies,
    runtime_policy_lifecycle,
    sandbox,
    users as users_router,
)
from app.security import observability_middleware
from app import observability as azure_observability

configure_logging(level="INFO" if settings.environment == "production" else "DEBUG")
logger = logging.getLogger("payreality.startup")


def _register_current_signing_key() -> None:
    """Seeds the signing-key registry (EVIDENCE_KEY_ROTATION.md) with
    whatever key is currently configured. Idempotent and safe to run on
    every boot: does nothing if this key_id is already registered, and
    is what actually performs a rotation the moment a process starts
    with a new EVIDENCE_SIGNING_KEY_B64/_ID.

    Deliberately does not raise on failure (DB unreachable at boot,
    etc.): this registry is what makes verification correct across a
    future rotation, not something request-serving depends on right
    now, so a transient failure here logs a warning and lets the app
    boot rather than crash-looping the whole service. verify_evidence's
    fallback path keeps working exactly as it did before this table
    existed if the registry entry is ever missing."""
    if not settings.evidence_signing_key_b64:
        logger.warning("signing_key_not_configured: skipping signing-key registry startup check")
        return
    try:
        from app.db.session import SessionLocal
        from app.domain.evidence.signing import public_key_b64_from_signing_key_b64
        from app.services.signing_key_service import ensure_current_key_registered

        db = SessionLocal()
        try:
            public_key = public_key_b64_from_signing_key_b64(settings.evidence_signing_key_b64)
            ensure_current_key_registered(db, settings.evidence_signing_key_id, public_key)
        finally:
            db.close()
    except Exception:
        logger.exception("signing_key_registration_failed_at_startup")


def _bootstrap_organisation_owner() -> None:
    """RBAC.md: idempotently creates the one Organisation and its Owner
    user on first boot after this migration. Same failure posture as
    _register_current_signing_key: never raises, since a transient DB
    issue at boot shouldn't crash-loop the whole service, and every
    subsequent boot will simply try again."""
    try:
        from app.db.session import SessionLocal
        from app.services.organization_service import ensure_owner_bootstrapped

        db = SessionLocal()
        try:
            ensure_owner_bootstrapped(db)
        finally:
            db.close()
    except Exception:
        logger.exception("organisation_owner_bootstrap_failed_at_startup")


def _reconcile_opa_with_active_policies() -> None:
    """OPA runs embedded in this same container and its REST-loaded
    policies live only in its own process memory (no bundle persistence
    configured); a restart -- a deploy, a crash, or (on the free plan)
    an idle spin-down -- silently wipes whatever was live, and nothing
    else re-uploads it. Without this, every real Intent after a restart
    evaluates against an undefined "authorization" package and comes
    back HUMAN_REVIEW/"undetermined" no matter the input, indistinguish-
    able from a legitimate no-match result. Same failure posture as the
    other two startup hooks: never raises, logs and lets the app boot,
    since the next restart will simply retry."""
    try:
        from app.db.session import SessionLocal
        from app.services.runtime_policy_service import reconcile_opa_with_active_policies

        db = SessionLocal()
        try:
            reconcile_opa_with_active_policies(db, opa_url=settings.opa_url)
        finally:
            db.close()
    except Exception:
        logger.exception("opa_policy_reconciliation_failed_at_startup")


def _ensure_authority_intelligence_search_index() -> None:
    """Authority Intelligence Program, Phase 1: idempotent Azure AI
    Search index creation, no-ops entirely if
    AZURE_AI_SEARCH_ENDPOINT isn't configured for this environment. Same
    failure posture as the other three startup hooks: never raises, logs
    and lets the app boot -- Authority Builder's Postgres-backed fallback
    keeps working regardless of whether this succeeds."""
    try:
        from app.services.authority_intelligence_service import ensure_search_index

        ensure_search_index()
    except Exception:
        logger.exception("authority_intelligence_search_index_failed_at_startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _register_current_signing_key()
    _bootstrap_organisation_owner()
    _reconcile_opa_with_active_policies()
    _ensure_authority_intelligence_search_index()
    yield


def _validate_production_config() -> None:
    """Refuse to boot in production with missing/default secrets rather than
    running degraded: e.g. silently unable to sign Evidence, or exposing
    every policy/resolution endpoint with no operator gate."""
    if settings.environment != "production":
        return
    missing = []
    if not settings.evidence_signing_key_b64:
        missing.append("EVIDENCE_SIGNING_KEY_B64")
    if not settings.admin_api_key:
        missing.append("ADMIN_API_KEY")
    if not settings.cors_origin or settings.cors_origin == "http://localhost:5173":
        missing.append("CORS_ORIGIN")
    if missing:
        raise RuntimeError(
            "Refusing to start with ENVIRONMENT=production while these are "
            f"missing or left at their dev default: {', '.join(missing)}"
        )


def create_app() -> FastAPI:
    _validate_production_config()

    app = FastAPI(
        title="PayReality Runtime Authority API",
        version="0.1.0",
        description=(
            "Deterministic policy evaluation (OPA/Rego), ED25519-signed "
            "Evidence, and the human-review resolution flow for AI agent "
            "financial actions. Full schema at /openapi.json, interactive "
            "docs at /docs."
        ),
        lifespan=lifespan,
    )

    azure_observability.configure(app)

    app.middleware("http")(observability_middleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-PayReality-Key-Id",
            "X-PayReality-Signature",
            "X-PayReality-Operator-Key",
            # Milestone 2 (Multi-Tenant Foundation): required alongside the
            # Operator Key on every org-scoped request -- see
            # dependencies.get_current_organization's own docstring.
            "X-PayReality-Organization-Id",
        ],
    )

    @app.get("/health")
    def health():
        """Liveness only: process is up and serving. No dependency calls,
        see /health/ready for database and OPA reachability."""
        return {"status": "ok"}

    @app.get("/version")
    def version():
        """Which build is actually running. RENDER_GIT_COMMIT is set
        automatically by Render on every deploy; falls back to 'unknown'
        outside Render (e.g. running via docker-compose)."""
        return {
            "version": app.version,
            "commit": os.environ.get("RENDER_GIT_COMMIT", "unknown"),
        }

    @app.get("/health/ready")
    def health_ready():
        """Readiness: checked live on every call, not cached. A false
        'ready' here is worse than a slow one, since a load balancer or
        orchestrator will route real traffic based on this.

        Each check runs with a hard overall deadline via a worker thread,
        not just the engine's own connect_timeout: psycopg retries every
        address a hostname resolves to (e.g. both ::1 and 127.0.0.1 for
        "localhost"), each getting its own connect_timeout budget, so an
        unreachable "localhost" database took 14+ seconds to fail even
        with connect_timeout=5, caught by actually timing this endpoint
        against a real unreachable database, not assumed from the config
        alone. The .result(timeout=...) below bounds the HTTP response
        itself regardless of how many addresses get tried underneath."""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

        def _check_database() -> bool:
            from sqlalchemy import text

            from app.db.session import SessionLocal

            db = SessionLocal()
            try:
                db.execute(text("SELECT 1"))
                return True
            finally:
                db.close()

        def _check_opa() -> bool:
            from app.opa_client import HttpOpaClient

            return HttpOpaClient().health()

        # Not a `with` block deliberately: ThreadPoolExecutor.__exit__ calls
        # shutdown(wait=True), which would block this response on the same
        # slow-to-fail connection attempt we're trying to bound. A future
        # that times out here keeps running in its worker thread in the
        # background (Python can't force-kill a thread), but that no
        # longer blocks the HTTP response, which is the actual guarantee
        # this endpoint needs to make.
        checks = {"database": False, "opa": False}
        pool = ThreadPoolExecutor(max_workers=2)
        db_future = pool.submit(_check_database)
        opa_future = pool.submit(_check_opa)

        try:
            checks["database"] = db_future.result(timeout=3)
        except FutureTimeoutError:
            logger.warning("readiness_check_timed_out component=database")
        except Exception:
            logger.exception("readiness_check_failed component=database")

        try:
            checks["opa"] = opa_future.result(timeout=3)
        except FutureTimeoutError:
            logger.warning("readiness_check_timed_out component=opa")
        except Exception:
            logger.exception("readiness_check_failed component=opa")

        pool.shutdown(wait=False)
        ready = all(checks.values())
        return JSONResponse(status_code=200 if ready else 503, content={"ready": ready, "checks": checks})

    app.include_router(principals.router)
    app.include_router(agents.router)
    app.include_router(policies.router)
    app.include_router(intents.router)
    app.include_router(evidence.router)
    app.include_router(runtime_policies.router)
    app.include_router(runtime_policy_lifecycle.router)
    app.include_router(runtime_policy_lifecycle.dashboard_router)
    app.include_router(integration_contracts.router)
    app.include_router(integration_identities.router)
    app.include_router(enforcement_bindings.router)
    app.include_router(integration_runtime.router)
    app.include_router(policy_simulation.router)
    app.include_router(ai_policy_builder.router)
    app.include_router(ai_authority_builder.router)
    app.include_router(policy_drafting.router)
    app.include_router(auth_router.router)
    app.include_router(users_router.router)
    app.include_router(organization_router.router)
    app.include_router(organization_lifecycle.router)
    app.include_router(enterprise_systems.router)
    app.include_router(organization_structure.business_units_router)
    app.include_router(organization_structure.departments_router)
    app.include_router(organization_structure.teams_router)
    app.include_router(facts.router)
    app.include_router(capability_tokens.router)
    app.include_router(assurance.router)
    app.include_router(sandbox.router)

    return app


app = create_app()
