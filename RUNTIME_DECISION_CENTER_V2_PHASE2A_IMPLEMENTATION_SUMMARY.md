# Runtime Decision Center V2, Phase 2A Implementation Summary

Scope: the specific gaps `RUNTIME_DECISION_CENTER_V2_UX_AUDIT.md` and `RUNTIME_DECISION_CENTER_V2_DATA_PROVENANCE.md` found, and only those. No Enterprise Knowledge, no live per-condition explainability, no multi-hop authority, no new policy engine, no new evidence architecture; all explicitly out of scope, none touched.

## Workstream 2: UX corrections

Six of the ten audit findings were fixed, each clearly supported by an existing pattern already used elsewhere on this same page or in this app, low risk, unrelated to any new backend functionality:

1. **Eyebrow-label inconsistency**: the three column headers now use `text-xs font-mono uppercase tracking-widest`, matching `PlatformOverview.tsx`/`LiveAssurance.tsx`'s existing pattern exactly, instead of a near-miss the page had invented.
2. **Severity-mismatched glyph**: the "unavailable" pipeline stage no longer shows a "×" (which reads as an error even for neutral cases like "no principal set yet"); only the "done" state still shows a checkmark.
3. **Loading-state inconsistency**: the two remaining bare "Loading..." text spots (the pipeline's risk-classification stage, the Decision panel's risk-classification row) now use the app's existing `<Skeleton>` component, matching every other loading state on the page.
4. **Italic for "not set" values**: removed; the existing color-only convention (`--pr-text-disabled`) already used everywhere else in this app now applies here too.
5. **Layout-stability**: the "Acting identity" card now always renders, with its own empty-state message before an agent is selected, matching the exact pattern the Runtime Authority and Decision columns already use on this same page, instead of popping into existence on selection.
6. **Glyph accessibility**: the stage-node ✓ glyph now carries `aria-hidden="true"`, since the adjacent chip text ("Confirmed," etc.) is the real accessible label.
7. **Label accuracy**: "Previous record hash" is now "Prior record's hash," since the value is a hash of the preceding chained record, not this record's own hash, a small copy correction the Data Provenance audit surfaced.

**Left open, deliberately:** the Evidence section's density (fixing it well means reorganizing visual hierarchy, which is a presentation redesign, out of this task's scope, not a low-risk fix); the `--pr-text-disabled` contrast ratio (a system-wide design token this one page has no standing to change unilaterally); and the two audit items that were never fixable findings in the first place, responsive behavior and general "does it feel right" impressions, both of which need an actual browser, still unavailable.

## Workstream 3: Signer and certificate detail

Added a "Signer" card to the Evidence section, sourced entirely from `agentsApi.listCertificates(agentId)`, an endpoint that already existed and was already used elsewhere (`AgentDetailPage.tsx`). Fields shown: Certificate ID, Status, Public key (truncated), Issued at, Activated at, Rotated at, Expires at, Revoked at, exactly the real columns on the `Certificate` model (`server/app/db/models.py:341-357`), nothing invented.

Deliberately scoped to **the certificate that signed this specific submission**, captured at submit time (`agent.certificate_id`, the same value already sent as the `X-PayReality-Key-Id` header), not "whatever the agent's current certificate happens to be." This distinction matters because no per-decision record of which certificate signed it is persisted anywhere in the backend (confirmed while building this); showing "current certificate" instead would silently misattribute an old decision's signer after any later key rotation. Scoping it to the just-submitted decision's own known-correct certificate avoids that failure mode entirely, at the cost of this data only being available for a decision made in the current page session, not one loaded from history (Phase 1 has no "load an existing decision by id" entry point yet regardless).

## Workstream 4: Decision metadata

Checked before changing anything, per instruction: `policy_version`, `policy_bundle_hash`, and `authority_version` were already real, already computed, and already persisted, just onto `Evidence.payload`, not `Decision` (confirmed in the Phase 1 Data Provenance audit) or `GetDecisionResponse`. `Decision.created_at` was a real, existing column, simply never included in the response schema at all.

Made the smallest possible backend addition, exactly as instructed:
- `server/app/schemas/intent.py`: `GetDecisionResponse` gains `created_at: datetime` (direct column read) and `policy_version`/`policy_bundle_hash`/`authority_version` (all `Optional`, `None` when absent).
- `server/app/routers/intents.py`'s `get_decision`: reads this decision's own earliest `Evidence` record (ordered by `created_at` ascending) and pulls the three fields from its payload via `.get()`, which safely returns `None` if the key or the record itself is absent. No new table, no new column beyond the one addition to a response schema, no new computation of anything, this reads a value that was already computed and already stored by Phase 1's own code.

Wired into the frontend: the Decision panel now shows Policy version/Policy bundle hash/Decision engine version immediately once the decision loads, no longer waiting on the separate Evidence fetch; the Timeline gained a real "Decision recorded" entry using the newly-exposed `created_at`.

## Workstream 5: Historical decision integrity, research only

Full findings in `RUNTIME_DECISION_CENTER_HISTORICAL_POLICY_BINDING_ANALYSIS.md`. Summary: the problem is narrower than the prior Phase 2 audit assumed. `Decision.policy_id` already points to an immutable, retired-not-deleted `Policy` row (confirmed by reading `deploy_policy`'s own behavior), and every historical policy version is already immutable (`RuntimePolicyRecord`, "never mutated after creation," by its own docstring). The only missing piece is the join between them, which specific `RuntimePolicyRecord`s a given compiled bundle contained, a manifest that's already computed in memory at compile time (`compiler_v2/bundle_builder.py`'s own `manifest` dict) and currently discarded rather than persisted. Not implemented in this task, per instruction.

## Verification performed

- `npm run build`: passes (production and `VITE_PUBLIC_DEMO_MODE=true` both).
- Backend: full test suite, `pytest -q` with no filter, 373 passed, 0 failed.
- `GetDecisionResponse` validated directly in a real Python session against both a fully-populated case and an all-null case (a decision where no policy was ever evaluated), confirming the schema addition is backward-compatible.
- Live schema diff (before this task's backend deploy vs. after): confirmed `authority_version`/`created_at`/`policy_bundle_hash`/`policy_version` are present on the live production `/openapi.json`'s `GetDecisionResponse` definition, proving the change is genuinely deployed, not just merged.
- Live frontend bundle grepped for markers unique to this round's UI changes; all found.
- No backend files beyond `schemas/intent.py` and `routers/intents.py` were touched. No new persistence mechanism, no new table, no redesign of the decision architecture.

## What regressed: nothing found

Signing/evidence flow: unchanged (`handleSubmit`'s signing logic, `postSigned` call, and the existing resolve flow were not touched beyond adding the new fetch calls alongside them). Tenant isolation: unchanged, in both directions, the endpoint this task modified had no organization scoping before and has none after, a pre-existing fact restated in the Final Verification doc rather than silently left ambiguous.
