# Milestone 16: Production Validation

This document distinguishes what has been validated against the **live Azure staging URLs** (the
`*.azurestaticapps.net` default hostnames, since no custom domain or DNS change has happened yet) from
what remains to validate **after** the pending DNS action. Nothing here claims a production-domain
verification that hasn't actually happened.

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

## Pending DNS actions (for the user, at Namecheap -- see architecture doc for why these can't be done from this session)

**Before any record is changed**, confirm in the Namecheap dashboard whether `ALIAS` or `ANAME` record
types are offered for this domain (some Namecheap plans support them, some don't) -- this determines
which of the two apex-domain options below applies.

| Domain | Current record | Target |
|---|---|---|
| `payreality.aisecurewatch.com` | A -> `76.76.21.21` (Vercel) | CNAME -> `nice-beach-0bb78f810.7.azurestaticapps.net` |
| `www.aisecurewatch.com` | CNAME -> Vercel edge | CNAME -> `lemon-bay-06710d110.7.azurestaticapps.net` |
| `aisecurewatch.com` (apex) -- **if ALIAS/ANAME is available** | A -> `216.198.79.1` (Vercel) | ALIAS/ANAME -> `lemon-bay-06710d110.7.azurestaticapps.net` |
| `aisecurewatch.com` (apex) -- **if ALIAS/ANAME is not available** | A -> `216.198.79.1` (Vercel) | Registrar-level URL redirect to `https://www.aisecurewatch.com` (standard fallback; `www` becomes the real Azure-hosted target) |

**Do not touch**: MX records (`mx1`/`mx2.improvmx.com`) or the existing TXT records (SPF, Google site
verification) -- unrelated to this migration, real production email routing depends on them.

**Immediately after each record is changed**, this session (or a follow-up one) will run
`az staticwebapp hostname set` for that domain to complete the Azure-side binding and certificate
issuance, then re-run this document's full validation suite against the real domain -- matching Milestone
7's own established cutover discipline (provision/validate with DNS still on the old provider where
possible, switch, then immediately re-verify through the real hostname).

## Backend and API (unaffected, re-confirmed)

**LIVE, VERIFIED**: `https://api.aisecurewatch.com/openapi.json` returns `200`. Zero backend code,
configuration, or infrastructure was changed by this milestone. `GET /health/ready` returns
`{"ready":true,"checks":{"database":true,"opa":true}}` -- OPA is healthy, which is only possible if it is
still running and reachable exactly where it has always been (the FastAPI process resolves it via
`settings.opa_url`, `http://127.0.0.1:8181` in production, unchanged). `az resource list` for any resource
with "opa" in its name returns empty -- confirms no separate OPA Azure resource, endpoint, or service of
any kind was created, matching this milestone's explicit prohibition. OPA was not touched, split,
exposed, or given any network identity beyond its existing loopback binding.
