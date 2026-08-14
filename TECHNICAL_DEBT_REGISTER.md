# Technical Debt Register

Every known, real gap accumulated across this engagement's own milestones, not a fresh audit. Each item names where it was found and its current status. VERIFIED means directly confirmed against live systems or code; nothing here is guessed.

## Security and correctness

| Item | Found | Status |
|---|---|---|
| `GET /v1/evidence/chain/verify` returns `total: 0` against an organization with confirmed real Evidence records | Milestone 5 | Open, un-root-caused. Does not crash (the Milestone 3 fix for the original `TypeError` holds); the count itself is simply wrong. Should be root-caused before a pilot customer's own team runs this exact check. |
| No account lockout after repeated failed logins | Disclosed since early in the engagement, restated in Milestone 8's Security Overview | Open, not built. |
| Rate limiting is in-process memory only; a second backend instance shares no rate-limit state with the first | Disclosed early, restated Milestone 8 | Open. Blocks safely scaling horizontally past one instance without also fixing this. |
| MFA schema exists (`User.mfa_enabled`, an organization-level setting) but no login-time challenge flow is implemented | Disclosed early, restated Milestone 8 | Open, schema-ready only. |
| `AuthorityRelationship.cross_org_approved` is dead schema, defined, never read | Milestone 3 | Open, disclosed, not removed. |
| `runtime_policy_service.py`'s own lifecycle-event writes don't stamp `organization_id` on the event row itself | Milestone 3 | Open, disclosed. |
| No delete/retention path exists for Authority Intelligence documents in Blob Storage or Postgres, for any organization | Milestone 3 | Open. Relevant to any future data-retention or right-to-deletion requirement. |
| Unclear whether the dashboard UI hides or disables actions a user's own RBAC role doesn't permit, versus only discovering this after the backend rejects the request | Milestone 8 | Open, flagged for a dedicated follow-up audit, not yet investigated. |

## Infrastructure

| Item | Found | Status |
|---|---|---|
| `psql-payreality-staging-cus-restoretest`, a standalone Postgres server created for a Milestone 5 restore drill | Milestone 5 | Open. Real, ongoing cost. Keep-or-delete decision never made across three subsequent milestones. |
| `kv-pr-staging-adzg`, a soft-deleted Key Vault, name permanently reserved until 2026-11-08 | Milestone 3 | Not billed, but real reserved state; will resolve itself on that date. |
| No zone-redundant high availability anywhere in the Azure deployment | Milestone 4 | Open, deliberate cost/complexity tradeoff at current scale, not an oversight, but should be revisited before real production load. |
| Terraform's `ai-foundry`/`ai-search` modules are unconditional in the shared root composition; no per-environment toggle exists | Milestone 4, confirmed still true through Milestone 6-7 | Open. A future `terraform apply` against any environment could silently attempt to (re)create both. |
| Azure's free Managed Certificate provisioning has no Terraform-native expression in the pinned provider version | Milestone 7 | Not a defect, a real provider limitation; worked around via direct `az` CLI, documented as a deliberate, narrow exception to this project's IaC discipline. |
| Storage accounts (`stprstagingadzg`, `stprprodtq1k`) allow public network access at the account level even though private endpoints exist for each | Milestone 4 | Open. A private endpoint is additive, not exclusive; the public path remains reachable. |
| The Terraform remote-state storage account (`sttfstatepr8p3t4s`) allows public blob access | Milestone 4 | Open. State files can contain sensitive values; this is the one place this project's otherwise-consistent private-by-default posture was not applied. |
| No CI/CD deployment pipeline exists; every deploy across every milestone has been a manually run `az`/`terraform` command sequence | Designed (Milestone 4's Phase 5) but never implemented | Open. The design exists and is ready to build. |
| Whether Render's database ever held real data needing migration | Open since Milestone 4 | Never resolved; no credentialed access to check directly has existed at any point in this engagement. |
| Render itself has not been retired; its free Postgres instance auto-expires on a fixed date independent of any human decision | Milestone 7 | Open, time-boxed. Whatever decision gets made about Render, it should happen with this date in mind, not after it. |

## Product surface

| Item | Found | Status |
|---|---|---|
| AI Policy Builder (the single-document extraction pipeline) is functionally redundant with Authority Builder, which now produces the same output shape with richer explainability fields and the same underlying AI provider | Milestone 6 (`AI_PIPELINE_CONSOLIDATION_REVIEW.md`), reaffirmed Milestone 8 (`INFORMATION_ARCHITECTURE_V2.md`) | Migrated onto the same canonical AI provider (Milestone 6); recommended for full retirement as a separate user-facing surface, not yet executed. |
| The single-document AI Policy Builder's dashboard surface (`/governance/upload`) has zero inbound links anywhere in the current navigation, reachable only by direct URL | Milestone 8 | Open, matches the retirement recommendation above. |
| Governance (the dashboard's policy-authoring area) has no sidebar-level sub-navigation despite containing five materially different workflows | Milestone 8 | Open, a specific, scoped fix already designed (`NAVIGATION_REDESIGN.md`), not yet implemented. |
| Naming drift: "Evidence Vault" (on-page, pre-rename) versus "Evidence" (nav); "Rule" (page title) versus "Runtime Policy" (everywhere else); "Policy Studio" (directory name, error copy) versus "Governance" (nav) | Milestone 8 | Open, small, specified fixes, not yet applied. |
| `theme.css` and `theme.ts` contain contradictory comments about which theme is the platform default | Milestone 8 | Open, a documentation trap, not a currently-visible bug (light wins in practice). |
| `OrganisationSettingsPage.tsx` contains a stale claim that Azure OpenAI/Bedrock integration doesn't exist, no longer true since Milestone 6 | Milestone 8 | Open, a one-line content fix. |
| Inconsistent loading-state coverage across dashboard screens (some have real skeletons, `PlatformOverview.tsx` and `CorpusUploadPage.tsx`'s history table do not) | Milestone 8 | Open, small, specified fix. |

## External narrative

| Item | Found | Status |
|---|---|---|
| The website claimed the core runtime was built in Rust with gRPC, across three files including its own search-engine structured data | Milestone 8, corrected Milestone 9 | **Resolved.** See `PUBLIC_TECHNICAL_ACCURACY_UPDATE.md`. |
| The website's "sub-millisecond evaluation" claim is plausible for OPA's own real-world performance but has never been independently benchmarked in isolation within this engagement | Milestone 9 | Open. Not known to be false; simply not yet verified to the standard this platform holds every other public claim to. |
| The website's "Book a Demo" primary conversion mechanism is a `mailto:` link with no backend and no delivery confirmation | Milestone 8 | Open, a real risk now that the company is actively pursuing pilot conversations. |
| No SOC 2 or ISO 27001 certification exists, and the process has not started | Disclosed early, reaffirmed every subsequent milestone | Open, by design at this stage; see `COMPANY_READINESS_ASSESSMENT.md` for the current recommendation. |
| Python is the only SDK language; Node.js, Go, Java, .NET, and Rust are on the roadmap, not started | Ongoing, correctly disclosed on the website itself | Not debt in the sense of a defect; a real, honestly-stated scope limit. |
| No pre-built enterprise system connectors exist (specific ERPs, procurement tools); integration today is direct API/SDK only | Ongoing, correctly disclosed on the website itself | Not debt; a real, honestly-stated scope limit, expand only once a real pilot builds a specific one. |

## What this register deliberately excludes

Anything already fully resolved with no open follow-up (for example, `domain/extraction/`'s dead code, removed outright in Milestone 6, or the Milestone 3 Evidence chain crash, genuinely fixed) is not listed here; a debt register that never shrinks stops being useful as a signal of what actually still needs attention.
