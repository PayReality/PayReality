# Milestone 4: Production Cutover Readiness Assessment

## Recommendation

# NOT READY FOR PRODUCTION CUTOVER

## Evidence supporting this decision

This is **not** a finding that the Azure platform is broken, unstable, or behaves differently from Render — the opposite is true, and the evidence is strong:

- Byte-identical API surface (92 paths / 112 operations) confirmed against Render.
- Zero errors under representative concurrent load; latency matches or beats Render at every measured percentile.
- Database, Blob Storage, and Key Vault access all confirmed working end-to-end, through the real managed-identity/RBAC paths, not shortcuts.
- OPA runs embedded and healthy, unmodified from its existing design.
- Container App restart and cold-start recovery both confirmed clean and fast.
- `terraform plan` shows zero drift; the deployment is fully reproducible from code.

**The platform is ready. The operation of that platform is not**, and cutting production traffic over today would mean running production on an environment where:

1. **Nothing pages anyone if it goes down** (Risk Register #1, High). This alone is disqualifying — a platform that works perfectly but fails silently is worse than a slower platform that fails loudly.
2. **The Evidence signing key is a placeholder value**, not real key material (Risk Register #2, High for functional correctness). Evidence records — a core product guarantee — would be signed incorrectly or fail to sign at all in this environment as it stands today.
3. **No one has ever actually restored this database from backup** (Risk Register #3, Medium-High). The configuration is correct; the muscle memory and the confidence that come from having done it once are not there yet.
4. **There is no application-level observability** (Risk Register #4, Medium) beyond container logs — recoverable, but a real gap for diagnosing a live incident quickly.

None of these require rebuilding anything. They are the specific, named list of what stands between "the infrastructure works" (proven) and "this is safe to run production on" (not yet).

## What "ready" will look like

- [ ] Baseline alert rules configured and wired to a real notification target (Container App health, Postgres availability, Key Vault errors — see Operational Readiness Report's recommendation).
- [ ] Milestone 5 complete: real Evidence signing key and other application secrets populated, no placeholder values remaining.
- [ ] One PITR restore drill performed and its result documented, even if the resulting server is then left in place per this program's no-deletion rule.
- [ ] A decision made (build or explicitly defer) on Application Insights instrumentation, so it's a choice, not an unnoticed gap.
- [ ] `prod.tfvars` confirmed to use the same collision-resistant Key Vault naming convention this milestone's predecessor introduced for staging, before any production `terraform apply` is attempted.

## What does not need to happen before cutover, based on this milestone's evidence

- No further performance validation — Azure already matches or exceeds Render's observed characteristics.
- No further API-parity testing — the two platforms are running byte-identical code, provably.
- No infrastructure redesign — every checklist item that passed, passed cleanly, on the first real attempt at exercising it.

## Scope boundary, restated

This assessment evaluates readiness only. Per this milestone's absolute rules, no DNS change, no customer traffic migration, and no production cutover has been performed or is being proposed here — this document exists to inform the decision, not to make it or begin acting on it.
