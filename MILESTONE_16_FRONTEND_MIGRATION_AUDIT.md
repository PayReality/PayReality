# Milestone 16: Frontend Migration Audit (Phase 0-2)

Every claim below is **VERIFIED** (checked directly this session), not inferred or carried forward from
a prior milestone's memory without re-confirmation, unless explicitly marked otherwise.

## Repository identification

Two separate, real repositories, confirmed via `git remote -v` in each:
- **Marketing website**: `C:\Users\user\Downloads\PayReality website` -> `github.com/PayReality/Payreality-website.git`.
- **Dashboard**: `C:\Users\user\Downloads\payreality-demo-audit` -> `github.com/PayReality/PayReality.git`.

## Marketing website (`aisecurewatch.com`)

- **Framework**: React + TypeScript, Vite 6.3.5, `react-router` 7.13.0 for client-side routing.
- **Package manager**: npm (`package-lock.json` present; a `pnpm-workspace.yaml` also exists but is
  unused by the actual build script).
- **Build command**: `vite build && vite build --ssr src/entry-server.tsx --outDir dist-ssr && node scripts/prerender.mjs`
  -- three real steps, not one. The client SPA builds to `dist/`, a second SSR-only build (externalizing
  React rather than bundling it) produces `dist-ssr/entry-server.js`, and `scripts/prerender.mjs` then
  renders every real route through `react-dom/server` and writes the result over `dist/<route>/index.html`,
  patching `<title>`/meta/canonical/OG/JSON-LD tags from `scripts/route-meta.mjs` (the client-only `SEO.tsx`
  component sets these via `useEffect`, which never runs during this static render, so this patch step is
  what makes crawlers see real content without executing JavaScript). **The final build output is 100%
  static files** -- there is no server-side rendering at request time, no serverless function, and no API
  route of any kind in this repository.
- **Output directory**: `dist/` (the SSR build's `dist-ssr/` is a build-time-only intermediate, never
  served).
- **Node version**: confirmed via Vercel project settings, `24.x`.
- **Environment variables** (from `vercel env ls production` against the live `aisecurewatch-website`
  project): exactly one, `VITE_MIXPANEL_TOKEN` (Preview + Production, Vercel "sensitive" type -- readable
  only by overwriting, not by reading back, though this is a build-time value embedded in the public
  bundle regardless, per this milestone's own correct framing that frontend env vars are never secret
  once built). `analytics.ts` also reads `VITE_MIXPANEL_DEBUG`, unset in Vercel (defaults off, matching
  `.env.example`).
- **API dependencies**: none at runtime. `src/app/lib/site.ts` hardcodes three literal URLs consumed only
  as outbound `<a href>` links, never fetched: `SITE_URL` (`https://aisecurewatch.com`), `PLATFORM`
  (`https://demo.aisecurewatch.com`, the separate public demo, out of this milestone's two named
  domains), and `API_URL` (`https://api.aisecurewatch.com`, linked only to `/docs`, the FastAPI
  auto-generated reference).
- **Server-side requirements**: none at request time (see build command above).
- **Static assets**: `public/` -- favicons (light/dark variants), `og-image.png`, `site.webmanifest`,
  `payreality-logo.png`/`-dark.png`, `robots.txt`, `sitemap.xml`, and one domain-ownership verification
  file (`197687a0b6a30c1f0a8c1c5bdf203f94.txt`, a bare token in a flat text file -- almost certainly a
  Bing/other webmaster-tools verification artifact; **must be carried over unchanged** to any new host or
  domain verification will break).
- **Forms**: none with a real backend. The README and source confirm "Request Enterprise Demo"/"Request
  Research Paper" open an in-page modal that builds a `mailto:` link (no network call), and "View
  Platform"/"Book a Demo" are plain outbound links to `demo.aisecurewatch.com`.
- **Analytics**: Mixpanel via `mixpanel-browser`, client-side only, silently no-ops if
  `VITE_MIXPANEL_TOKEN` is unset.
- **SEO**: per-page `<SEO>` component (title/description/canonical/OG/JSON-LD props) plus the build-time
  prerender pass described above, which is what actually makes this metadata visible to non-JS crawlers.
- **Structured data**: JSON-LD, injected by the prerender step per `scripts/route-meta.mjs`'s per-route
  metadata table.
- **Sitemap**: static `public/sitemap.xml`, hand-maintained (not generated at build time), listing every
  real route with `lastmod`/`changefreq`/`priority`.
- **robots.txt**: static, `Allow: /`, references the sitemap.
- **Redirects/rewrites**: `vercel.json` has exactly one rule -- a catch-all rewrite to `/index.html` for
  any path not matching `assets/`, favicons, `og-image`, `site.webmanifest`, `robots.txt`, or
  `sitemap.xml`. Because Vercel (like most static hosts) always serves a literal existing file before
  consulting a rewrite rule, and the prerender step writes a real `index.html` into every route's own
  directory, **every real route is actually served as its own prerendered static file today**; the
  rewrite only ever fires for a path with no matching prerendered file (a 404-shaped or truly
  client-only path). A `public/_redirects` file also exists, in Netlify's own redirect-file syntax
  (`/* /index.html 200`) -- Vercel does not read this format at all, so it is inert/vestigial on the
  current host, but its *intent* (an SPA fallback) must still be replicated on whatever the next host is.
  `/docs/*` routes are also noted (README) as redirecting to `/developers/*`, implemented in
  `AppRoutes.tsx` at the router level (a client-side redirect), not as a host-level rule -- **VERIFIED
  present in source, not independently tested via a live redirect chain this session.**
- **Image optimization**: none -- plain `<img>`/static asset references, no Vercel Image Optimization API
  usage found (`git grep -i "next/image\|vercel.*image"` returns nothing, consistent with this being a
  plain Vite SPA, not Next.js).
- **External integrations**: Mixpanel (analytics) and the domain-verification file above are the only
  two found. No forms integration, no CMS, no third-party embeds beyond these.
- **Vercel-specific functionality used**: none beyond static hosting + the one rewrite rule + the custom
  domain/certificate binding itself. No serverless functions, no edge functions, no cron jobs, no
  deployment hooks configured (confirmed: `vercel project inspect` shows no functions/cron section for
  this project, and the repo contains no `api/` directory Vercel would auto-detect as serverless
  functions).

## Dashboard (`payreality.aisecurewatch.com`)

Re-confirmed this session (previously established across Milestones 3-15 of this engagement, verified
again rather than merely carried forward):
- **Framework**: React + TypeScript, Vite 6.4.3, `react-router` 7.18.2, client-side routing only, every
  route lazy-loaded (`routes.tsx`).
- **Package manager**: npm.
- **Build command**: `vite build` (single step -- no SSR/prerender pass, unlike the marketing site; this
  app requires an authenticated session to show anything meaningful, so build-time prerendering for
  anonymous crawlers was never applicable).
- **Output directory**: `dist/`.
- **Node version**: `24.x` (Vercel project settings).
- **Environment variables** (`vercel env ls production` against `pay-reality-demo`): `VITE_API_URL`
  (Production only, sensitive) and `VITE_MIXPANEL_TOKEN` (Preview + Production). `VITE_API_URL` is
  genuinely load-bearing at build time -- `src/app/live/apiClient.ts:7`:
  `const API_BASE = import.meta.env.VITE_API_URL ?? "/api"`. Its live value cannot be read back (Vercel
  "sensitive" type), but Milestone 7's own live verification (checking the actual deployed JS bundle
  directly) already confirmed the production bundle calls `https://api.aisecurewatch.com`, and no
  architecture change since then would have altered that -- **the Azure build pipeline must set this
  exact value explicitly**, not rely on reading it from Vercel.
- **Authentication flow**: session-token-based (`POST /v1/auth/login`, bearer token in
  `localStorage`-backed helpers), entirely client-side against the API -- no cookies, no server-side
  session, no SSR-dependent auth state. Unaffected by which static host serves the JS bundle.
- **API base URL**: `https://api.aisecurewatch.com`, out of this milestone's scope, unchanged, confirmed
  healthy (`GET /openapi.json` returns `200` as of this session).
- **Runtime configuration**: none beyond the two build-time env vars above -- no runtime config-fetching,
  no feature-flag service.
- **Route handling**: `react-router`'s standard client-side routing; every route needs the same SPA
  fallback (any path -> `index.html`, letting the client router take over) since there is no per-route
  prerendering here.
- **SPA/SSR requirements**: SPA only, no SSR, confirmed by `package.json`'s single `vite build` script
  (no `--ssr` step, unlike the marketing site).
- **Asset handling**: standard Vite content-hashed assets under `dist/assets/`.
- **External integrations**: Mixpanel analytics (optional, same pattern as the marketing site).
- **Vercel-specific functionality used**: none beyond static hosting + one SPA-fallback rewrite (`.vercel`
  project metadata; no `api/` directory, no functions/cron configured).

## Vercel (full inventory, not assumed from memory)

**VERIFIED** via `vercel project ls`, `vercel domains inspect aisecurewatch.com`, and per-project
`vercel env ls production`, this session:

| Project | Bound domain(s) | Repo | In this milestone's scope? |
|---|---|---|---|
| `aisecurewatch-website` | `aisecurewatch.com`, `www.aisecurewatch.com` | `Payreality-website` | **Yes** -- the marketing site |
| `pay-reality-demo` | `payreality.aisecurewatch.com` | `PayReality` | **Yes** -- the dashboard |
| `payreality-demo-public` | `demo.aisecurewatch.com` | `PayReality` | **No** -- not one of this milestone's two named domains; left untouched |
| `demo` | none (only its own `*.vercel.app`) | an unrelated, orphaned repo | **No** -- confirmed orphaned in Milestone 7's own audit, unrelated to this migration |

- **Production branches**: `main` for both in-scope projects (standard Vercel git integration).
- **Build settings** (`vercel project inspect`): both report Framework Preset `Vite`, Build Command
  `npm run build` (Vercel auto-detects; the actual `package.json` script is the three-step chain for the
  marketing site, the single `vite build` for the dashboard), Output Directory `None` (Vercel's
  Vite-preset default auto-detection of `dist/`), Install Command the npm/yarn/pnpm/bun auto-detect
  default (this repo's `package-lock.json` means `npm install` is what actually runs).
- **Environment variables**: enumerated above per project; no other Vercel-specific env vars found
  (no `VERCEL_*` variables consumed by application code in either repo, confirmed via
  `git grep -i "process.env.VERCEL\|import.meta.env.VERCEL"` in both, zero hits).
- **Deployment hooks**: none configured on either in-scope project.
- **Redirects/rewrites**: covered above per app (marketing site's SPA-fallback rewrite; dashboard has an
  equivalent single rewrite rule, same shape).
- **Serverless/edge functions**: none in either project.
- **Cron jobs**: none in either project.
- **Framework-specific Vercel functionality**: none found beyond the standard Vite static-build
  detection.

## DNS (VERIFIED this session, and re-confirming Milestone 7's own findings still hold)

**Critical constraint for this milestone, disclosed immediately rather than discovered mid-cutover**:
`aisecurewatch.com`'s DNS zone is hosted at Namecheap (`dns1/dns2.registrar-servers.com`), a third-party
registrar with **no API credential available in this environment** (confirmed in Milestone 7, unchanged
since -- `vercel domains inspect aisecurewatch.com` itself shows the "Current Nameservers" as
`registrar-servers.com`, not Vercel's own `ns1/ns2.vercel-dns.com`, meaning Vercel is not authoritative
DNS either). **Any DNS record change (Phase 5/6 of this milestone) requires the user to make the change
manually at Namecheap**, exactly as Milestone 7's `api.aisecurewatch.com` cutover required. This is not a
gap in this session's tooling to work around; it is the actual, real operational boundary, and this audit
states it up front rather than discovering it at the cutover step.

Current records relevant to this migration, **freshly re-verified live this session** against Google's
public resolver (`8.8.8.8`), not merely carried forward from Milestone 7: `aisecurewatch.com` A ->
`216.198.79.1` (Vercel); `www.aisecurewatch.com` CNAME -> `050e7dbf8560f39d.vercel-dns-017.com` (Vercel
edge); `payreality.aisecurewatch.com` A -> `76.76.21.21` (Vercel). Zero drift from Milestone 7's own
findings. MX (ImprovMX email) and TXT (SPF + Google site verification) records exist on the same zone and
**must not be touched** by this migration -- they have nothing to do with either frontend.

## Phase 2: Secrets audit (VERIFIED, both repositories clean)

**Marketing website** (`Payreality-website`, 55 commits total): filename scan (current tree + every file
ever added across full history) found only `.env.example` (a template with empty placeholder values, no
real secret). Content pattern scan (current tree, and full-history pickaxe search for AWS keys, GitHub
tokens, Anthropic keys, and PEM-format private key headers) found zero matches.

**Dashboard** (`PayReality`, 185 commits total): filename scan found only `.env.example`,
`server/.env.example` (confirmed by reading it directly: every secret field -- `EVIDENCE_SIGNING_KEY_B64`,
`ADMIN_API_KEY`, `ANTHROPIC_API_KEY` -- is blank in the template, with a comment describing how to
generate a real value locally, never a committed real one), and a documentation guide *about* secrets
management (not itself a secret). Content pattern scan (current tree excluding vendored `.venv`/
`node_modules`, and full-history pickaxe search for the same patterns as above) found zero matches.

**Conclusion**: no production secret, API key, credential, certificate, or private key was found
committed to either repository's current tree or its full git history. **Both repositories are ready for
the private-repository transition from a secrets-exposure standpoint** -- this does not by itself
complete Phase 2 (deployment-dependency mapping and testing private-repo CI/CD access still remain, see
`MILESTONE_16_COMPLETION_SUMMARY.md`), but it removes the one blocker that would have required history
rewriting (`git filter-repo`/BFG) before privacy could even be considered.

## What this audit did not (yet) do

Deployment-dependency mapping for CI/CD against a *private* repository (does Azure's deployment
mechanism need a GitHub App install, a PAT, or a deploy key; does anything else depend on either repo
being public) is **PLANNED**, addressed in the Phase 1/2 sections of
`MILESTONE_16_AZURE_FRONTEND_ARCHITECTURE.md` rather than this audit document.
