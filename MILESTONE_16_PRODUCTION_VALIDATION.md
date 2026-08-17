# Milestone 16: Production Validation

**Update: DNS cutover is complete.** All three real production domains (`aisecurewatch.com`,
`www.aisecurewatch.com`, `payreality.aisecurewatch.com`) now resolve to Azure and serve correctly over
valid HTTPS -- see "Real production domain validation" below. The staging-hostname validation that
follows was performed *before* the cutover and is kept here as the historical record of what was checked
before DNS was touched, per this milestone's own discipline of not claiming a production-domain
verification before it actually happened.

## Real production domain validation (post-cutover, LIVE, VERIFIED)

Performed after the user changed the three DNS records at Namecheap and this session completed the
corresponding Azure-side custom domain bindings (`az staticwebapp hostname set`, once for each domain,
using `--validation-method dns-txt-token` for the apex specifically -- discovered as a real requirement
only by attempting the default method first and reading Azure's own error/help output, not assumed in
advance):

| Domain | Result |
|---|---|
| `https://aisecurewatch.com/` | `200`, `ssl_verify_result: 0` (certificate chain verifies), correct prerendered title and canonical URL referencing the real domain. Confirmed consistently across repeated checks, including after a local DNS-cache flush, to rule out a transient stale-cache false positive (one earlier check briefly hit a stale cached IP and failed TLS/SNI validation -- this was a local resolver caching artifact, not a server-side issue, and did not recur after the flush). |
| `https://www.aisecurewatch.com/` | `200`, `ssl_verify_result: 0`, correct content. |
| `https://payreality.aisecurewatch.com/` | `200`, `ssl_verify_result: 0`, correct content (the dashboard). |
| CORS preflight, real origin | `OPTIONS https://api.aisecurewatch.com/v1/auth/login` with `Origin: https://payreality.aisecurewatch.com` returns `200` with `access-control-allow-origin: https://payreality.aisecurewatch.com` -- confirms the prediction made before cutover (no backend CORS change would be needed, since the origin string is unaffected by which infrastructure serves the frontend) was correct. |

**What this does and does not prove**: this confirms the domains resolve to Azure, serve valid HTTPS, and
that the CORS precondition for the dashboard to reach the API is satisfied. It does **not** constitute a
full login/RBAC/Decision-Center click-through -- that still requires a real browser session (see "Browser
verification status" below, unchanged) or the user's own manual walkthrough.

## Pre-cutover staging validation (historical record)

This document distinguishes what was validated against the **Azure staging URLs** (the
`*.azurestaticapps.net` default hostnames, before DNS was touched) from what the section above confirms
against the real domains now. Nothing here claims a production-domain verification before it actually
happened.

## Marketing website -- staging validation (`https://lemon-bay-06710d110.7.azurestaticapps.net`)

All **LIVE, VERIFIED** this session via direct `curl` checks against the real deployed site, not assumed
from a successful build:

| Check | Result |
|---|---|
| Homepage loads | `200`, correct `<title>PayReality \| Enterprise AI Authority Infrastructure</title>` |
| `/about` | `200`, correct distinct title |
| `/manifesto` | `200`, correct distinct title |
| `/developers` | `200`, correct distinct title |
| `/resources/faq` | `200`, correct distinct title |
| `robots.txt` | `200`, served |
| `sitemap.xml` | `200`, served |
| Prerendering | Each route above returned its own distinct, correct `<title>` -- confirms the
  build-time SSR prerender step ran correctly on Azure's build infrastructure (Node 24, GitHub Actions
  runner), not just that the client bundle built |
| SPA routing config | `staticwebapp.config.json`'s fallback rule deployed and did not break any of the
  above real routes |

**Not yet validated** (require either a real browser, per this milestone's own disclosed environment
limitation, or the custom domain to be live): forms (the `mailto:` modal flow -- source-verified in the
audit doc, not click-tested), image asset loading beyond HTTP-200 checks on the HTML documents themselves,
mobile/responsive rendering, and JSON-LD structured-data content (confirmed the injection mechanism is
unchanged and ran during the same prerender pass that correctly patched titles, but the actual JSON-LD
payload was not independently diffed against the Vercel version this session).

## Dashboard -- staging validation (`https://nice-beach-0bb78f810.7.azurestaticapps.net`)

**LIVE, VERIFIED**:
- Homepage loads, `200`, correct `<title>PayReality | AI Authority Layer</title>`.
- The deployed JS bundle, fetched and inspected directly, calls `api.aisecurewatch.com` -- confirms
  `VITE_API_URL` was correctly baked in at build time on Azure's pipeline, matching Vercel's production
  behavior exactly (this was the single most load-bearing build-time value for this application; getting
  it wrong would have silently shipped a dashboard unable to reach the real API at all).

**A real, concrete finding, not a failure of this migration**: an actual authenticated API call
(`OPTIONS /v1/auth/login` with `Origin: https://nice-beach-0bb78f810.7.azurestaticapps.net`) was rejected
by the backend's CORS policy (`400 Disallowed CORS origin`). This is **expected and correct**, not a bug
to fix: the backend's CORS allowlist is origin-based (scheme + host), and the temporary Azure staging
subdomain is, correctly, not on it. Verified directly that the real production origin the dashboard will
actually be served from after DNS cutover, `https://payreality.aisecurewatch.com`, is **already
allowlisted today** (`200 OK`, `access-control-allow-origin: https://payreality.aisecurewatch.com`) --
because a browser's `Origin` header reflects the domain the page loads from, not which infrastructure
serves it, cutting DNS over to Azure requires **zero backend CORS change**, since the origin string itself
never changes. This was verified by direct testing, not assumed from CORS theory alone.

**Not yet validated, and cannot be until the custom domain is live** (this is the actual reason full
dashboard functional validation is blocked on the DNS action, not a gap in this session's effort): login,
RBAC, tenant isolation, and every dashboard route/workflow named in this milestone's Phase 7 (Decisions in
all six states, Agents, Policy Builder, Runtime Policies, Evidence, Approvals, Settings, organization
management, deep links, page refresh) all require a real authenticated session, which requires a
CORS-allowed origin, which requires the real custom domain to be live. Attempting any of these against the
staging subdomain would only demonstrate the CORS rejection already confirmed above, not the actual
dashboard behavior.

## Browser verification status

**BLOCKED BY ENVIRONMENT**, consistent with every prior milestone in this engagement -- no browser
automation tool is available in this session (not re-checked freshly this exact turn, but no tool
addition occurred between the last confirmed check and now). All validation above is direct HTTP-level
verification against the real deployed artifacts, the strongest available alternative, not a substitute
claimed to be equivalent to an actual browser session.

## DNS actions actually taken (historical record; ALIAS/ANAME turned out to be available)

| Domain | Was | Now |
|---|---|---|
| `payreality.aisecurewatch.com` | A -> `76.76.21.21` (Vercel) | CNAME -> `nice-beach-0bb78f810.7.azurestaticapps.net` |
| `www.aisecurewatch.com` | CNAME -> Vercel edge | CNAME -> `lemon-bay-06710d110.7.azurestaticapps.net` |
| `aisecurewatch.com` (apex) | A -> `216.198.79.1` (Vercel) | `ALIAS` -> `lemon-bay-06710d110.7.azurestaticapps.net` (ALIAS was available on this Namecheap plan; the URL-redirect fallback was not needed) |
| `_dnsauth.aisecurewatch.com` (new) | did not exist | `TXT` -> `_vgb5p7h7faabqioc7ddrf4097nvhd3s` (Azure's root-domain ownership validation token; must remain in place for certificate renewal, same pattern as `asuid.api`'s role in Milestone 7) |

MX records (`mx1`/`mx2.improvmx.com`) and the existing TXT records (SPF, DMARC, Google/Bing site
verification, DKIM) were **not touched**, confirmed by direct inspection of the full record list before
and after -- real production email routing was never at risk.

One real intermediate finding during cutover, resolved: immediately after the apex `A` record was first
changed (an earlier attempt, since replaced by the `ALIAS` record above), it briefly resolved to
Namecheap's own URL-forwarding service IP and returned `404 Site Not Found` -- this was a leftover from
an interim redirect-record attempt, not a problem with the final `ALIAS`-based configuration, and resolved
once the `ALIAS` record was the only record present for that host.

## Backend and API (unaffected, re-confirmed)

**LIVE, VERIFIED**: `https://api.aisecurewatch.com/openapi.json` returns `200`. Zero backend code,
configuration, or infrastructure was changed by this milestone. `GET /health/ready` returns
`{"ready":true,"checks":{"database":true,"opa":true}}` -- OPA is healthy, which is only possible if it is
still running and reachable exactly where it has always been (the FastAPI process resolves it via
`settings.opa_url`, `http://127.0.0.1:8181` in production, unchanged). `az resource list` for any resource
with "opa" in its name returns empty -- confirms no separate OPA Azure resource, endpoint, or service of
any kind was created, matching this milestone's explicit prohibition. OPA was not touched, split,
exposed, or given any network identity beyond its existing loopback binding.
