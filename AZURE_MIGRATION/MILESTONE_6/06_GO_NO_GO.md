# Milestone 6: Go / No-Go Checklist

Every item has an objective pass/fail criterion, evaluated against live evidence gathered this milestone. An item is marked **FAIL** only when the stated FAIL condition is actually true today, not out of caution.

---

**Azure environment exists**
PASS: A resource group with production Azure infrastructure exists and is reachable.
FAIL: No such resource group exists.
**Result: FAIL.** `az group list` shows only `rg-payreality-staging-cus`. No production resource group exists anywhere in the subscription.

---

**Production DNS**
PASS: A production hostname (frontend or API) resolves to an Azure endpoint.
FAIL: No production hostname resolves to any Azure endpoint.
**Result: FAIL.** `payreality.aisecurewatch.com` resolves to Vercel. No `api.*` record exists. `az containerapp hostname list` returns empty.

---

**SSL certificate**
PASS: A valid, trusted certificate is bound to a production Azure hostname.
FAIL: No certificate is bound to any Azure hostname reachable by production traffic.
**Result: FAIL.** No custom domain, therefore no certificate to evaluate.

---

**Production data present in Azure**
PASS: Azure's PostgreSQL database contains the organizations, agents, policies, and evidence records that reflect Render's actual production state.
FAIL: Azure's database contains only bootstrap/test data, and no mechanism exists to migrate real data.
**Result: FAIL.** Confirmed via repository search: no data-migration tooling exists. Azure's database holds one bootstrap organization and test artifacts from Milestones 3 and 5, not production data.

---

**CORS configured for real production origin**
PASS: The Container App's `CORS_ORIGIN` matches the real production frontend's origin.
FAIL: It matches a different or nonexistent origin.
**Result: FAIL.** Currently resolves to `https://staging.payreality.aisecurewatch.com`, a hostname with no DNS record, because the deployed Terraform environment is `"staging"`.

---

**Evidence signing key**
PASS: A real, non-placeholder signing key is installed and its derived public key is independently verifiable.
FAIL: The key is a placeholder or unverifiable.
**Result: PASS.** Confirmed Milestone 5, reconfirmed unchanged this milestone: the API's own `/v1/evidence/verification-keys` endpoint returns a public key matching an independently-computed value byte-for-byte.

---

**Admin API key**
PASS: A real, non-placeholder key is installed; correct key authenticates, incorrect key is rejected.
FAIL: The key is a placeholder, or authentication doesn't correctly distinguish correct from incorrect.
**Result: PASS.** Confirmed Milestone 5: real key → `200`; wrong key → `401`.

---

**Anthropic API key**
PASS: A real, non-placeholder key is installed.
FAIL: The value is still the Milestone 2 placeholder.
**Result: FAIL.** `az keyvault secret show ... anthropic-api-key` still returns `PENDING-MILESTONE-5-MANUAL-ENTRY`, reconfirmed this milestone. Does not block platform readiness; does block AI-assisted features.

---

**Managed Identity permissions**
PASS: Every identity holds exactly the roles it needs on Key Vault, Storage, and Container Registry, and no more.
FAIL: Any identity is missing a required role, or holds a broader role than its function needs.
**Result: PASS.** Confirmed unchanged from Milestone 5's full audit; re-verified live this milestone.

---

**Storage containers**
PASS: `uploads`, `evidence-exports`, and `authorization-receipts` all exist, private, RBAC-gated.
FAIL: Any container is missing or publicly accessible.
**Result: PASS.**

---

**Database backups / recovery**
PASS: Automated backups are running with a real, usable restore point, and a restore has actually been performed and its data verified at least once.
FAIL: Backups are not configured, or a restore has never been tested.
**Result: PASS.** The strongest-evidenced item in this program: a live restore drill (Milestone 5) produced a server whose data was queried and confirmed to match the source exactly.

---

**Monitoring (Log Analytics)**
PASS: Container logs and platform diagnostic logs are confirmed flowing with a live query.
FAIL: No live data confirmed.
**Result: PASS.**

---

**Alerting**
PASS: Alert rules exist against real metrics, and the notification delivery mechanism is confirmed working with a real test.
FAIL: No alert rules exist, or the notification path has never been tested.
**Result: PASS, with a disclosed coverage caveat.** Five rules exist; a real test notification was sent and confirmed delivered. Two rules were not organically triggered under live testing conditions (documented cause: metric semantics, not misconfiguration) — this is a test-coverage gap, not a FAIL condition as defined here.

---

**Application Insights**
PASS: Real application-level telemetry (requests, dependencies, traces) is confirmed present.
FAIL: Application Insights exists but receives no application-level data.
**Result: PASS.** Confirmed Milestone 5 with live data.

---

**Container App revisions**
PASS: The current revision is healthy and serving the real application image.
FAIL: The current revision is unhealthy or serving a placeholder.
**Result: PASS.**

---

**Rollback strategy — Azure-internal failure**
PASS: A rollback from a bad Azure deployment to a prior good one has been tested and confirmed working.
FAIL: No such test has been performed.
**Result: PASS.** Milestone 5's live rollback drill: bad image deployed, confirmed no outage occurred (old revision kept serving), rolled back via Terraform, confirmed full recovery.

---

**Rollback strategy — post-cutover DNS reversion**
PASS: A rollback from Azure-serving-real-traffic back to Render has been tested and confirmed to complete within an agreed time bound.
FAIL: This has never been tested because traffic has never been switched to Azure.
**Result: FAIL** (by definition — the scenario has never occurred). `04_ROLLBACK_RUNBOOK.md` documents the intended procedure and identifies which cutover method (DNS-based vs. application-config-based) determines the actual rollback speed, but the procedure itself is untested against a live incident.

---

**Render production untouched**
PASS: Render's backend and the production frontend both respond successfully, and no Render resource has been modified by this program.
FAIL: Render has been modified, disabled, or is not responding.
**Result: PASS.** `payreality-api.onrender.com/health` → `200`. `payreality.aisecurewatch.com` → `200`. No Render resource touched at any point across all six milestones.

---

## Tally

**FAIL: 6** (Azure production environment exists, Production DNS, SSL certificate, Production data present, CORS configured correctly, Anthropic API key, DNS-reversion rollback untested — 7 counting the untested rollback scenario)
**PASS: 11**

Six of the seven FAIL items trace back to two root causes: **no Azure production environment has ever been provisioned** (environment/DNS/SSL/CORS all downstream of this), and **no data migration mechanism exists** (production data, and by extension every validation area in `05_VALIDATION_PLAN.md` that depends on real data, downstream of this). The seventh (Anthropic key) is independent and narrower in impact.
