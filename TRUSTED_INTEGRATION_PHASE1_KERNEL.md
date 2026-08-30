# Trusted Integration Architecture, Phase 1: Integration Contract Kernel

Implements the Integration Contract kernel designed in the Trusted Integration Architecture report and its Founder Decisions & Design Closure Addendum. This document describes what actually shipped; the architecture rationale lives in those two documents, not repeated here.

## What this is

An `Integration` records that one external enterprise system exists (`server/app/db/models.py`'s `Integration` class) -- a label and an organization, nothing else. An `IntegrationContractVersion` records one immutable, versioned, human-approvable mapping from one external operation (`source_operation`, e.g. `"ChangeSupplierBankDetails"`) onto PayReality's canonical vocabulary: a fixed `canonical_action`, and deterministic field-path extraction rules (`resource_path`, `fact_subject_path`, `amount_path`, `currency_path`, `context_bindings`) for everything else a RuntimePolicy Condition could reference. No transformation language, no expressions, no scripting -- one hop per field, or nothing.

## What an APPROVED Integration Contract means, precisely

**It means**: a human holding `integration_contract.publish` reviewed this exact, already-immutable semantic mapping and accepted it as a truthful description of how this external operation should be interpreted.

**It does NOT mean**, and nothing in this codebase currently claims otherwise:

- an Adapter exists;
- runtime is using this mapping;
- an Agent is protected by it;
- enforcement exists;
- this mapping has ever observed a real operation;
- PayReality is non-bypassable.

Phase 2 is what will eventually wire a trusted Adapter's runtime construction of a canonical Intent through an `EnforcementBinding` selecting one APPROVED version. Until Phase 2 ships, creating an Integration or approving a Contract version has **zero effect** on `POST /v1/intents`, the Decision Engine, Evidence, the Authorization Receipt, or any other existing runtime path -- verified directly, not merely asserted (`tests/integration/test_integration_contract_lifecycle.py::test_creating_and_approving_contracts_has_zero_runtime_side_effects`).

## Lifecycle -- corrected from the original architecture report

```
draft -> validated -> approved -> retired
```

`validated` computes and freezes `content_hash` (over semantic fields only -- see below) and makes the row immutable from that point on. `approved` records `approved_by`/`approved_at`. Critically: **approving a new version never automatically retires a previously-approved sibling for the same operation.** Multiple `approved` versions of the same `(integration_id, source_operation)` may legitimately coexist (e.g. production still pinned to v1 while staging trials v2) -- there is no `active` state on this table at all, and no partial-unique-on-approved index (unlike `Policy`/`Certificate`). Selecting exactly one approved version to actually use belongs entirely to Phase 2's `EnforcementBinding`, which does not exist yet. Retirement is always explicit (`retire_contract_version`), never a side effect.

## Version identity and concurrency

Stable identity is `(integration_id, source_operation)` -- there is no separate `IntegrationContract` identity table; `version` is monotonic within that composite key, the same shape `RuntimePolicyRecord`'s own `policy_key`+`version` already uses with no separate "Policy identity" table either. `UNIQUE(integration_id, source_operation, version)` is the only DB-level uniqueness constraint.

Version allocation is concurrency-safe via a bounded retry (`MAX_VERSION_CREATE_ATTEMPTS = 3`, `services/integration_contract_service.py`), mirroring `deploy_policy`'s own established bounded-retry pattern for the identical class of race (PayReality 1.0 Audit finding G02): read the current max version for the tuple, attempt insert, catch the racing `IntegrityError`, roll back, retry with freshly re-read state. A losing attempt never leaks a raw `IntegrityError`/500 -- only the typed `ConcurrentVersionConflictError`, raised solely after every attempt is exhausted (practically unreachable outside deliberately adversarial concurrency). Proven against real PostgreSQL, not only SQLite (`tests/integration/test_integration_contract_concurrency.py`), including that unrelated `(integration_id, source_operation)` tuples never serialize against each other.

## Content hash

Computed once, at `draft` -> `validated`, over exactly: `source_operation`, `canonical_action`, `resource_path`, `fact_subject_path`, `amount_path`, `currency_path`, `context_bindings` -- canonical (sorted-key) JSON, SHA-256. Deliberately excludes `version` (identifies the historical row, not what the mapping means) and every lifecycle/provenance field, including `source_schema_fingerprint` (provenance, not semantic content -- see below). Two separately-versioned rows with byte-equivalent values for exactly the hashed fields hash identically; `context_bindings`' own key order never affects the result. Stored and API-visible in Phase 1; referenced by no Decision, Evidence, or Intent row, because nothing has evaluated against it yet -- Phase 2 is where `Evidence.integration_contract_content_hash` will be copied from the resolved version at evaluation time, the same dual FK-plus-hash mechanism `policy_bundle_hash` already uses for `Policy`.

## Source schema fingerprint

`source_schema_fingerprint` is a nullable, passive, optionally-populated column -- provenance only, excluded from `content_hash`, read by no code path. It exists solely as a clean hook for a future mapping-drift detector. No polling, monitoring, schema discovery, or drift job was built in this milestone.

## Authority-relevant context

Locked in as a schema/design decision, not yet enforced (no runtime path exists yet to enforce it): once Phase 2 wires a trusted Adapter's runtime Intent construction, only context keys explicitly present in an APPROVED version's own `context_bindings` may be extracted from the observed operation and allowed to influence Runtime Authority. Unbound caller-provided context may exist as non-authoritative metadata but must never reach a RuntimePolicy Condition as if it were trusted-mapped.

## RBAC

Two new permissions (`server/app/domain/rbac/permissions.py`), deliberately not reusing `runtime_policy.publish` -- mapping-semantic governance and RuntimePolicy governance may be delegated to different enterprise roles:

| Permission | Grants | Default holders |
|---|---|---|
| `integration_contract.manage` | Create Integration; create/edit a DRAFT version; trigger deterministic `validate` | Owner, Governance Administrator |
| `integration_contract.publish` | Approve a VALIDATED version; retire an APPROVED version | Owner, Governance Administrator |

`validate` requires only `manage`, not `publish` (Founder Decisions & Design Closure Addendum): validation authorizes nothing, it only confirms the mapping is deterministically well-formed. Approval remains the one governance boundary.

## API surface

All under `/v1/integrations`, additive, organization-scoped throughout (a cross-organization id returns not-found, never a distinguishable forbidden -- matching this codebase's established convention):

`POST /v1/integrations`, `GET /v1/integrations`, `GET /v1/integrations/{id}`, `POST /v1/integrations/{id}/contract-versions`, `GET /v1/integrations/{id}/contract-versions`, `GET /v1/integrations/{id}/contract-versions/{version_id}`, `PATCH /v1/integrations/{id}/contract-versions/{version_id}` (DRAFT only), `POST .../{version_id}/validate`, `POST .../{version_id}/approve`, `POST .../{version_id}/retire`.

No Phase 2 concept is exposed: no Integration Identity, no EnforcementBinding, no Adapter endpoints, no change to `POST /v1/intents` or any existing endpoint.

## What Phase 2 will add (recorded now, not built)

Integration Identity (a thin, certificate-bearing trusted-Adapter identity, reusing Agent's own Certificate-rotation shape, never a competing Agent model); `EnforcementBinding` (Agent x Integration Identity x Contract Version x environment, the first place exactly one APPROVED version per operation is actually selected for runtime use); `EnforcementBindingAgent` (the DB-enforced allow-list closing the origin-Agent binding invariant -- an Adapter may only attest origin for Agents it explicitly enumerates); `Intent.integration_contract_version_id` and `Intent.external_operation_id` (nullable FKs, deliberately not added in Phase 1 since nothing reads them yet); `environment` copied onto the historical Intent at submission time; the trusted-context runtime filter enforcing the authority-relevant context decision above; `Evidence.integration_contract_content_hash`; the new pre-evaluation "integration rejection" outcome (distinct from DENY) for a malformed or untrusted integration request; origin-Agent Adapter attestation semantics.

None of this exists yet. No PEP, gateway, workflow engine, CMDB, iPaaS, vendor connector, discovery engine, or capability discovery was built in this milestone either.
