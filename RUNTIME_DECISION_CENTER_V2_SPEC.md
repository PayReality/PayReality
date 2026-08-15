# Runtime Decision Center V2 Design Specification

Companion to the interactive wireframe (published separately). Redesigns `src/app/live/pages/LiveTestIntent.tsx` (currently a developer-style form: Agent/Action/Amount/Currency, "Submit Signed Intent") into the platform's flagship page: the moment an AI agent asks permission to act and Runtime Authority decides, before execution.

Every claim below is labeled:
- **LIVE**: real data exists today; this is a reskin of an existing value.
- **PLANNED**: real, computed data exists server-side but isn't exposed on the relevant API response yet, or a real engine exists but isn't wired to this code path. Scoped, bounded backend work.
- **VISION**: no backing implementation anywhere. Shown honestly as a placeholder, never faked as live.

This labeling comes from a direct code audit (`server/app/schemas/intent.py`, `server/app/domain/decision/engine.py`, `server/app/domain/policy_simulation/explainer.py`, `server/app/services/authority_context_service.py`, `server/app/db/models.py`, `src/app/live/types.ts`), not from the architecture docs alone. Those docs (`ENTERPRISE_KNOWLEDGE_ARCHITECTURE.md`) already say plainly that Enterprise Knowledge has zero code; this spec confirms that and applies the same rigor to every other claim in the brief.

## 1. Information architecture

```
Runtime Decision Center
├── Masthead (page title, live decision id/agent/timestamp, scenario state)
├── Hero (three columns, always visible, the page's core)
│   ├── Business Context (left)
│   ├── Runtime Authority Pipeline (center)
│   └── Decision (right)
├── Enterprise Knowledge          [VISION]
├── Runtime Policy Evaluation     [LIVE list, PLANNED per-condition detail]
├── Decision Explanation          [PLANNED]
├── Authority Chain               [LIVE 1-hop, VISION multi-level]
├── Evidence                      [LIVE]
└── Timeline                      [LIVE]
```

The hero is fixed above the fold; the six panels below are independently collapsible cards a returning user can hide once they trust the summary. This continues the "scanned and operated, not read top to bottom" pattern already established elsewhere in this app's design language.

## 2. Component hierarchy

```
RuntimeDecisionCenter
├── DecisionMasthead                    (title, decision id, agent, requested-at)
├── DecisionHero
│   ├── BusinessContextColumn
│   │   ├── ContextCard(agent/operation/vendor/amount/system)   -- LIVE
│   │   ├── ContextCard(business unit/department)               -- LIVE (via Agent -> Principal -> org structure)
│   │   └── ContextCard(risk classification)                    -- LIVE
│   ├── AuthorityPipeline
│   │   └── PipelineStage x 8 (icon, name, chip, detail, timestamp)
│   └── DecisionPanel
│       ├── VerdictBadge (ALLOW / DENY / ESCALATE / BLOCKED / loading / empty)
│       ├── DecisionStatList (authority level, policy version, OPA bundle, evidence flag, decision time)
│       └── ApprovalActions (Approve / Deny, only in the escalated state)
├── EnterpriseKnowledgePanel            (VISION, rendered with an explicit "illustrative" overlay)
├── PolicyEvaluationPanel
│   └── PolicyRow x N (expandable to ConditionBreakdown)
├── ExplanationPanel (ReasonList)
├── AuthorityChainPanel (ChainNode x N, ghosted beyond 1 hop)
├── EvidencePanel (EvidenceFieldGrid, "Open full Evidence record" link)
└── TimelinePanel (TimelineRow x N)
```

Each panel is a self-contained component with its own loading/empty/error boundary. No panel's failure should blank the page: this directly continues the `describeApiError` discipline just shipped, where every panel names its own real failure instead of a shared generic one.

## 3. UX flow

1. **Entry.** A user arrives either by submitting a new intent (the existing test-intent form, kept but reframed as "Request a decision," not removed; this is still how a human triggers a decision manually) or by opening a decision from Evidence/Assurance/Agent Detail (a decision already has an id, so the Decision Center becomes its permanent detail view, not just a one-shot submission form).
2. **Empty.** No decision selected/submitted: pipeline shows all 8 stages `Pending` (unlit grey), Decision panel shows a calm "Awaiting request" placeholder, Business Context shows the actual input form (Agent, Action, Amount, Currency, the current fields, now styled as enterprise cards with selects rather than raw HTML dropdowns).
3. **Submit, then Loading.** Pipeline animates stage by stage in real sequence (matches the current poll-until-RESOLVED behavior in `LiveTestIntent.tsx:79-92`, just visualized instead of hidden behind a spinner). Each stage transitions Pending to Running to Passed/Failed as its real result arrives; today's API returns the outcome atomically, so the animation is a presentation layer replaying a known-good result at readable speed (150 to 400ms per stage) rather than a truly stage-by-stage backend stream. PLANNED: a real intermediate-state stream (SSE/WebSocket) would remove this gap. The sequencing itself is still honest given what each stage represents; it just isn't independently observable yet.
4. **Resolved: ALLOW.** Every stage `Passed`, Decision panel shows the green verdict, all decision stats populate, Evidence panel shows the real created record.
5. **Resolved: DENY.** The stage that actually failed (Runtime Policies, in practice) shows `Failed` in red, subsequent stages still complete (Evidence is created for denials too, per `intent_service.py`), Decision panel shows the red verdict and the specific failing policy/condition from the Explanation panel.
6. **Resolved: HUMAN_REVIEW ("Escalate").** This is the platform's only actual "waiting for approval" state (confirmed: no separate decision-level approval workflow exists beyond `outcome === HUMAN_REVIEW` plus `status: PENDING`). Last stage shows `Waiting`, Decision panel shows the amber verdict plus Approve/Deny buttons that call the same resolve endpoint `LiveTestIntent.tsx` already calls today. This is a reskin of existing capability, not new capability.
7. **System failure ("Blocked").** OPA unreachable or an unhandled evaluation error. Distinct from DENY: the pipeline shows `Blocked` (struck through, grey) on every stage from the failure point on, and the Decision panel explicitly says "Runtime Authority could not confirm authorization, so the action never defaults to allow." This reuses the existing fail-closed language already on `PlatformOverview.tsx`, applied here as a literal decision outcome rather than marketing copy.

## 4. Interaction design

- **Pipeline stages**: static (already-resolved decision) or animated once (freshly submitted). Never looping, never re-animating on every visit; a returning viewer of a week-old decision should see static Passed states immediately, not a replay.
- **Policy rows**: click-to-expand accordion, one open at a time by default (matches `PolicyWorkspacePage`'s existing disclosure pattern), showing field/operator/expected/actual per condition.
- **Evidence panel**: fields are read only; "Open full Evidence record" navigates to the existing `/evidence` detail view rather than duplicating it here.
- **Approval actions**: only rendered when `outcome === HUMAN_REVIEW` and unresolved; disabled with a tooltip (matching the `CorpusReviewPage.tsx` disabled-button pattern already shipped) for a viewer lacking `authority.review`.
- **Enterprise Knowledge panel**: always visually distinct, a subtle diagonal-hatch or blur overlay with "Illustrative, no live connector exists yet," never presented at the same visual weight as live panels. This is the one section where restraint matters most: this exact page redesign was requested partly because a previous page (Integrations tab) said "connected" in a way that didn't match reality. This panel must not repeat that mistake in the other direction.

## 5. States

| State | Pipeline | Decision panel | Notes |
|---|---|---|---|
| Empty | All Pending | "Awaiting request" placeholder | Business Context shows the live input form |
| Loading | Sequential Running to Passed | Pulsing "Evaluating..." | Real poll already exists; this animates its result |
| Allow | All Passed | Green ALLOW, full stats | |
| Deny | Fails at Runtime Policies | Red DENY, failing condition surfaced | Evidence still created |
| Escalate (HUMAN_REVIEW) | Waiting at final stage | Amber ESCALATE plus Approve/Deny | The only real "awaiting approval" state |
| Blocked (system error) | Blocked from failure point | Neutral "could not confirm authorization" | Fail-closed language, distinct from DENY |

## 6. What ships now vs. later

**Phase 1, reskin with real data (no backend changes):** three-column layout, pipeline visualization driven by the existing decision result, Business Context cards from existing Agent/Decision fields, Decision panel populated from fields `GetDecisionResponse` already returns, Policy Evaluation panel listing `evaluated_mandate_ids` (real, flat list, no per-condition detail yet), Authority Chain shown honestly as one hop, Evidence panel, Timeline from existing timestamps.

**Phase 2, small scoped backend additions:** expose `policy_version`/`policy_bundle_hash` (already computed in `decision/engine.py`, already written to Evidence) directly on `GetDecisionResponse` so the Decision panel doesn't need a second fetch; run the existing Simulator explainer (`policy_simulation/explainer.py`) against a resolved decision's stored context to populate real per-condition breakdown and the Explanation panel with genuine reasoning instead of a static example.

**Phase 3, genuinely new capability, only once a real need exists:** Enterprise Knowledge connectors (per `ENTERPRISE_KNOWLEDGE_ARCHITECTURE.md`'s own explicit deferral), multi-hop authority chain resolution (already named in that architecture doc as a Phase 4 concept), a live intermediate-state stream so the pipeline reflects real stage-by-stage backend progress rather than replaying a known result.

## 7. Fields the brief requested that don't exist today

Reported for completeness, not silently dropped. **Cost Centre** only exists as an arbitrary free-text intent-context value today (e.g. `context.cost_center`), not a structured/queryable field. **Country** has no field anywhere in the data model. **Requester** as distinct from Agent doesn't exist; the agent's identity is the only "who acted" concept, there's no separate human requester field. **Confidence score on a decision** doesn't exist; confidence exists only in AI Authority Builder's document-extraction pipeline, an unrelated subsystem. None of these are shown as live in the wireframe. Business Context explicitly marks Requester/Country as not yet captured rather than omitting them silently, so the gap is visible to whoever reviews this spec next.
