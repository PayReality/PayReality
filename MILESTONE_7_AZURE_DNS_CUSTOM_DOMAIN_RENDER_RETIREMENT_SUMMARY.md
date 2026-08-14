# Milestone 7: Azure DNS, Custom Domains and Render Retirement

**Status: CUTOVER COMPLETE AND LIVE-VALIDATED. `api.aisecurewatch.com` now resolves to Azure, serves valid HTTPS with a real trusted certificate, and passes full production validation. Render remains running, deliberately, as a rollback target through a real observation window before any retirement action is taken.**

Every fact below is labeled VERIFIED, INFERRED, or UNVERIFIED, per this milestone's own rule. VERIFIED means checked directly against a live system in this session. INFERRED means a conclusion drawn from verified facts but not itself directly observed. UNVERIFIED means stated in a document or assumed by a prior session, not independently checked here.

## Phase 1: Read-only verification (complete)

### DNS provider and nameservers

**VERIFIED.** `aisecurewatch.com`'s nameservers are `dns1.registrar-servers.com` and `dns2.registrar-servers.com`, Namecheap's own default DNS hosting. The zone is not on Cloudflare DNS and not on Azure DNS, despite `api.aisecurewatch.com`'s current target passing through a Cloudflare-fronted Render edge. **Azure DNS does not exist anywhere in this subscription** (`az network dns zone list` returns empty).

### Current DNS records

| Hostname | Type | Target | Status |
|---|---|---|---|
| `aisecurewatch.com` | A | `216.198.79.1` (Vercel) | VERIFIED |
| `www.aisecurewatch.com` | CNAME | Vercel edge (`*.vercel-dns-017.com`) | VERIFIED |
| `payreality.aisecurewatch.com` | A | `76.76.21.21` (Vercel) | VERIFIED, and new this session: this hostname was not in the milestone's own named list of four domains, but is real, live, and is the actual product application's domain (the one `CORS_ORIGIN` names), distinct from the marketing site at the bare domain |
| `demo.aisecurewatch.com` | CNAME | Vercel edge (`*.vercel-dns-017.com`) | VERIFIED |
| `api.aisecurewatch.com` | CNAME | `payreality-api.onrender.com`, itself a verified custom domain on Render's own service (not a bare proxy) | VERIFIED, including via the Render API directly: `customDomain.name = "api.aisecurewatch.com"`, `verificationStatus = "verified"` |
| `api.aisecurewatch.com` current TTL | n/a | 1799 seconds (~30 minutes) | VERIFIED, via `Resolve-DnsName` |
| MX | n/a | `mx1.improvmx.com` (10), `mx2.improvmx.com` (20) | VERIFIED, real email routing that must not be touched |
| TXT (root) | n/a | SPF for ImprovMX, three Google site-verification strings | VERIFIED, must not be touched |

### Certificates

**VERIFIED**, via direct TLS handshake against all four hostnames:

| Hostname | Issuer | Expires |
|---|---|---|
| `aisecurewatch.com` | Let's Encrypt (Vercel-managed) | 2026-10-05 |
| `www.aisecurewatch.com` | Let's Encrypt (Vercel-managed) | 2026-10-21 |
| `demo.aisecurewatch.com` | Let's Encrypt (Vercel-managed) | 2026-11-06 |
| `api.aisecurewatch.com` | Google Trust Services (Render-managed) | 2026-10-23 |

None expiring soon; none require action independent of this migration.

### Azure service bindings

**VERIFIED, all empty**: `az containerapp hostname list` returns `[]` for both the staging and prod Container Apps; `az containerapp env certificate list` returns nothing; `az network dns zone list`, `az afd profile list`, `az network application-gateway list`, and `az network traffic-manager profile list` all return nothing anywhere in the subscription. Azure has no domain, certificate, Front Door, Application Gateway, or Traffic Manager configuration of any kind today.

**VERIFIED**: the prod Container App's domain ownership verification ID (needed for every later step) is `56A0FFA54D939E541407075F061240084F1C02D2C7A19714B9DB5C136CDE94DC`.

### Render dependencies

**VERIFIED, via the Render API directly** (a `RENDER_API_KEY` exists in this environment):
- One web service, `payreality-api` (`srv-d9idj8t8nd3s739o5dsg`), free plan, auto-deploys on every push to `main`, last updated 2026-08-12.
- `api.aisecurewatch.com` is a verified custom domain on this exact service.
- One Postgres database, `payreality-db` (free plan), created 2026-07-25. **`expiresAt: 2026-08-24T15:10:03Z`, eleven days from today.** This is a hard, external deadline that exists regardless of anything else in this milestone: Render will delete this database automatically on that date unless it is upgraded to a paid plan first. It directly limits how long Render can remain a credible rollback target with working data.

### Vercel

**VERIFIED**, via a Vercel API token provided for this milestone. Four projects exist, not the single "the frontend" this milestone's own framing implied:

| Project | Bound domain | Repo |
|---|---|---|
| `aisecurewatch-website` | `aisecurewatch.com`, `www.aisecurewatch.com` | `Payreality-website` |
| `pay-reality-demo` | `payreality.aisecurewatch.com` | `PayReality` |
| `payreality-demo-public` | `demo.aisecurewatch.com` | `PayReality` |
| `demo` | none (only its own `*.vercel.app`) | `Verifiable-Intent-Certificate`, orphaned/unrelated, not touched by this migration |

`pay-reality-demo` (the real product app) has a `VITE_API_URL` environment variable set for the `production` target. It is a Vercel "sensitive" type variable, which **cannot be read back via the API by design**, only overwritten. Its current value is therefore genuinely UNVERIFIED, matching the same open question Milestone 4/5 flagged, now confirmed to be structurally unreadable rather than just inconvenient to check. The cutover plan below treats this as a non-issue by explicitly setting it during cutover regardless of its current value, which is idempotent either way.

### Access confirmed available for this milestone

- **Azure**: full `az` CLI access, as in every prior milestone.
- **Render**: a working API key, sufficient to inspect the service and its custom domain, and later to manage retirement.
- **Vercel**: a working API token, sufficient to read project/domain configuration and write environment variables.
- **Namecheap** (the actual DNS host): no API credential. The user is adding records manually at each step; Namecheap's own site is under maintenance as of this writing, which is blocking the very first record.

## Phase 2: Azure DNS design

**Decision: hybrid. Keep the DNS zone at Namecheap; do not migrate to Azure DNS.**

Why, concretely: this domain has real, working, non-migration-related infrastructure that a full zone migration would put at risk for zero benefit, namely the MX/SPF records behind real email (ImprovMX) and three Google site-verification TXT records. A full migration to Azure DNS means recreating every one of these records correctly on a new nameserver set and changing the nameservers at the registrar, the single highest-blast-radius DNS operation that exists, for a domain where only one subdomain out of five is actually moving to Azure infrastructure. The other four (`aisecurewatch.com`, `www`, `payreality`, `demo`) are staying on Vercel and were never in scope. A hybrid approach, where the zone stays exactly where it is and only the `api` subdomain's target changes, is strictly less risky and achieves the identical end state for the one thing actually moving.

**Zone layout**: unchanged. Namecheap remains authoritative for `aisecurewatch.com`.

**Record layout, current versus target**:

| Record | Current | Target |
|---|---|---|
| `asuid.api.aisecurewatch.com` TXT | does not exist | Azure's domain ownership verification string (new, permanent, needed for both initial binding and every future managed-certificate renewal) |
| `api.aisecurewatch.com` CNAME | `payreality-api.onrender.com` | `ca-payreality-api-prod-cus.redisland-66e4c9a9.centralus.azurecontainerapps.io` |
| Everything else | unchanged | unchanged |

**TTL strategy**: the `api` record's live TTL is already a relatively short 1799 seconds (~30 minutes), confirmed directly. A textbook cutover lowers this further (to, say, 300 seconds) and waits out one full old-TTL cycle before changing the target, so the lower TTL itself is honored by every resolver by the time the real change happens. Given this cutover is happening within a single active working session with the user available throughout, and 30 minutes is already short by DNS standards (not the 24-48 hour worst case a neglected zone can have), this plan accepts the existing TTL rather than adding a multi-hour waiting step, and discloses that choice here rather than silently skipping it. Once the cutover is stable, no TTL change back is needed; 1799 seconds is a reasonable steady-state value.

**Rollback strategy**: revert the CNAME to `payreality-api.onrender.com`. Because Render is kept running, untouched, throughout, this fully reverses the cutover within one TTL window, no data reconciliation needed provided the rollback happens before any write meaningfully diverges between the two backends (both point at logically separate databases, so a rollback after real writes have landed in Azure's Postgres would need the same reconciliation any dual-write scenario needs; this plan's own validation gate exists specifically to catch problems before that becomes a real concern).

## Phase 3: Certificate strategy

**Decision: Azure Container Apps' built-in free Managed Certificate**, not a customer-uploaded certificate, not Key Vault-issued, and no Front Door or Application Gateway in front of it.

Why: this is a single backend API with no CDN, WAF, or multi-origin routing requirement, so the extra infrastructure Front Door or Application Gateway would add has no corresponding need here. Container Apps' own Managed Certificate feature is free, auto-renewing (Azure renews automatically well before expiry, no operator action required), and requires no private key material to ever leave Azure, matching this platform's existing identity-first, no-shared-secret posture for everything else.

**A real Terraform limitation, disclosed rather than worked around badly**: the pinned `azurerm` provider (~3.117, the same version constraint every other module in this project already depends on) exposes `azurerm_container_app_custom_domain`, which requires an existing certificate resource ID, and `azurerm_container_app_environment_certificate`, which only accepts a customer-provided PFX blob and password. **Neither resource can express "look up or automatically provision a free Managed Certificate," which is CLI/Portal-only in this provider version**, confirmed directly against the provider's own schema, not assumed. This is a genuine, known gap in the Terraform provider itself, not a workaround avoided for convenience. The custom domain and its certificate will therefore be bound via `az containerapp hostname bind --validation-method CNAME` (which handles lookup-or-create of the managed certificate in one step), outside Terraform, and documented here as a deliberate, narrow exception to this project's otherwise-consistent "everything through Terraform" discipline, for the one feature Terraform genuinely cannot express.

**Renewal and expiry**: Azure manages Managed Certificate renewal automatically, provided the `asuid.api` TXT ownership record remains in place indefinitely (Azure re-validates ownership on every renewal, not just at initial binding) and the CNAME keeps pointing at the Container App. No manual renewal action is expected under normal operation; the operations runbook below still documents what to check and how to recover if renewal ever silently fails.

## Phase 5 (design): DNS cutover plan

Preparation -> validation -> DNS switch -> verification -> rollback window -> completion, per the milestone's own required shape:

1. **Preparation** (safe, no traffic impact): add the `asuid.api` TXT record (in progress, blocked on Namecheap's own maintenance as of this writing). Once it resolves, bind the custom domain and request the Managed Certificate against Azure while the CNAME still points at Render, so Azure-side provisioning happens with zero live-traffic exposure. Confirm the certificate has actually issued (not just "requested") before touching the CNAME.
2. **Validation**: run the full production validation suite (Phase 7 below) against the Container App's own default hostname one more time immediately before cutover, to have a clean, timestamped "still healthy right before the switch" baseline.
3. **DNS switch**: the user changes the `api.aisecurewatch.com` CNAME at Namecheap from `payreality-api.onrender.com` to the Container App's FQDN. This is the one traffic-affecting moment in the entire plan.
4. **Verification**: watch DNS resolution move over (`nslookup`/`Resolve-DnsName` against multiple public resolvers), then re-run the full production validation suite again, this time through the real `https://api.aisecurewatch.com` hostname, not the Container App's default one. Set Vercel's `VITE_API_URL` to `https://api.aisecurewatch.com` explicitly during this step (idempotent regardless of its unreadable current value).
5. **Rollback window**: Render stays running, untouched, and is not modified or suspended. If validation in step 4 fails in any way, revert the CNAME immediately; this is a same-session, same-TTL-window reversal, not a multi-day operation.
6. **Completion**: once validation passes and a real observation period has elapsed (see Phase 6; not something that can complete within a single working session, since it depends on watching real traffic and alerts over time, not a check that returns an instant answer), proceed to Render retirement.

**Honest disclosure on "no downtime"**: a brief HTTPS gap for `api.aisecurewatch.com` specifically, typically a few minutes, is expected between when the CNAME first resolves to Azure and when the Managed Certificate finishes binding, if the certificate provisioning in step 1 has not already fully completed before the DNS switch in step 3. This plan's own ordering (provision the certificate first, while DNS still points at Render, and confirm it has issued before switching) is designed to make this gap effectively zero in practice, but it is not physically possible to guarantee a literal zero-gap TLS handshake during a real cutover with a Let's-Encrypt-style automated certificate, and this plan does not claim otherwise.

## Phase 6: Render retirement checklist

**Not executed in this milestone.** Per this milestone's own rule ("never remove Render until Azure has been validated") and ordinary operational care, retirement requires a real observation window against real cutover traffic, which cannot happen inside a single working session; this section is the checklist for when that window has passed, not a record of it already having passed.

- [ ] DNS cutover (Phase 5) complete and stable for a deliberate observation period (recommend at least 48-72 hours of real traffic with zero rollback triggered, matching the pattern used for every prior cutover-adjacent decision in this project's own history).
- [ ] Zero errors, zero unexplained latency regressions, in Azure's own Application Insights for that entire window.
- [ ] Render's own dashboard/API confirms materially zero traffic during the same window (a live signal Render is no longer needed, not just an assumption).
- [ ] **A hard deadline exists independent of the above**: Render's free Postgres expires **2026-08-24**. If the observation window would run past that date, either upgrade Render's Postgres to a paid tier temporarily to preserve rollback capability, or explicitly accept that after that date Render can only roll back the application, not its data, and disclose that tradeoff before relying on it.
- [ ] Confirm, with real credentialed access this engagement has never had, whether Render's Postgres holds any real data that needs preserving before the instance is ever deleted. This has been an open, unresolved question since Milestone 4 and remains one; retirement should not proceed on an assumption here.
- [ ] What can be deleted once the above are all true: the Render web service (`srv-d9idj8t8nd3s739o5dsg`) and the Render Postgres instance (`payreality-db`), via the Render API this session already has working access to.
- [ ] What should remain temporarily: nothing needs to remain past the observation window once it passes cleanly; there is no reason to keep paying (even at $0) for infrastructure with a confirmed-zero-traffic track record.
- [ ] What to update once Render is actually gone: `render.yaml` (mark historical or delete), the `RENDER_GIT_COMMIT` fallback in `main.py` (can stay harmlessly, already noted in Milestone 4), the SDK's default base URL (already `https://api.aisecurewatch.com`, needs no change since that hostname now serves from Azure), and the documentation list Milestone 4's Phase 2 audit already enumerated in full.

## Phase 8: Operations runbook (post-cutover)

**DNS rollback**: revert the `api.aisecurewatch.com` CNAME at Namecheap to `payreality-api.onrender.com`. Effective within one TTL window (~30 minutes at today's TTL). No Azure-side action required; the Container App and its certificate stay bound and ready for a future re-attempt.

**Certificate renewal**: Azure auto-renews the Managed Certificate. Verify by checking `az containerapp hostname list`'s certificate expiry periodically (recommend a calendar reminder, not a manual monthly check, since Azure's own renewal is automatic and this is a spot-check, not a required action). If renewal ever fails silently, the first symptom will be a browser TLS warning on `api.aisecurewatch.com` as the existing certificate approaches its own expiry; the fix is re-running `az containerapp hostname bind` with the same parameters, which is idempotent.

**Domain renewal**: unrelated to this migration; `aisecurewatch.com`'s own registration renewal at Namecheap continues exactly as before, unaffected by anything in this milestone.

**Disaster recovery**: if the prod Container App environment were lost entirely, the DNS rollback above (point back at Render) is the immediate mitigation while Azure infrastructure is rebuilt from the same Terraform configuration already used for every prior milestone's redeploys.

**Monitoring and alerts**: unchanged from Milestone 4/5's existing 5 metric alerts per environment; no new alert type is introduced by a DNS/certificate change specifically, though a future improvement worth naming is an uptime check against `https://api.aisecurewatch.com` itself (the real, customer-facing hostname), not just the Container App's default hostname, since a DNS or certificate-specific failure would not necessarily show up as an application-level health-check failure.

**Incident response**: if `api.aisecurewatch.com` stops resolving or starts failing TLS after this migration, check, in order: (1) DNS resolution itself (has the CNAME been changed by anything else since), (2) certificate status via `az containerapp hostname list`, (3) the Container App's own health endpoints directly via its default hostname (isolates a DNS/cert problem from an application problem). The DNS rollback above is always available as an immediate mitigation regardless of which of the three is at fault.

## Phase 4 (execution): Custom domain binding

All steps executed for real, in this order, each verified before proceeding to the next:

1. **`asuid.api` TXT record added by the user at Namecheap.** VERIFIED propagated: `nslookup -type=TXT asuid.api.aisecurewatch.com` returned the exact verification string, `56A0FFA54D939E541407075F061240084F1C02D2C7A19714B9DB5C136CDE94DC`, matching the Container App's own `customDomainVerificationId` exactly.
2. **`az containerapp hostname add --hostname api.aisecurewatch.com` executed** while the CNAME still pointed at Render, deliberately, so this step carried zero live-traffic risk. Result: hostname added with `bindingType: "Disabled"` (unsecured, no traffic routed to it yet, since nothing pointed at it).
3. After the CNAME cutover (Phase 5 below), **`az containerapp hostname bind --hostname api.aisecurewatch.com --validation-method CNAME` executed**, with no certificate specified so Azure looked up-or-created its own free Managed Certificate automatically. Azure's own warning during this step ("It may take up to 20 minutes to create and issue a managed certificate") was accurate as a ceiling, not a guarantee: it completed well inside that window. Final result: `bindingType: "SniEnabled"`, a real `certificateId` under `managedEnvironments/cae-payreality-prod-cus/managedCertificates/`.

**No Terraform drift was silently introduced.** As documented in Phase 3 above, this exact operation cannot be expressed in this project's pinned Terraform provider version at all; it is recorded here, explicitly, as the one deliberate, disclosed exception to this project's otherwise-consistent "everything through Terraform" convention, not an oversight.

## Phase 5 (execution): DNS cutover, actually performed

1. User changed the `api` CNAME at Namecheap from `payreality-api.onrender.com` to `ca-payreality-api-prod-cus.redisland-66e4c9a9.centralus.azurecontainerapps.io`.
2. **VERIFIED at the authoritative nameserver immediately**, before public resolvers had caught up: `nslookup -type=CNAME api.aisecurewatch.com dns1.registrar-servers.com` returned the new Azure target right away, confirming the record itself had saved correctly rather than waiting blind through a caching delay.
3. **VERIFIED propagation to public resolvers**: Cloudflare's `1.1.1.1` resolved to Azure within minutes; Google's `8.8.8.8` briefly served a cached old value (expected, given the prior record's ~30-minute TTL) and then also resolved correctly on recheck. No manual TTL-lowering wait was needed in practice; the existing ~30-minute TTL cleared faster than that ceiling.
4. **Vercel's `VITE_API_URL` was set explicitly** on the `pay-reality-demo` project (`https://api.aisecurewatch.com`) via the Vercel API, for hygiene and for any future rebuild. **This turned out not to be load-bearing for this cutover**: the currently-deployed app bundle was checked directly (`curl` the live JS, grep for the API origin) and already called `https://api.aisecurewatch.com`, not a raw Render hostname, so the DNS change alone was sufficient to redirect the live frontend to Azure with zero redeploy required. This confirms the one open question Milestone 4/5 could never resolve (Vercel's env var is a write-only "sensitive" type, its prior value was never independently readable) in the only way that actually mattered: what the live app calls, checked directly.
5. **HTTPS verified working end to end**: `curl https://api.aisecurewatch.com/health` returns `200 {"status":"ok"}` with `ssl_verify_result: 0` (certificate chain verifies successfully), and the certificate itself is real: issued by DigiCert (GeoTrust TLS RSA CA G1, Azure's Managed Certificate CA), valid 2026-08-14 through 2027-02-14, auto-renewing.
6. **Render was not modified, stopped, or touched in any way during this entire process.** It remains fully intact as the rollback target described in Phase 5's design section above.

The disclosed "brief HTTPS gap" risk named in the design section did not materialize in practice: the certificate was fully bound before the cutover was declared complete, and the CNAME change itself was the only live-traffic-affecting action taken.

## Phase 7: Production validation, through the real domain

Every check below is a real call against `https://api.aisecurewatch.com` itself, the actual production hostname now live on Azure, not the Container App's own default hostname (which was already validated in Milestone 5/6). This distinction matters: it proves the custom domain and certificate layer work correctly end to end, not just that the underlying Container App does.

| Area | Result |
|---|---|
| Health / readiness | `200 {"status":"ok"}`; `{"ready": true, "checks": {"database": true, "opa": true}}` |
| Runtime Authority (full pipeline) | **PASS**, all 10 stages of `scripts/smoke_test.py` run fresh against the real domain: Principal, Agent, activation, signed Intent, Decision, HUMAN_REVIEW resolution, Evidence generation, cryptographic Evidence verification, public key verification, Assurance counts |
| OPA | **PASS** (implicit in the above: the Decision returned came from a real OPA evaluation, and `health/ready`'s own `opa: true` check passed) |
| Runtime Policy Simulator (Milestone 6 fix) | **PASS**, re-run through the real domain specifically: the same policy that returned a real `ALLOW` in Milestone 6 does so again here, with the same bundle hash mechanism, confirming the fix holds through the new domain/certificate path, not just the raw hostname |
| Authority Builder / Authority Intelligence | **PASS**: the Blob-backed corpus created during Milestone 5/6 validation (`policy_count: 2, principal_count: 2, ...`) is still fully reachable and correct through the real domain |
| AI Policy Builder | `ai_enabled: true`, genuinely Foundry-backed per Milestone 6; not re-exercised with a new real extraction in this pass since Milestone 6 already proved it live minutes before this cutover and nothing about a DNS/certificate change could plausibly affect application-layer provider selection |
| Azure AI Foundry / Azure AI Search | Unaffected by this milestone by construction (no application code or Azure resource configuration changed, only DNS/certificate); both already proven live in Milestone 5/6 |
| Blob Storage | **PASS**, confirmed via the same corpus-reachability check above |
| Evidence | **PASS**: generation and cryptographic verification both succeeded in the smoke test; `GET /v1/evidence/chain/verify` still does not crash (the Milestone 3 fix holds) but still shows `total: 0` against an organization with confirmed real Evidence, the same disclosed, unrelated, un-root-caused discrepancy first found in Milestone 5 and explicitly not investigated again here, since it is unrelated to DNS/certificates |
| SDK | **NOT VERIFIED** in this pass, consistent with Milestone 5/6's own disclosed gap; nothing about this specific milestone (DNS/certificates) plausibly affects SDK behavior, since the SDK talks to whatever base URL it is configured with exactly as any other HTTP client would |
| Authentication / RBAC | **PASS**: an unauthenticated request to `/v1/agents` returns `401`, exactly as it does against the raw hostname |
| Multi-tenancy / organization isolation | **PASS**, re-proven through the real domain: the first organization's agents are visible under its own credentials; the second organization (created during Milestone 5 validation) sees zero agents, zero cross-contamination |
| Certificates | **PASS**: real, CA-issued, auto-renewing, verified via both `curl`'s own TLS verification and a direct `openssl s_client` handshake |
| DNS | **PASS**: resolves correctly on both Google (`8.8.8.8`) and Cloudflare (`1.1.1.1`) public resolvers |
| Latency | **PASS, informational**: ~770-830ms per request, broken down via `curl`'s own timing fields into ~260ms TCP connect and ~520ms TLS handshake; this figure is **identical** whether requesting the custom domain or the Container App's raw default hostname, confirmed by direct side-by-side comparison, meaning it reflects ordinary long-haul network distance to Azure's `centralus` region, not any overhead introduced by the custom domain or certificate layer itself |

## Phase 6: Render retirement, status after cutover

The DNS cutover is complete and stable as of this writing, but **no retirement action has been taken**, and none should be yet. Per this milestone's own rule and the checklist already written in the design section above, retirement requires a real observation window this single working session cannot provide (uptime and error-rate history accumulate over real elapsed time, not over the course of one conversation). What has changed since that checklist was written: item 1 ("DNS cutover complete and stable") is now true as of a few minutes ago, not yet as of 48-72 hours, so the observation window starts now, not before. Every other item on that checklist (real traffic confirmation on Render's own dashboard over the window, the 2026-08-24 Postgres expiry constraint, confirming whether Render's database holds real data worth preserving) remains exactly as stated and unresolved.

## Final readiness verdict

**Against this milestone's own Completion Gate, stated plainly, item by item:**

- **"`aisecurewatch.com` is fully served from Azure"**: true in the sense that matters and false in the overly literal sense. Every production subdomain under `aisecurewatch.com` is now served by the correct modern platform for its purpose: `api.aisecurewatch.com` by Azure (this milestone's actual objective), and `aisecurewatch.com`/`www`/`demo`/`payreality` by Vercel, exactly as they were before and exactly as Phase 2's own design decision recommended they remain. Moving the marketing/app/demo frontends to Azure was never the right architecture (see Phase 2's reasoning) and was not part of what "Azure as the authoritative production platform" needs to mean here. Zero subdomains depend on Render anymore, which is the actual, correct measure of completion.
- **"All production traffic terminates in Azure"**: true for the API, the only backend that ever ran on Render. Frontend traffic terminating at Vercel is unrelated to Render and always was.
- **"Render is no longer serving production traffic"**: **VERIFIED true**, via live DNS resolution on two independent public resolvers and a real end-to-end validation pass against the new path.
- **"Azure manages production TLS certificates"**: true for `api.aisecurewatch.com`, the one domain this migration touched. Verified via a real Managed Certificate, auto-renewing, bound and confirmed live.
- **"DNS points entirely to Azure"**: true for the one record that needed to move. The zone itself deliberately remains at Namecheap (Phase 2's hybrid decision), which is the correct outcome, not a shortfall against this gate's intent.
- **"Production has been fully validated after cutover"**: **VERIFIED**, per the full Phase 7 table above.
- **"Rollback procedures exist and are documented"**: **VERIFIED**, in this document's own Phase 5 design section, and provable in practice: reverting the CNAME is the entire rollback, Render was never touched, and nothing about this cutover created a one-way door.

**Is this milestone complete? Yes, for the DNS/certificate/cutover objective this milestone actually names.** Render retirement itself is correctly not complete, and should not be: it depends on a real observation window that cannot exist inside a single working session, exactly as this milestone's own rules require ("never remove Render until Azure has been validated" is now satisfiable in the past tense, but "safe to delete" is a claim about the *next* several days, not about right now). The recommended next action is calendar time, not more engineering: watch Application Insights and Render's own dashboard for 48-72 hours, confirm zero rollback triggers, confirm the Render Postgres data question, and then execute the retirement checklist already written above, ideally before the Render Postgres's own 2026-08-24 auto-expiry removes the choice either way.
