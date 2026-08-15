# Historical Policy Binding, Production Verification

## What was performed

Deployed through the existing, established Azure process, unchanged from every prior milestone in this engagement: `az acr build` (new image, tagged `prod-a05383a`, the exact commit this change shipped from), `terraform apply` against the real production Terraform state (`environments/prod.tfvars`, plan reviewed before apply, exactly one change: the container image tag).

No test credentials (Operator Key or session token) were available in this environment, and no browser-automation tool exists in this session, unchanged from every prior verification round in this engagement. Neither was fabricated or bypassed. What follows is real, live verification of what's verifiable without them, stated precisely rather than inflated.

## Migration

`entrypoint.sh` runs `alembic upgrade head` automatically on every container start, before `uvicorn` starts, with `set -e` (any migration failure crashes the container before it ever becomes healthy). The new revision reached `Healthy` status:

```
az containerapp revision list ...
ca-payreality-api-prod-cus--0000006   Healthy   100   acrprprodtq1k.azurecr.io/payreality-api:prod-a05383a
```

A container that reached `Healthy` at 100% traffic, running this exact image, is direct evidence the migration succeeded: had it failed, `alembic upgrade head` would have exited non-zero, `set -e` would have stopped the script, and the container would never have started `uvicorn` or passed its `/health` check at all. This is not an assumption; it follows from reading `entrypoint.sh` itself.

## API schema

```
GET https://api.aisecurewatch.com/health -> {"status":"ok"}
```

Fetched the live production `/openapi.json` and confirmed directly (not assumed):
- `/v1/decisions/{decision_id}/policy-binding` is a registered path with a `GET` operation.
- `DecisionPolicyBindingResponse` is a registered schema with exactly the fields specified: `decision_id`, `policy_id`, `bundle_hash`, `bundle_version`, `compiled_at`, `activated_at`, `retired_at`, `policies`.
- `PolicyManifestEntry` is a registered schema.

## A real decision creates the expected binding

Not verified live in this session, for lack of credentials to submit a real signed intent against production. Verified instead, thoroughly, against a real (if SQLite-backed) database and a real OPA server in `HISTORICAL_POLICY_BINDING_TEST_REPORT.md`, exercising the exact same, unmodified production code path (`deploy_policy`, `submit_intent`, `get_decision_policy_binding`) this production deployment now runs. The distinction matters and is stated plainly: this confirms the code is correct and is now running in production, not that a specific live production decision has been observed to produce a specific live production binding.

## The historical decision can be reconstructed / changing the active policy does not change the historical result

Same basis as above: proven against real code, real OPA, and a real relational database in the test suite (`test_historical_stability_decision_survives_later_policy_version`, `test_bundle_stability_and_manifest_reconstruction`), not re-proven against live production data this session, for the same credential limitation.

## What was directly, live confirmed

```
GET https://api.aisecurewatch.com/v1/decisions/00000000-0000-0000-0000-000000000000/policy-binding
-> 401 {"detail":"authentication_required"}
```

This confirms, live, that the new endpoint's authorization gate is real and functioning: it requires a resolvable organization (Operator Key or session) before reaching any decision-lookup logic at all, exactly as designed for the tenant-isolation requirement, and refuses an unauthenticated request outright rather than leaking a 404-vs-401 distinction that could itself be an information signal.

## Honest summary

Migration: confirmed live, by necessary implication of the container's own health state, not by direct SQL inspection (no database credential/access available). API schema and the new endpoint's registration and auth gate: confirmed live, directly. The deeper functional claims (a live decision actually creates the expected binding; that binding survives a live redeploy) rest on the test suite's real, non-mocked verification of the identical code now running in production, not on a fresh live production transaction, because no credential existed in this session to create one. This is the same category of limitation disclosed in every verification round of this engagement to date, not a new or larger one.
