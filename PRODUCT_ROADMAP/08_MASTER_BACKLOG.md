# Part 8 — Master Implementation Backlog

**Status:** final. This is the single, ordered build sequence, resolving the tier structure of [04](04_BUILD_ROADMAP.md)/[07](07_IMPLEMENTATION_QUEUE.md) into one recommended order. Where two items have no dependency on each other, they are marked to run in parallel rather than artificially serialized — a real engineering team has more than one person, and this backlog should reflect that rather than pretend otherwise.

## Track A — Infrastructure foundation (must lead everything else)

1. **Q-C1** — Migrate production Postgres off the expiring free tier; verify backup/restore.
2. **Q-C2a**, **Q-C2b** *(parallel with each other, both depend on #1)* — Error tracking; scheduled smoke-test monitoring.
3. **Q-C2c** *(depends on #2)* — Real alerting wired to both.
4. **Q-H2a** *(depends on #1, parallel with #2–3)* — Staging environment provisioned.
5. **Q-H2b** *(depends on #4)* — Auto-deploy to staging on merge.
6. **Q-H2c** *(depends on #5)* — Scripted, manual production promotion.

## Track B — Trust and legal foundation (parallel with Track A from day one)

7. **Q-C4a** — Internal SOC 2 gap assessment (longest lead time in this backlog; start immediately).
8. **Q-C5a**, **Q-C5b** *(parallel with each other and with #7)* — Privacy Policy/Terms; DPA template.
9. **Q-C4b** *(depends on Track A's #1 for a stable environment to test)* — Third-party penetration test.
10. **Q-H3a**, **Q-H3b** *(parallel with #7–9)* — Ticketing tool; SLA document.

## Track C — Cheap, high-leverage fixes (parallel with Tracks A and B; no dependencies)

11. **Q-C3** — Fix the misleading Notifications settings tab.
12. **Q-H4** — Wire SDK tests into CI.
13. **Q-H5a** *(then)* **Q-H5b** — Regenerate API docs; add a drift check.

## Track D — Authorization Receipts (parallel with everything above; no dependencies, but a sustained multi-week effort)

14. **Q-H1a** — Receipt schema v1, produced alongside Evidence.
15. **Q-H1b** *(depends on #14)* — Asynchronous Merkle-root anchoring.
16. **Q-H1c** *(depends on #14)* — Export endpoint and open verification tool.

## Track E — Product surface improvements (start once Track A/B's most urgent items are underway, not necessarily finished)

17. **Q-M1** — CSV/PDF export for Decisions and Evidence.
18. **Q-M3** — Guided onboarding wizard.
19. **Q-M4** — Internal contract/invoice tracking.
20. **Q-L2** — Global search.
21. **Q-L3** — BI/trend dashboards.

## Track F — Scaling the business (sequenced after the staging/CD discipline in Track A exists)

22. **Q-M2** *(depends on #4–6)* — Per-customer provisioning automation.
23. **Q-L1** *(depends on #22, and on a real demand signal — not scheduled to a date)* — Row-level multi-tenancy design and implementation.

## Track G — Demand-gated (not scheduled; each triggers only on a named customer requirement)

24. **Q-L4** — Second-language SDK.
25. **Q-L5** — i18n infrastructure.
26. **Q-L6** — Full responsive layouts for data-dense content pages.

## Why this order

Track A comes first because every other track either depends on it directly (staging, monitoring, the penetration test needing a stable target) or benefits from not shipping into an environment that is, today, on a countdown to an outage. Track B runs in parallel from day one specifically because it has the longest lead time in the entire backlog (a SOC 2 program is measured in months) and zero technical dependency on anything else — starting it late would make it the critical path for enterprise sales regardless of how fast everything else moves. Track C exists because "cheap and high-leverage" is a real category, not a tiebreaker — these ship inside the first week or two without displacing anything else. Track D (Authorization Receipts) is deliberately marked parallel-with-everything because it is the one item in this entire backlog with a completed design and zero remaining design risk — the only reason it isn't Critical-tier is that nothing breaks today by its absence, unlike Track A. Tracks E and F are real, valuable, and correctly sequenced after the foundation exists to support them well rather than in spite of it. Track G is not scheduled because nothing in this audit found evidence any of it is needed yet — scheduling it anyway would be exactly the kind of speculative work the directive for this program explicitly ruled out.
