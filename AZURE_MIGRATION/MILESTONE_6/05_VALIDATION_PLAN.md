# Milestone 6: Production Validation Plan

For each area: the exact check to run (to be executed as part of Step 7 of `03_PRODUCTION_RUNBOOK.md`, after real cutover), and its **current** status — already validated at the platform level in prior milestones, or blocked today on a gap named in `01_PRODUCTION_AUDIT.md`. Distinguishing these two matters: a "platform validated" item needs re-confirmation with real traffic, not re-invention; a "blocked" item cannot be meaningfully validated until its blocker closes.

## Authentication

**Check:** real user login via `/v1/auth/login` with actual production credentials; confirm session/token issuance; confirm the operator-key path (`X-PayReality-Operator-Key`) still authenticates the real admin key.
**Status:** Platform-validated. The operator-key path was tested with the real (Milestone 5) admin key: correct key → `200`, wrong key → `401`. Real end-user login has not been exercised because Azure's database has no real production users yet (blocked on data migration).

## Policy compilation

**Check:** publish a real runtime policy; confirm it compiles to Rego and loads into OPA (`curl http://localhost:8181/v1/policies` from inside the container shows a non-empty result).
**Status:** **Blocked.** Confirmed in Milestone 4 and unchanged since: `/v1/policies` returns `{"result":[]}` — no policy has ever been published in this environment, because doing so requires the real admin/owner access that data migration would bring, and no representative test policy has been created as a substitute.

## Runtime Authority

**Check:** submit an intent that depends on a specific Authority/Mandate scope; confirm the decision correctly reflects that scope (an in-scope action is not incorrectly denied, an out-of-scope action is not incorrectly allowed).
**Status:** **Blocked** — depends on real (or representative test) Authority data, which depends on Policy compilation above.

## Runtime Truth

**Check:** confirm a decision's recorded outcome (ALLOW / DENY / HUMAN_REVIEW) matches what OPA actually evaluated, not a cached or stale result — i.e., the "truth" the system acted on is the truth it recorded.
**Status:** **Blocked** — same dependency chain as Runtime Authority above.

## Evidence generation

**Check:** confirm a real decision produces a signed Evidence record with the correct `key_id` (`signing_key_azure_prod_v1`), correct hash chain (`previous_hash` linking to the prior record), and a signature that verifies against the registered public key.
**Status:** **Partially validated.** The signing mechanism itself is cryptographically proven correct (Milestone 5: the API's public-key endpoint matches an independently-computed value). A real Evidence record has not been generated end-to-end because no real decision has been made yet (blocked upstream on Policy compilation).

## Evidence verification

**Check:** `POST /v1/evidence/{evidence_id}/verify` against a real record; confirm it returns a valid verification result; confirm `GET /v1/evidence/chain/verify` correctly walks and validates the full chain.
**Status:** **Blocked** — nothing to verify yet without real Evidence records (see above).

## Blob uploads

**Check:** through the actual application API (not the infrastructure-level RBAC test already performed), upload a document, confirm it lands in the `uploads` container, and confirm it's retrievable through the app's own document endpoints.
**Status:** **Partially validated.** The storage account itself was proven correct at the infrastructure level (Milestone 4: upload/download/delete via RBAC, byte-identical content). The application's own upload *endpoints* have not been exercised, since that requires an authenticated user session (blocked on data migration/real users).

## PostgreSQL persistence

**Check:** write a record through the application, restart the Container App, confirm the record persists.
**Status:** Platform-validated, repeatedly. Alembic migrations have run correctly and idempotently across multiple real restarts (Milestones 3 and 5); the Milestone 5 backup-restore drill independently confirmed data durability by verifying a restored copy matched the source exactly.

## OPA evaluation

**Check:** submit intents covering at least one expected ALLOW, one expected DENY, and one expected HUMAN_REVIEW outcome; confirm each matches policy intent.
**Status:** **Blocked.** OPA itself is confirmed healthy and embedded correctly (Milestones 3–5), but with zero policies loaded, no real evaluation has ever been exercised in this environment — this is the same underlying gap as Policy compilation above, viewed from the runtime side.

## Health endpoints

**Check:** `/health` and `/health/ready` both return `200`; `/health/ready` genuinely checks OPA and database reachability, not a hardcoded response.
**Status:** Fully validated, repeatedly, across every milestone including this one's audit.

## OpenTelemetry traces

**Check:** generate real traffic; confirm `requests`, `dependencies`, and `traces` all show fresh data in Application Insights.
**Status:** Platform-validated (Milestone 5: real data confirmed in all three). Should be re-confirmed with real production request volume post-cutover, but the instrumentation itself is proven working.

## Alert verification

**Check:** confirm all five alert rules are `Enabled`; confirm the notification path fires for at least a synthetic test; where feasible, confirm at least one rule fires from a genuine (not CLI-simulated) condition.
**Status:** Platform-validated for configuration and notification delivery (Milestone 5: a real test email was sent and confirmed `Succeeded`). Two of five rules were not organically triggered in live testing — see Milestone 5's Risk Register for the specific reasons (metric semantics, not configuration defects). Recommend re-attempting these two under real production load post-cutover, when genuine crash/high-CPU conditions are more likely to occur naturally than they were against a synthetic `/health`-only test.

## Summary

Of twelve validation areas: **five are fully platform-validated**, **three are partially validated** (the mechanism is proven, the specific end-to-end path isn't yet exercised), and **four are blocked** on the same underlying dependency — the absence of real production data and at least one real, published policy in Azure. This is not four independent gaps; it is one gap (data migration, `01_PRODUCTION_AUDIT.md`) with four downstream symptoms.
