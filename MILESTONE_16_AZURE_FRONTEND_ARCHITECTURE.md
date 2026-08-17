# Milestone 16: Azure Frontend Architecture

## Phase 1 decision: Azure Static Web Apps for both applications

**Decision: Azure Static Web Apps, Free tier, for both the marketing website and the dashboard.**

Reasoning, per the milestone's own "least complex hosting model that fully supports the existing
application" principle: both applications, confirmed in `MILESTONE_16_FRONTEND_MIGRATION_AUDIT.md`, are
Vite-built SPAs with zero server-side runtime requirement. The marketing site's build-time SSR/prerender
pass produces static HTML files, not a live server-rendering process -- there is nothing for App Service
or Container Apps to actually run at request time for either application that Static Web Apps' CDN-backed
static file serving doesn't already do. Free tier's 2-custom-domain limit is exactly sufficient (marketing
site needs `aisecurewatch.com` + `www.aisecurewatch.com`; dashboard needs only
`payreality.aisecurewatch.com`), and its free, auto-renewing managed TLS certificates match this
project's existing certificate strategy for `api.aisecurewatch.com` (Milestone 7).

**Rejected**: Azure App Service and Azure Container Apps, both real options considered and rejected as
unnecessary complexity -- neither application has a server-side process to host; introducing one would be
infrastructure with no corresponding requirement, exactly what this milestone's own instructions warn
against.

## Resources provisioned (LIVE, VERIFIED)

A new, deliberately separate Terraform root, `AZURE_MIGRATION/terraform-frontend/` (own state file,
`payreality-frontend.tfstate`, same backend storage account as the existing backend Terraform), holding
two `azurerm_static_web_app` resources in the existing `rg-payreality-prod-cus` resource group:

| Resource | Name | Default hostname | Bound app |
|---|---|---|---|
| Static Web App | `stapp-payreality-website-prod-cus` | `lemon-bay-06710d110.7.azurestaticapps.net` | Marketing website (`Payreality-website` repo) |
| Static Web App | `stapp-payreality-dashboard-prod-cus` | `nice-beach-0bb78f810.7.azurestaticapps.net` | Dashboard (`PayReality` repo) |

Both **LIVE** as of this session -- `terraform apply` completed, both resources confirmed created via
their own outputs, and both are serving real, correct application content today at their default
hostnames (see `MILESTONE_16_PRODUCTION_VALIDATION.md`).

## CI/CD pipeline (LIVE, VERIFIED)

`.github/workflows/azure-static-web-apps.yml` added to both repositories, triggered on push to `main`
(the same branch Vercel already deploys from) and manually via `workflow_dispatch`. Each workflow:
builds the app itself on Node 24 (matching Vercel's own configured Node version exactly, rather than
relying on Azure's Oryx auto-builder to guess it), sets the exact build-time environment variables the
Vercel production build has always used (`VITE_API_URL=https://api.aisecurewatch.com` explicitly for the
dashboard, since this value can never be read back from Vercel's "sensitive" env var type but is
unambiguously the correct one per Milestone 7's own live-bundle verification), then deploys the pre-built
`dist/` output via `Azure/static-web-apps-deploy@v1` using a per-repository deployment token
(`AZURE_STATIC_WEB_APPS_API_TOKEN_WEBSITE` / `_DASHBOARD`, each Terraform's own `api_key` output, set as a
GitHub Actions secret via `gh secret set`, never printed to any log).

**One real bug found and fixed during this milestone**: the action's actual required input is
`azure_static_web_apps_api_token`, not `azure_static_web_apps_api_key` as first written -- confirmed from
the first (failed) run's own warning log, not guessed, and fixed in both repos' workflow files within the
same session (commits `2285aab` on the website repo, `5ef5fb2` on the dashboard repo). Both workflows now
run green.

`staticwebapp.config.json` added to both repos' roots, replicating each app's existing Vercel
`vercel.json` SPA-fallback rewrite (`navigationFallback.rewrite` to `/index.html`), with an `exclude`
list matching each app's real static-asset paths so a genuinely missing asset still 404s instead of
silently serving the SPA shell.

**Analytics parity gap, disclosed rather than silently accepted**: `VITE_MIXPANEL_TOKEN` is referenced in
both workflows as a GitHub Actions secret but has not been set yet -- its real value lives only in
Vercel's own encrypted, write-only env var store and cannot be read back by design. Until it is added to
each repo's GitHub secrets (a value only the user can supply, e.g. by re-entering it from wherever it was
originally generated, since Vercel itself cannot disclose it either), both Azure builds ship with
analytics silently disabled -- **the application still functions correctly either way** (this is the
existing, deliberate no-op-if-unset design in `analytics.ts`), but this is a real, known parity gap
against the current Vercel production behavior, not something to claim is already matched.

## Custom domain binding: real findings, not yet completed

Attempting to bind each real domain to its Azure Static Web App this session (Azure-side actions only,
**no DNS record was changed**) surfaced two concrete, real requirements that were not knowable without
attempting it:

1. **Static Web Apps requires the DNS record to already point at the app's default hostname before
   Azure will accept the custom domain binding** -- a different order of operations than Container Apps'
   flow (Milestone 7), which let the hostname be added first and validated later. Concretely: `az
   staticwebapp hostname set --hostname payreality.aisecurewatch.com` today returns `CNAME Record is
   invalid. Please ensure the CNAME record has been created` -- correct and expected, since DNS still
   points at Vercel. **This means the DNS record change must happen first, then the Azure-side binding
   immediately after**, the reverse of this milestone's own Phase 5 ordering as originally described, and
   is disclosed here precisely because it changes the real sequence of steps still to come.
2. **A CAA-record consideration for `www.aisecurewatch.com` specifically, resolved by analysis, not yet
   requiring separate action**: attempting to bind `www.aisecurewatch.com` returned a CAA-authorization
   error naming `digicert.com` (Azure Static Web Apps' certificate issuer). Investigating this directly
   (via a DNS-over-HTTPS CAA query, since neither `nslookup` nor PowerShell's `Resolve-DnsName` support
   the CAA record type on this system) found the CAA restriction does not live on `aisecurewatch.com`
   itself -- it lives on Vercel's own CNAME target (`050e7dbf8560f39d.vercel-dns-017.com`), which
   `www.aisecurewatch.com` currently points at, restricting issuance to `globalsign.com`,
   `letsencrypt.org`, `sectigo.com`, and `pki.goog`. CAA lookups follow a CNAME chain, so this restriction
   is Vercel's own security posture for its own infrastructure, not a record anyone would need to
   separately remove -- **once the CNAME is repointed at Azure's own hostname, the CAA check will
   evaluate against whatever (if any) CAA policy exists for `azurestaticapps.net`, not Vercel's**, and
   this specific error is expected to resolve itself as a direct consequence of the DNS change, not a
   separate blocker requiring its own fix. This is **RECOMMENDED as the working assumption**, not yet
   independently confirmed by an actual successful binding, since that requires the DNS change to have
   already happened.
3. **The apex domain (`aisecurewatch.com`) needs a specific decision, not just a record change**: apex
   domains cannot be CNAME records by DNS specification, and Azure Static Web Apps' apex-domain support
   depends on the registrar supporting an ALIAS/ANAME-style record (a CNAME-like record permitted at the
   zone apex) or an equivalent Azure-specific TXT-validated `A`/`ALIAS` binding. **Whether Namecheap's
   plan for this domain supports ALIAS/ANAME records is UNVERIFIED** -- this environment has no
   Namecheap API credential (confirmed in Milestone 7, unchanged), so this can only be checked by the
   user directly in the Namecheap dashboard. If ALIAS/ANAME is unavailable, the standard, well-established
   fallback is a registrar-level URL redirect from the bare apex to `https://www.aisecurewatch.com`
   (making `www` the real Azure-hosted target and the apex a pure redirect) -- common practice for
   exactly this constraint, and worth deciding now rather than discovering it as a blocker mid-cutover.

## Required next action (blocks all further progress on custom domains and DNS cutover)

This is a genuine, disclosed handoff point, not a task this session's tooling can complete alone --
**this environment has no API credential for Namecheap** (the domain's actual DNS host), confirmed
originally in Milestone 7 and reconfirmed by this milestone's own domain inspection. The user must,
at Namecheap, either:
- Check whether ALIAS/ANAME record types are available for the `aisecurewatch.com` apex, and report back
  which option to use (native ALIAS record if available; a URL-redirect-to-www fallback if not), **before**
  any DNS record for either in-scope domain is changed, so the plan below can be finalized rather than
  attempted blind; then
- Add the exact records specified in `MILESTONE_16_PRODUCTION_VALIDATION.md`'s "Pending DNS actions"
  section once that decision is made.

No further Azure-side custom-domain work can proceed until this happens, since (per finding 1 above)
Azure will not accept the binding until the DNS record already resolves to the correct target.
