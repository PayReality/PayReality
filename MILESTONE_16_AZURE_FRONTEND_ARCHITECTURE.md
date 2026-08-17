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

## Custom domain binding: COMPLETE (LIVE, VERIFIED)

**All three custom domains are now bound and serving in production**:
`az staticwebapp hostname show` reports `"status": "Ready"` for `payreality.aisecurewatch.com`,
`www.aisecurewatch.com`, and `aisecurewatch.com`, each with a valid, issued managed certificate, and
direct HTTPS checks against all three confirm `200` with `ssl_verify_result: 0` and correct content (see
`MILESTONE_16_PRODUCTION_VALIDATION.md`'s "Real production domain validation" section for the full
results). The findings below, made while working through the binding, are kept as the record of what was
actually required, not as open items.

Attempting to bind each real domain to its Azure Static Web App (Azure-side actions, before any DNS
record was changed) surfaced two concrete, real requirements that were not knowable without attempting
it, plus a third discovered while completing the apex domain after DNS was changed:

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
3. **The apex domain (`aisecurewatch.com`) needed a specific decision, resolved**: apex domains cannot be
   `CNAME` records by DNS specification. **Confirmed live**: Namecheap's plan for this domain does offer
   `ALIAS` records, so the apex uses `ALIAS -> lemon-bay-06710d110.7.azurestaticapps.net` -- the
   URL-redirect-to-`www` fallback was not needed.
4. **Root/apex domains require a different Azure validation method, discovered by attempting the
   default one first**: `az staticwebapp hostname set --hostname aisecurewatch.com` (no extra flags)
   returned the same `CNAME Record is invalid` error even after DNS was correctly pointed via the `ALIAS`
   record above -- because the CLI's default `cname-delegation` validation method doesn't apply to root
   domains at all (confirmed directly from `az staticwebapp hostname set --help`, which explicitly notes
   `--hostname` "Only support sub domain in preview" for the default method, and documents
   `--validation-method dns-txt-token` as the root-domain path). Re-running with
   `--validation-method dns-txt-token` prompted for a TXT record
   (`_dnsauth.aisecurewatch.com`, value `_vgb5p7h7faabqioc7ddrf4097nvhd3s`) -- once the user added it,
   Azure's own validation polling picked it up and the domain reached `"status": "Ready"` without further
   action.

## DNS cutover: COMPLETE

The user changed all three DNS records directly at Namecheap (unavoidable -- this environment has no
Namecheap API credential, confirmed originally in Milestone 7). Each change was verified live at the
authoritative nameserver (`dns1`/`dns2.registrar-servers.com`) as it happened, not assumed from the
Namecheap panel alone. One transient issue during the apex change (an interim redirect-record attempt
briefly returning `404 Site Not Found` from Namecheap's own forwarding service) was diagnosed and
resolved by replacing it with the final `ALIAS` record. Full before/after record values are in
`MILESTONE_16_PRODUCTION_VALIDATION.md`.
