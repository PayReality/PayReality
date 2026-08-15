# Runtime Decision Center V2, Phase 1 Implementation Summary

Phase 1 of `RUNTIME_DECISION_CENTER_V2_SPEC.md` is implemented and built. This covers only what that spec labeled LIVE: a reskin of `src/app/live/pages/LiveTestIntent.tsx` (routed at `/decisions`) using real data the platform already produces. Nothing labeled PLANNED or VISION was implemented or visually implied.

## What changed

- `src/app/live/pages/LiveTestIntent.tsx`: full rewrite into the three-column layout (Business Context / Runtime Authority / Decision), plus Authority Chain, Runtime Policy Evaluation, Evidence, and Timeline sections below. Same exported component name and route, so no other file needed to change.
- `src/app/live/types.ts`: `EvidencePayload` gained eight fields (`principal_name`, `authority_version`, `policy_version`, `policy_bundle_hash`, `resolved_by`, `responsible_party`, `reviewer`, `review_outcome`) that the backend already writes into the real Evidence payload today; the frontend type simply hadn't declared them before. No backend change was needed or made.
- `src/app/demo/mockRouter.ts`: the existing `GET /v1/evidence` mock now honors a `decision_id` query filter, matching the real backend's `list_evidence(db, organization.id, decision_id)` parameter, so the demo environment keeps working against the redesigned page.

No backend files changed. No new API endpoints were added; every request the page makes was already a real, existing endpoint.

## What each state actually shows, and its real API source

| State | Source |
|---|---|
| Empty | No `decision` yet. Business Context still resolves and shows the selected agent's real principal/department via `GET /v1/principals/{id}/authority-context`, so the preview is real, not placeholder text. |
| Evaluating | `submitting === true` and no `decision` yet: a single "Evaluating..." indicator, not a staged animation implying independently observed sub-steps the backend doesn't expose. |
| Allow / Deny | `decision.outcome`, `decision.reason` (via the existing `describeReason`), `decision.evaluated_mandates`, `decision.evaluated_mandate_ids`, `decision.enterprise_system_name`: all direct fields of `GET /v1/decisions/{id}` (`GetDecisionResponse`), unchanged endpoint. |
| Escalate / Awaiting Approval | `decision.outcome === "HUMAN_REVIEW" && decision.status === "PENDING"`. Approve/Deny call the existing `POST /v1/decisions/{id}/resolve`, already-shipped capability, only relocated into the new Decision panel. |
| Blocked | A real submission-time error (signature/replay/agent-status rejection, or any other failure before a decision was ever produced) shown via the existing `describeApiError`, with the platform's own already-shipped fail-closed sentence (`PlatformOverview.tsx`) reused verbatim, not new copy. |

Risk classification, authority context (organization/business unit/department/team/role), and delegation edges all come from `GET /v1/evidence?decision_id={id}` (the real, already-existing `decision_id` filter on `list_evidence`), fetched as soon as the intent is submitted since Evidence is created synchronously at that point regardless of outcome. This is a genuinely richer real-data source than the previous page ever read from.

## What could not be implemented because the backend doesn't expose it

- **Per-condition policy explainability.** `evaluated_mandates`/`evaluated_mandate_ids` is a flat list of which policies were evaluated; no pass/fail per condition is available for live decisions (the Simulator's explainer exists but isn't wired to this code path). The Runtime Policy Evaluation panel lists the real matched policies only, with an explicit caption saying condition-level detail isn't available yet, rather than fabricating an expand-to-see-conditions affordance.
- **Multi-hop authority chain.** Only one hop (principal to agent) is resolvable from `authority_context_service`. The Authority Chain panel shows exactly that, nothing ghosted or implied beyond it.
- **Decision-level timestamp.** `GetDecisionResponse` has no `created_at` of its own. The Timeline is built from Evidence's real `created_at`/`recorded_at`, `resolution.created_at`, and a client-observed "request sent" time explicitly labeled as local, not server-confirmed.
- **Enterprise Knowledge.** No code exists anywhere in the platform for this. Not shown at all, not even as a labeled placeholder, since a visible pipeline stage or panel for a nonexistent capability would itself overstate what the product does. A code comment marks where a future stage would slot into the pipeline logic; nothing renders from it today.
- **Decision confidence score.** Doesn't exist for runtime decisions (confidence exists only in the unrelated AI Authority Builder document-extraction pipeline). Not shown.
- **Cost Centre / Country / Requester as structured fields.** None exist in the data model. Not shown as fields; the existing free-text `cost_center` value already sent in the intent's `context` object is unchanged and was never a UI-facing claim.

## Verification performed

- `npm run build`: passes, both the production build and a `VITE_PUBLIC_DEMO_MODE=true` build (confirms the demo environment's mock router still resolves every call this page makes).
- This repository has no frontend type-check or test script (`package.json` has only `build`/`dev`; no TypeScript devDependency, no test framework). `npm run build` (Vite/esbuild) is the full extent of automated frontend verification this project runs, unchanged from before this work.
- Backend: no backend files were modified. Ran the existing intent/evidence/decision-related backend test suite as a safety check on the endpoints this page now relies on more heavily (`GET /v1/evidence?decision_id=`, `GET /v1/principals/{id}/authority-context`): 36 passed, 0 failed.
- Every field rendered was traced to its exact source: `server/app/schemas/intent.py` (`GetDecisionResponse`), `server/app/services/intent_service.py` (`_build_evidence_payload`), `server/app/services/authority_context_service.py` (`AuthorityContext`/`classify_risk`), `server/app/services/resolution_service.py` (the second Evidence record on resolution), read directly rather than assumed from the earlier design spec.

## What was not tested

No browser-automation tool was available in this session, so the redesigned page was not clicked through interactively in a running browser. What's verified above is build correctness (it compiles, the demo mock router resolves every call) and data-contract correctness (every displayed field traced to a real, currently-returned API field), not manually-observed UI/UX correctness (layout at real viewport sizes, click-through of Approve/Deny, actual visual appearance of each state). A manual pass in a browser against a real or staging backend is the recommended next step before treating this as fully verified, exactly as the standing frontend-change guidance for this project requires.
