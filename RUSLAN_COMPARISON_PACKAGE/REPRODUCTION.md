# Reproduction

## Environment requirements

- Python matching this repository's `server/.venv` (3.14 at the time this package was built).
- Dependencies from `server/requirements*.txt`, installed into that venv.
- A real, reachable `opa` binary on `PATH` (or the WinGet fallback path
  `tests/integration/conftest.py`'s own `opa_url` fixture already knows about) -- every trace-
  producing test uses a real, ephemeral OPA server, not a mock.
- For the migration/full-suite verification referenced in the matrix (not a trace file itself):
  a local PostgreSQL instance reachable via a `DATABASE_URL` environment variable
  (`docker compose up -d postgres` from the repository root brings up this repo's own disposable
  dev instance; credentials are internal-only and not reproduced here).
- Branch/commit this package was built from: `product-lifecycle-opa-timeout-reliability`, commit
  reported in this consolidation review's own final report (see that report for the exact hash).

## Commands, one per trace file

Run from the repository's `server/` directory. Each command regenerates the exact trace file named
next to it; the harness truncates and rewrites its own output file on each run (see each test
file's own `_TRACE_PATH` handling), so a fresh run reproduces the same file, not an appended copy.

```bash
# schedule_1_late_commitment_after_revocation.jsonl
# schedule_2_unresolved_outcome_after_revocation.jsonl
# material_action_binding_enforcement.jsonl
# capability_consumption_concurrency.jsonl
# (all four are schedules within the same run; the source file before
# splitting is tests/integration/_interop_evidencebound_recovery_v01_output/traces.jsonl)
pytest tests/integration/test_interop_evidencebound_recovery_v01.py -v

# operation_attempt_registration_concurrency.jsonl
# (source file before copying: tests/integration/_product_lifecycle_output/traces.jsonl)
pytest tests/integration/test_product_lifecycle_vertical_slice.py -k test_concurrent_first_attempts_at_new_business_operation_identity -v
```

The splitting script that separates the four schedules out of the single source `traces.jsonl`
into the four named files in `traces/` groups records by their own `"schedule"` field
(`"1"`, `"2"`, `"material"`, `"race"`); this is a mechanical relabeling of already-produced output,
not a re-execution or alteration of any recorded value.

## Regression coverage for the fix listed in the comparison matrix (row 10)

```bash
pytest tests/integration/test_product_lifecycle_vertical_slice.py -k test_issuance_freshness_rejection_never_orphans_the_business_operation_identity -v
```

## Full focused suite (everything touching this feature)

```bash
pytest tests/integration/test_product_lifecycle_vertical_slice.py tests/integration/test_product_lifecycle_vertical_slice_postgres.py tests/integration/test_interop_evidencebound_recovery_v01.py tests/integration/test_interop_trace_v0_1.py tests/integration/test_lifecycle_router_reachability.py -v
```

Postgres-backed tests in this list require the real database described above; they skip (not
fail) with an explicit message if it is unreachable.

## Migration chain verification

```bash
# From server/, with DATABASE_URL pointed at a real, empty Postgres database:
python -m alembic upgrade head
```

Confirms the full migration chain (including the graph-connectivity fix documented in this
review's own final report) applies cleanly to real PostgreSQL. A separate, non-empty-database
verification (seeding a realistic pre-existing `integration_contract_versions` row before
upgrading, confirming its backfill) was performed this session using a throwaway script, not
preserved as a permanent repository file; its method and result are described in this
consolidation review's own final report, not repeated here.
