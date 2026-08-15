# Runtime Decision Center V2, Phase 1 Verification

## Method, stated up front

No browser-automation tool was available in this session. This was checked directly (searched for a browser/Playwright/computer-use tool before starting; none exists) rather than assumed. `WebFetch` was tried against `https://payreality.aisecurewatch.com/decisions` and, as expected for a client-rendered SPA with no server-side rendering, returned only the static `<title>` tag (`PayReality | AI Authority Layer`), no rendered content. This confirms, rather than assumes, that no tool available in this session can observe the rendered page.

No Operator Key or test-user session token was available in this context either (Key Vault secret retrieval was blocked by this environment's own permission controls when attempted). Without one of these, this session cannot register an agent, sign an intent, or call any of the permission-gated endpoints (`/v1/agents`, `/v1/principals`, `/v1/evidence`) as an authenticated caller.

What follows is therefore verified by **unauthenticated live API checks** (what's reachable without credentials) plus **direct source tracing** (what the code does, cross-referenced against the passing backend test suite) for everything a credential or browser would otherwise let you observe directly. Every item below states which of these two it rests on. **This is not a substitute for an actual manual or credentialed pass**, and the final verdict reflects that honestly rather than inferring PASS from a successful build.

## Live, unauthenticated checks performed

```
GET https://payreality.aisecurewatch.com/decisions  -> 200
GET https://api.aisecurewatch.com/health            -> 200
GET https://api.aisecurewatch.com/v1/agents         -> 401 (correctly permission-gated)
GET https://api.aisecurewatch.com/v1/principals     -> 401 (correctly permission-gated)
GET https://api.aisecurewatch.com/v1/evidence?decision_id=x -> 401 (correctly permission-gated)
GET https://api.aisecurewatch.com/v1/decisions/00000000-0000-0000-0000-000000000000 -> 404 {"detail":"decision_not_found"}
```

The last result confirms something worth recording precisely: `GET /v1/decisions/{id}` has genuinely no permission gate at all in the source (`routers/intents.py`), confirmed live, not just by reading the code. Any real decision's outcome, reason, agent_id, and amount are readable by anyone who has or guesses its UUID. This is pre-existing behavior, not something introduced by this work, but it's a real fact worth the platform owner knowing.

## Journey checklist

**Empty.** Verified by source tracing only. `agentId === ""` renders the form with no decision; both the Runtime Authority and Decision columns show their explicit empty-state copy ("Awaiting a request," "No decision yet"). Not observed rendered.

**Intent creation (agent/action/amount/currency, existing signing flow).** Verified by source tracing only; this logic is unchanged from the pre-existing page (same `getAgentPrivateKey`, `signBody`, `postSigned` call), which was previously shipped and used. Not re-exercised end-to-end in this session for lack of a registered agent's private key.

**Submission, then Evaluating.** Verified by source tracing. `submitting` is `true` from the start of `handleSubmit` until the `finally` block; the Runtime Authority column shows a single "Evaluating..." indicator during that window and nothing else. State resets (`setResult(null)`, `setDecision(null)`, `setEvidenceRecords([])`, `setEvidenceError(null)`) run at the top of every new submission, so a second decision cannot show stale data from the first, confirmed by reading the reset block directly, not observed.

**ALLOW.** Not exercised live (no signing credential available). Every field it would show is traced to a real source in `RUNTIME_DECISION_CENTER_V2_DATA_PROVENANCE.md`. The backend's own intent/decision/evidence test suite (36 tests) passes, unchanged, covering the ALLOW path server-side.

**DENY.** Same basis as ALLOW. `describeReason` correctly maps real backend reason codes to plain English; verified by reading the exact map in `format.ts` against the codes the backend actually raises (`domain/decision/engine.py`), not guessed.

**ESCALATE / Awaiting Approval.** Confirmed the backend can genuinely produce this state: `HUMAN_REVIEW` is a real `Effect` (`domain/runtime_policy/effects.py`), and `status: "PENDING"` plus the resolve endpoint (`POST /v1/decisions/{id}/resolve`, unchanged, already-shipped) are real, tested capabilities (`resolution_service.py`, exercised by the backend test suite). Not exercised live in this session.

**BLOCKED.** Confirmed the backend can genuinely produce this: `AgentSuspendedError`/`AgentRetiredError`/`AgentNotOperationalError`/`ReplayDetectedError` (`services/intent_service.py`) are real exception types the router catches and turns into 4xx responses `describeApiError` already knows how to translate. Not exercised live.

**Refresh after a decision.** Not verified. This is a purely client-side React-state concern (no persistence of `decision`/`evidenceRecords` across a reload was added, matching the pre-existing page's behavior exactly, it never persisted either). A refresh returns to the Empty state; this follows directly from reading the code, not from observing a reload.

**Browser back/forward.** Not verified; no browser available. React Router's default behavior for this route is unchanged from before this work.

**Failed API requests.** Verified by source tracing for every network call this page makes: each has a `.catch` routed through `describeApiError`, none swallow an error silently. This directly continues the fix made earlier in this engagement for the "generic error hides the real cause" bug class.

**Invalid inputs / missing agent.** Verified by source tracing. The submit button is `disabled={!agentId || !action || submitting}`; a missing agent is additionally caught explicitly in `handleSubmit` ("Select an agent that was registered in this browser").

**Expired/invalid signing state.** Verified by source tracing: an invalid/expired signature is rejected server-side by `verify_agent_signature`/`check_timestamp_window` before `submit_intent` ever runs, surfaces as a real `ApiError`, and renders in the Blocked state via `describeApiError`.

**Slow responses.** Not verified; would need either a browser with network throttling or a live slow request, neither available. The existing 60-attempt/2-second poll ceiling and `pollTimedOut` UI (unchanged from the prior page) already handle this for the HUMAN_REVIEW-polling case specifically.

**Multiple decisions sequentially.** Verified by source tracing (see the reset block under Evaluating above); not observed.

**Different users / different organizations.** Not verified; would need multiple real credential sets, not available in this session.

## What this verification cannot claim

It cannot claim the page renders correctly, looks right at real viewport sizes, or that clicking through it produces the expected visual result, because no tool in this session can observe that. It can claim, with real evidence: the deployed bundle serves the intended code (confirmed by the prior session's live-bundle grep), every endpoint the page calls behaves exactly as the source says it should (confirmed live for the unauthenticated ones, confirmed by a passing test suite for the rest), and every failure path routes through real, non-generic error handling rather than a silent or misleading one.
