# Module: ai-search

**Owner:** platform/infrastructure engineer. **Purpose:** the Authority Intelligence Program's retrieval layer -- backs `app/services/authority_intelligence_service.py`'s document indexing and corpus-text retrieval, replacing (when configured) Authority Builder's Postgres-only document read with a real Azure AI Search-backed one.

## What this module creates

One `azurerm_search_service` (`basic` SKU by default), RBAC-only (`local_authentication_enabled = false` -- no admin/query keys exist for this service at all). Two role assignments, both scoped to the Container App's own Managed Identity: `Search Service Contributor` (control-plane -- creating the index itself) and `Search Index Data Contributor` (data-plane -- indexing and querying documents within it).

## Why `basic`, not `free`

Azure AI Search's free tier has inconsistent Azure AD/RBAC data-plane authentication support across regions and API versions. Given this program's explicit, non-negotiable security requirement ("no API keys inside code... no shared credentials"), `basic` is the minimum tier that reliably supports RBAC-only access -- the free tier would otherwise force a choice between violating that requirement or accepting inconsistent behavior, neither acceptable for what's described as a production-ready implementation.

## What gets indexed, and what deliberately never does

Per the program's own instruction: uploaded governance documents (SOPs, delegation-of-authority memos, approval matrices, regulatory documents) via `authority_intelligence_service.index_document`, called from the existing document-upload path. **Runtime Evidence, Runtime Truth, and live customer/decision data are never indexed here** -- nothing in this module or the application code that calls it has a code path that could write any of those into this index; the only writer is the Authority Builder document-upload flow.

## The index itself is not a Terraform resource

`azurerm_search_service` provisions the service; the index schema (its fields) is created idempotently by application code at startup (`app/services/authority_intelligence_service.py::ensure_search_index`, called from `main.py`'s lifespan) rather than by Terraform, because the `azurerm` provider has no resource type for an individual search index. This mirrors the same "Terraform provisions the service, application code manages its own schema-shaped state idempotently" pattern already used for Postgres (Terraform creates the server and database; Alembic migrations, run by the application, manage the schema).

## Inputs / Outputs

Standard `resource_group_name`/`location`/`environment`/`tags`, plus `container_app_identity_principal_id` and `sku`. Outputs the service's query endpoint (not a secret -- RBAC is the actual credential) and its name.
