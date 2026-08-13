from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"

    database_url: str = "postgresql+psycopg://payreality@localhost:5432/payreality_dev"

    opa_url: str = "http://localhost:8181"
    opa_binary_path: str = "opa"

    evidence_signing_key_b64: str = ""
    evidence_signing_key_id: str = "signing_key_dev"

    # The original shared-secret superuser bypass (app.security.
    # verify_operator_key / app.dependencies.require_permission): every
    # existing integration keeps working through this unchanged.
    # RBAC.md's per-user/per-API-key permission system is additive to
    # this, not a replacement for it.
    admin_api_key: str = ""

    anthropic_api_key: str = ""

    # Empty means "no Application Insights" -- the app runs exactly as it
    # always has (Render never sets this). When present, app/observability.py
    # activates OpenTelemetry auto-instrumentation; see that module's own
    # docstring for why this is opt-in rather than always-on.
    applicationinsights_connection_string: str = ""

    # Authority Intelligence (Phase 1): all empty means "run exactly as
    # today" -- Authority Builder falls back to Anthropic (if configured)
    # then the Fake provider, precisely as it already does. Endpoints and
    # names only; Managed Identity authenticates to all three services,
    # so none of this is a credential and none of it belongs in Key Vault.
    azure_ai_foundry_endpoint: str = ""
    azure_ai_foundry_deployment_name: str = "gpt-5-mini"
    azure_ai_search_endpoint: str = ""
    # Milestone 3 (Enterprise Surface Isolation): "-v2", not the same
    # name as before -- deliberate, not cosmetic. Azure AI Search
    # doesn't support adding a field to an existing index in place, so
    # the only additive way to introduce the new organization_id field
    # (see authority_intelligence_service.ensure_search_index) is a new
    # index name, letting that function's existing idempotent
    # "check if exists, else create" logic create it fresh rather than
    # silently reusing the old, unscoped schema.
    azure_ai_search_index_name: str = "authority-intelligence-documents-v2"
    azure_storage_account_url: str = ""
    azure_storage_container_name: str = "uploads"

    intent_signature_window_seconds: int = 300

    cors_origin: str = "http://localhost:5173"

    # Phase 10 (RBAC.md): identity for the one-time Organisation Owner
    # bootstrap. Not used anywhere else -- once the Owner row exists, the
    # bootstrap hook is a no-op on every subsequent boot.
    organization_name: str = "PayReality"
    owner_email: str = "owner@payreality.local"


settings = Settings()
