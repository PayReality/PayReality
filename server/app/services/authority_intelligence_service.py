"""Authority Intelligence Service (Authority Intelligence Program,
Phase 1): owns document ingestion (Blob Storage) and retrieval (Azure AI
Search) for the AI Authority Builder. Everything here is opt-in and
defensive, following the exact same pattern app/observability.py already
established for Application Insights: every function checks its own
settings field first and safely no-ops (never raises, never blocks the
existing Postgres-backed flow) when that piece of Azure AI infrastructure
isn't configured for this environment. Render, and any Azure environment
that hasn't had modules/ai-foundry / modules/ai-search applied yet, keep
working exactly as they do today.

Canonical ownership (per the program's own architecture): this module
owns document ingestion and document retrieval only. It never proposes
an Authority Graph itself (that's the AuthorityGraphExtractionProvider's
job) and never writes to any Runtime Governance / Runtime Authority /
Decision Engine table -- it only stores and retrieves the raw text that
an extraction provider is later handed.
"""

import logging
import uuid

from app.config import settings

logger = logging.getLogger("payreality.authority_intelligence")


def _blob_service_client():
    if not settings.azure_storage_account_url:
        return None
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    return BlobServiceClient(
        account_url=settings.azure_storage_account_url, credential=DefaultAzureCredential()
    )


def _search_client():
    if not settings.azure_ai_search_endpoint:
        return None
    from azure.identity import DefaultAzureCredential
    from azure.search.documents import SearchClient

    return SearchClient(
        endpoint=settings.azure_ai_search_endpoint,
        index_name=settings.azure_ai_search_index_name,
        credential=DefaultAzureCredential(),
    )


def _search_index_client():
    if not settings.azure_ai_search_endpoint:
        return None
    from azure.identity import DefaultAzureCredential
    from azure.search.documents.indexes import SearchIndexClient

    return SearchIndexClient(
        endpoint=settings.azure_ai_search_endpoint, credential=DefaultAzureCredential()
    )


def ensure_search_index(client=None) -> None:
    """Idempotent, called once at app startup (main.py's lifespan) --
    the same "log and continue, never crash boot" posture as the other
    three startup hooks (signing key, organisation owner, OPA policy
    reconciliation). A missing or misconfigured search endpoint here
    means Authority Builder falls back to reading documents from
    Postgres exactly as it always has -- never a startup failure.
    `client` is injectable, see upload_document_to_blob's docstring for
    why."""
    client = client or _search_index_client()
    if client is None:
        return
    try:
        from azure.search.documents.indexes.models import SearchIndex, SearchField, SearchFieldDataType

        existing = {idx.name for idx in client.list_indexes()}
        if settings.azure_ai_search_index_name in existing:
            return

        index = SearchIndex(
            name=settings.azure_ai_search_index_name,
            fields=[
                SearchField(name="id", type=SearchFieldDataType.String, key=True),
                SearchField(name="corpus_id", type=SearchFieldDataType.String, filterable=True),
                # Milestone 3 (Enterprise Surface Isolation): filterable,
                # required on every query -- confirmed unscoped before
                # this (MULTI_TENANT_ARCHITECTURE_VERIFICATION.md), and
                # already self-documented in AUTHORITY_INTELLIGENCE_
                # PHASE2_VALIDATION_REPORT.md as unsafe for a multi-
                # tenant rollout, which Milestone 2 made this platform.
                SearchField(name="organization_id", type=SearchFieldDataType.String, filterable=True),
                SearchField(name="document_id", type=SearchFieldDataType.String),
                SearchField(name="filename", type=SearchFieldDataType.String),
                SearchField(name="format", type=SearchFieldDataType.String),
                SearchField(name="content", type=SearchFieldDataType.String, searchable=True),
                SearchField(name="blob_path", type=SearchFieldDataType.String),
            ],
        )
        client.create_index(index)
        logger.info("authority_intelligence_search_index_created name=%s", settings.azure_ai_search_index_name)
    except Exception:
        logger.exception("authority_intelligence_search_index_setup_failed")


def upload_document_to_blob(
    corpus_id: uuid.UUID,
    document_id: uuid.UUID,
    filename: str,
    raw: bytes,
    organization_id: uuid.UUID | None = None,
    client=None,
) -> str | None:
    """Returns the blob path on success, None if Blob Storage isn't
    configured for this environment or the upload fails -- callers must
    treat None as "not available," not as an error to surface to the
    reviewer uploading a document. Documents are still stored in
    Postgres regardless (services/ai_authority_builder_service.py's
    add_document), so a failure here never loses the document.

    Milestone 3 (Enterprise Surface Isolation): the blob path is
    prefixed with the corpus's own organization -- confirmed to have no
    organization segment of any kind before this
    (MULTI_TENANT_ARCHITECTURE_VERIFICATION.md). "unscoped" (never a
    literal string an organization_id could ever equal, since that's
    always a real UUID) covers the same "no organization set" legacy
    scope every other org-scoping convention in this codebase treats as
    valid, not an error.

    `client` is injectable (same convention as every provider in this
    codebase, e.g. ClaudeAuthorityGraphExtractionProvider's own `client`
    param) so this function's request-building logic is unit-testable
    without a real Azure Storage account; production code never passes
    it, and gets the real client from settings instead."""
    client = client or _blob_service_client()
    if client is None:
        return None
    org_segment = str(organization_id) if organization_id is not None else "unscoped"
    blob_path = f"authority-corpora/{org_segment}/{corpus_id}/{document_id}-{filename}"
    try:
        container = client.get_container_client(settings.azure_storage_container_name)
        container.upload_blob(name=blob_path, data=raw, overwrite=True)
        return blob_path
    except Exception:
        logger.exception("authority_intelligence_blob_upload_failed corpus_id=%s document_id=%s", corpus_id, document_id)
        return None


def index_document(
    corpus_id: uuid.UUID,
    document_id: uuid.UUID,
    filename: str,
    format: str,
    text: str,
    blob_path: str | None,
    organization_id: uuid.UUID | None = None,
    client=None,
) -> None:
    """Best-effort: pushes one document's already-extracted text
    (domain/ai_policy_builder/text_extraction.py's extract_text, reused
    unchanged) into the search index. Never raises -- a failed indexing
    call falls back to Postgres-backed retrieval for this document at
    extraction time, exactly as if Azure AI Search were never
    configured at all.

    Milestone 3 (Enterprise Surface Isolation): organization_id is
    stamped onto the indexed document (empty string for the "no
    organization set" legacy scope, matching the field's own string
    type -- Azure AI Search has no null-able-UUID-filter concept as
    clean as this codebase's own `organization_id: uuid.UUID | None`
    convention, so an empty string plays that role here specifically).
    `client` is injectable, see upload_document_to_blob's docstring for
    why."""
    client = client or _search_client()
    if client is None:
        return
    try:
        client.upload_documents(
            documents=[
                {
                    "id": str(document_id),
                    "corpus_id": str(corpus_id),
                    "organization_id": str(organization_id) if organization_id is not None else "",
                    "document_id": str(document_id),
                    "filename": filename,
                    "format": format,
                    "content": text,
                    "blob_path": blob_path or "",
                }
            ]
        )
    except Exception:
        logger.exception("authority_intelligence_index_failed corpus_id=%s document_id=%s", corpus_id, document_id)


def _scoped_filter(corpus_id: uuid.UUID, organization_id: uuid.UUID | None) -> str:
    """Milestone 15 (Blob/Search tenant hardening, Workstream 11): the
    single place this OData filter is ever constructed. Milestone 13's
    audit found every existing caller applied it correctly, but noted
    the string-interpolated filter had no backstop if a future caller
    forgot to build it -- centralizing construction here means there is
    only one place to get it right, and only one place to review when
    the index's tenant-scoping logic ever needs to change. Both values
    are internally-generated UUIDs (never raw user input), so injection
    risk is structurally low, but this still isn't the place to relax
    that assumption."""
    org_value = str(organization_id) if organization_id is not None else ""
    return f"corpus_id eq '{corpus_id}' and organization_id eq '{org_value}'"


def retrieve_corpus_text(corpus_id: uuid.UUID, organization_id: uuid.UUID | None = None, client=None) -> str | None:
    """Retrieves every indexed document belonging to this corpus and
    concatenates them in the exact `=== FILE: <filename> ===` format
    services/ai_authority_builder_service.py's build_corpus_text()
    already produces from Postgres, so extraction's input contract is
    identical regardless of which path supplied it.

    Returns None -- not an empty string -- when Azure AI Search isn't
    configured or nothing is indexed for this corpus yet, so the caller
    can distinguish "use the Postgres fallback" from "this corpus
    genuinely has no text," which would otherwise look identical.

    Deliberately filtered by corpus_id, not a semantic top-K search:
    a corpus's extraction is defined (AI_AUTHORITY_BUILDER_ARCHITECTURE.md)
    as reasoning over every document in it as one body of evidence, not
    a relevance-ranked subset -- retrieval here is what makes that
    deterministic and traceable, not what makes it approximate.

    Milestone 3 (Enterprise Surface Isolation): the query filter also
    requires organization_id to match -- confirmed filtered only by
    corpus_id before this, with no tenant boundary in the index itself
    at all (MULTI_TENANT_ARCHITECTURE_VERIFICATION.md).

    Milestone 15 (Workstream 11 hardening): the query-side filter above
    is no longer the *only* thing standing between two tenants' documents
    -- every result is now independently re-checked against the expected
    scope below (`_scoped_filter` centralizes the query itself). This is
    the actual "backstop that doesn't depend solely on developer
    discipline" the milestone's own hardening proposal asked for: if the
    index's own filtering were ever bypassed or misconfigured, a
    cross-tenant document would be dropped here, fail-closed, rather than
    silently returned. `client` is injectable, see
    upload_document_to_blob's docstring for why."""
    client = client or _search_client()
    if client is None:
        return None
    try:
        results = client.search(search_text="*", filter=_scoped_filter(corpus_id, organization_id))
        parts = []
        for r in results:
            if str(r.get("corpus_id")) != str(corpus_id) or str(r.get("organization_id")) != (
                str(organization_id) if organization_id is not None else ""
            ):
                logger.error(
                    "authority_intelligence_scope_mismatch_dropped corpus_id=%s organization_id=%s "
                    "result_corpus_id=%s result_organization_id=%s",
                    corpus_id, organization_id, r.get("corpus_id"), r.get("organization_id"),
                )
                continue
            parts.append(f"=== FILE: {r['filename']} ===\n{r['content']}")
    except Exception:
        logger.exception("authority_intelligence_retrieval_failed corpus_id=%s", corpus_id)
        return None
    return "\n\n".join(parts) if parts else None
