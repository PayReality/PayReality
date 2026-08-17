# Milestone 16: Vercel Rollback and Retirement Plan

**Status: DNS cutover is complete -- all three in-scope domains now resolve to Azure and serve correctly
(see `MILESTONE_16_PRODUCTION_VALIDATION.md`). The observation window described below starts now. Vercel
remains untouched and fully intact as the rollback target; nothing in the retirement checklist has been
executed.** This document is the plan for after the observation window passes, not a record of retirement
already performed.

## Rollback triggers (objective, decided in advance)

Any one of the following, observed after DNS cutover, is sufficient to trigger an immediate rollback --
matching this milestone's own instruction not to improvise a production fix under pressure:

- Authentication failure on the dashboard (login, session persistence, or logout broken).
- Any major dashboard route failing to load or returning a client-side routing error on direct navigation
  or refresh.
- API connectivity failure from either production frontend (CORS rejection, timeout, or unexpected error
  rate against `api.aisecurewatch.com`).
- A major, visible UI regression on either application (missing assets, broken layout, broken navigation).
- Any broken form (the marketing site's demo-request modal, or any dashboard form).
- TLS certificate failure or mismatch on either custom domain.
- Any unexpected production error rate increase, on either application, beyond ordinary baseline noise.
- Significant, user-visible performance regression.

## Rollback procedure

Revert the specific DNS record(s) changed during cutover back to their Vercel targets (see
`MILESTONE_16_PRODUCTION_VALIDATION.md`'s "Pending DNS actions" table for the exact current values to
restore). This is a same-TTL-window reversal, matching Milestone 7's own established pattern for
`api.aisecurewatch.com` -- Vercel is never stopped, suspended, or modified during the observation window,
so a rollback requires no data reconciliation and no Azure-side undo, only the DNS record itself moving
back.

## Observation window

Recommend the same window this project used for the backend cutover (Milestone 7): **at least 48-72
hours of real production traffic with zero rollback triggers**, watched via: Vercel's own project
analytics/logs (to confirm traffic has actually moved to Azure and Vercel is serving materially zero
production requests), and ordinary monitoring of `api.aisecurewatch.com`'s existing Application Insights
alerts (an unexpected error-rate or latency change coinciding with the frontend cutover would surface
there even though the backend itself didn't change, since a broken frontend often manifests as malformed
or absent API calls).

## What must be true before retirement (checklist, none checked yet)

- [x] Both custom domains (`aisecurewatch.com` + `www`, `payreality.aisecurewatch.com`) resolve to Azure
      and serve valid, trusted HTTPS. **VERIFIED LIVE.**
- [x] Both GitHub repositories confirmed private (`gh repo view`, `"isPrivate": true` on both) with CI/CD
      independently verified still working from the private state -- both deploy workflows manually
      triggered post-visibility-change and both completed successfully. **VERIFIED LIVE.**
- [x] No remaining production DNS record for either in-scope domain still points at Vercel. **VERIFIED.**
- [ ] DNS cutover complete and stable for the full observation window, zero rollback triggers -- domains
      are live and correct; the 48-72 hour elapsed-time window itself has not yet passed.
- [ ] Full production validation (`MILESTONE_16_PRODUCTION_VALIDATION.md`'s Phase 7 checklist, including
      all six Decision Center states) passed against the real domains, not just the staging subdomains --
      still needs a real browser session or the user's own manual click-through.
- [ ] Vercel's own dashboard confirms materially zero traffic to both in-scope projects during the
      observation window.

## Retirement steps, once the checklist above is fully checked (not executed yet)

1. Remove the custom domains (`aisecurewatch.com`, `www.aisecurewatch.com`, `payreality.aisecurewatch.com`)
   from their respective Vercel projects (`aisecurewatch-website`, `pay-reality-demo`) -- domain removal
   only, not project deletion, as an interim, easily-reversible step.
2. Remove now-unnecessary Vercel environment variables (`VITE_API_URL`, `VITE_MIXPANEL_TOKEN` on both
   projects) -- optional hygiene, not required for correctness, since an un-aliased Vercel deployment
   receives no real traffic regardless.
3. Confirm no GitHub Actions, webhook, or other automation still depends on Vercel's own deploy hooks for
   either repository (none were found in this milestone's Phase 0 audit, but re-check at retirement time
   in case anything changed).
4. Verify DNS no longer references Vercel for either domain (`nslookup`/DNS-over-HTTPS check against
   public resolvers, matching this milestone's own verification discipline).
5. Retire (delete or archive) the `aisecurewatch-website` and `pay-reality-demo` Vercel projects
   themselves.
6. Verify production remains healthy immediately after project retirement (both domains still resolve
   and serve correctly -- this should be a no-op verification, since DNS and the actual serving
   infrastructure were already fully on Azure before this step, but it is still checked directly rather
   than assumed).

**Explicitly out of scope for this retirement**: the `payreality-demo-public` project
(`demo.aisecurewatch.com`) and the orphaned `demo` project -- neither is one of this milestone's two named
domains, and neither is touched by any step above.

## Why nothing here has been executed

Per this milestone's own explicit rule ("Do NOT delete Vercel before the rollback window") and ordinary
operational care: retirement depends on a real, multi-day observation window against real cutover
traffic, which cannot exist inside a single working session. DNS cutover is now complete (see
`MILESTONE_16_COMPLETION_SUMMARY.md`), so the observation window starts from this point, but 48-72 hours
of real elapsed time have not passed yet, and nothing in this checklist can be truthfully marked complete
until they do.
