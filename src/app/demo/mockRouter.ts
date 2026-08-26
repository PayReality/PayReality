import { notifyGlobal } from "../components/ui/toast";
import { agoMs, DAY } from "./liveClock";
import {
  ensureLiveFeedStarted,
  getLiveDecisions,
  getLiveEvidence,
  findLiveDecision,
  findLiveEvidenceByDecision,
} from "./liveFeed";
import { demoAgents, findDemoAgent, AGENT_AP_INVOICE } from "./fixtures/agents";
import { demoPrincipals, demoAuthorityContextByPrincipal, PRINCIPAL_OKONKWO } from "./fixtures/principals";
import {
  demoPolicies,
  findDemoPolicy,
  DEMO_ACTIONS,
  POLICY_VENDOR_PAYMENT_UNDER_50K,
  POLICY_SYSTEM_ACCESS,
  POLICY_VENDOR_ONBOARDING,
  POLICY_LEGACY_VENDOR_PAYMENT,
} from "./fixtures/policies";
import { demoEnterpriseSystems } from "./fixtures/enterpriseSystems";
import {
  demoBusinessUnits,
  demoDepartments,
  demoTeams,
  demoOrganizationSettings,
  demoIntegrationsStatus,
  demoHealthStatus,
  ORG_ID,
  ORG_NAME,
} from "./fixtures/organization";
import { demoUsers, demoCurrentUser } from "./fixtures/users";
import {
  demoCorpus,
  demoGraphSummary,
  demoAuthorityPrincipals,
  demoPrincipalCandidates,
  demoResources,
  demoOperations,
  demoRelationships,
  demoConflicts,
  demoGaps,
  demoQuestions,
  DEMO_CORPUS_ID,
} from "./fixtures/authorityBuilder";
import { demoUploads, demoCandidates, DEMO_UPLOAD_ID } from "./fixtures/policyBuilder";
import { DECISION_HERO_ALLOW } from "./fixtures/decisions";
import type { SubmitIntentResult } from "../live/types";

const BLOCKED_MESSAGE = "This action is disabled in the public demonstration.";

type Handler = (ctx: { params: Record<string, string>; query: URLSearchParams; body: any }) => unknown;

interface Route {
  method: string;
  test: RegExp;
  keys: string[];
  handler: Handler;
}

const routes: Route[] = [];

function compile(pattern: string): { test: RegExp; keys: string[] } {
  const keys: string[] = [];
  const source = pattern
    .split("/")
    .map((seg) => {
      if (seg.startsWith(":")) {
        keys.push(seg.slice(1));
        return "([^/]+)";
      }
      return seg.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    })
    .join("/");
  return { test: new RegExp(`^${source}$`), keys };
}

function on(method: string, pattern: string, handler: Handler) {
  const { test, keys } = compile(pattern);
  routes.push({ method, test, keys, handler });
}

/** For any write we intentionally never perform: toast + echo the unchanged record back so the caller's success path completes normally. */
function blocked(echo: unknown): unknown {
  notifyGlobal(BLOCKED_MESSAGE, "warning");
  return echo;
}

function notFound(what: string): never {
  throw new Error(`[demo mock] not found: ${what}`);
}

// ---------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------
on("POST", "/v1/auth/login", () => ({ token: "demo-session-token", expires_at: agoMs(-365 * DAY), user: demoCurrentUser }));
on("POST", "/v1/auth/logout", () => undefined);
on("GET", "/v1/auth/me", () => demoCurrentUser);
on("POST", "/v1/auth/setup-owner", () => demoCurrentUser);

// ---------------------------------------------------------------------
// Agents + Principals
// ---------------------------------------------------------------------
on("GET", "/v1/agents", ({ query }) => {
  const status = query.get("status");
  const q = query.get("q")?.toLowerCase();
  const limit = Number(query.get("limit") ?? "25");
  const offset = Number(query.get("offset") ?? "0");
  let rows = demoAgents;
  if (status) rows = rows.filter((a) => a.status === status);
  if (q) rows = rows.filter((a) => a.name.toLowerCase().includes(q));
  const total = rows.length;
  const page = rows.slice(offset, offset + limit);
  return { agents: page, total, limit, offset };
});
on("GET", "/v1/principals", () => demoPrincipals);
on("POST", "/v1/principals", ({ body }) => blocked({ id: "principal-new", name: body?.name ?? "New Principal", created_at: new Date().toISOString() }));
on("GET", "/v1/principals/:id/authority-context", ({ params }) => demoAuthorityContextByPrincipal[params.id] ?? demoAuthorityContextByPrincipal[PRINCIPAL_OKONKWO]);

on("POST", "/v1/agents", ({ body }) =>
  blocked({ ...findDemoAgent(AGENT_AP_INVOICE)!, id: "agent-new", name: body?.name ?? "New Agent", status: "registered" })
);
on("GET", "/v1/agents/:id", ({ params }) => buildAgentDetail(params.id));
on("PATCH", "/v1/agents/:id", ({ params }) => blocked(findDemoAgent(params.id) ?? notFound("agent")));
on("POST", "/v1/agents/:id/activate", ({ params }) => blocked(findDemoAgent(params.id) ?? notFound("agent")));
on("POST", "/v1/agents/:id/suspend", ({ params }) => blocked(findDemoAgent(params.id) ?? notFound("agent")));
on("POST", "/v1/agents/:id/retire", ({ params }) => blocked(findDemoAgent(params.id) ?? notFound("agent")));
on("POST", "/v1/agents/:id/revoke", ({ params }) => blocked(findDemoAgent(params.id) ?? notFound("agent")));
on("POST", "/v1/agents/:id/rotate", ({ params }) => blocked({ id: `cert-${params.id}`, agent_id: params.id, status: "active", public_key: "ed25519:demo", issued_at: new Date().toISOString(), activated_at: new Date().toISOString(), rotated_at: null, expires_at: null, revoked_at: null }));
on("POST", "/v1/agents/:id/transfer", ({ params }) => blocked(findDemoAgent(params.id) ?? notFound("agent")));
on("GET", "/v1/agents/:id/certificates", ({ params }) => buildCertificates(params.id));
on("GET", "/v1/agents/:id/audit", ({ params }) => buildAuditEvents(params.id));
on("POST", "/v1/agents/:id/audit/:eventId/verify", () => ({ valid: true }));
on("POST", "/v1/agents/bulk/suspend", ({ body }) => blocked({ results: (body?.agent_ids ?? []).map((id: string) => ({ agent_id: id, ok: false, error: BLOCKED_MESSAGE })), succeeded: 0, failed: (body?.agent_ids ?? []).length }));
on("POST", "/v1/agents/bulk/activate", ({ body }) => blocked({ results: (body?.agent_ids ?? []).map((id: string) => ({ agent_id: id, ok: false, error: BLOCKED_MESSAGE })), succeeded: 0, failed: (body?.agent_ids ?? []).length }));
on("POST", "/v1/agents/bulk/retire", ({ body }) => blocked({ results: (body?.agent_ids ?? []).map((id: string) => ({ agent_id: id, ok: false, error: BLOCKED_MESSAGE })), succeeded: 0, failed: (body?.agent_ids ?? []).length }));
on("POST", "/v1/agents/bulk/rotate", ({ body }) => blocked({ results: (body?.agent_ids ?? []).map((id: string) => ({ agent_id: id, ok: false, error: BLOCKED_MESSAGE })), succeeded: 0, failed: (body?.agent_ids ?? []).length }));

function buildCertificates(agentId: string) {
  const agent = findDemoAgent(agentId);
  if (!agent || !agent.certificate_id) return [];
  return [
    {
      id: agent.certificate_id,
      agent_id: agentId,
      status: agent.status === "registered" ? "issued" : agent.status === "revoked" ? "revoked" : "active",
      public_key: "ed25519:base64:demoPublicKeyMaterial==",
      issued_at: agoMs(120 * DAY),
      activated_at: agent.status === "registered" ? null : agoMs(119 * DAY),
      rotated_at: null,
      expires_at: agoMs(-245 * DAY),
      revoked_at: agent.status === "revoked" ? agoMs(5 * DAY) : null,
    },
  ];
}

function buildAuditEvents(agentId: string) {
  const agent = findDemoAgent(agentId);
  const base = [
    { type: "registered", offsetDays: 120 },
    { type: "activated", offsetDays: 119 },
  ];
  if (agent?.status === "suspended") base.push({ type: "suspended", offsetDays: 3 });
  if (agent?.status === "retired") base.push({ type: "retired", offsetDays: 10 });
  return base.map((e, i) => ({
    id: `audit-${agentId}-${i}`,
    agent_id: agentId,
    event_type: e.type,
    actor: "David Okonkwo",
    payload: {},
    key_id: "key-meridian-signing-2025-q1",
    signature: `ed25519:audit${i.toString(16).padStart(4, "0")}`,
    created_at: agoMs(e.offsetDays * DAY),
  }));
}

function buildAgentDetail(agentId: string) {
  const agent = findDemoAgent(agentId);
  if (!agent) notFound("agent");
  const principal = demoPrincipals.find((p) => p.id === agent.acting_for_principal_id);
  const linkedPolicies = demoPolicies
    .filter((p) => p.scope.agent === agentId)
    .map((p) => ({
      policy_key: p.policy_key, name: p.name, version: p.version, status: p.status,
      // Product Experience Remediation Milestone 1: what this policy
      // actually governs.
      action: p.scope.action, resource: p.scope.resource,
    }));
  const decisions = getLiveDecisions().filter((d) => d.agent_id === agentId).slice(0, 5);
  const evidence = getLiveEvidence().filter((e) => e.payload.agent_id === agentId).slice(0, 5);
  return {
    agent,
    principal_name: principal?.name ?? "Unknown principal",
    policies: linkedPolicies,
    certificates: buildCertificates(agentId),
    recent_decisions: decisions.map((d) => ({
      id: d.id, outcome: d.outcome, reason: d.reason, created_at: agoMs(0),
      // Product Experience Remediation Milestone 1: what was attempted.
      action: d.action, resource: d.resource,
    })),
    recent_evidence: evidence.map((e) => ({ id: e.evidence_id, status: e.status, created_at: e.created_at })),
    recent_audit_events: buildAuditEvents(agentId),
  };
}

// ---------------------------------------------------------------------
// Runtime Policies (Policy Studio)
// ---------------------------------------------------------------------
on("GET", "/v1/runtime-policies/vocabulary", () => ({ actions: [...DEMO_ACTIONS] }));
on("GET", "/v1/runtime-policies", ({ query }) => {
  const status = query.get("status");
  return status ? demoPolicies.filter((p) => p.status === status) : demoPolicies;
});
on("GET", "/v1/runtime-policies/:key/versions", ({ params }) => {
  const p = findDemoPolicy(params.key);
  return p ? [p] : [];
});
on("GET", "/v1/runtime-policies/:key/versions/:version", ({ params }) => findDemoPolicy(params.key) ?? notFound("policy"));
on("GET", "/v1/runtime-policies/:key/diff", () => ({
  conditions: [],
  scope_changed: false,
  effect_changed: false,
  constraints_changed: false,
  affected_agents: [],
  affected_policies: [],
  risk_impact: "unchanged",
  risk_reason: "No material differences between the selected versions in this demo policy.",
}));
on("GET", "/v1/runtime-policies/:key", ({ params }) => findDemoPolicy(params.key) ?? notFound("policy"));
on("POST", "/v1/runtime-policies", ({ body }) => blocked({ ...findDemoPolicy(POLICY_VENDOR_PAYMENT_UNDER_50K)!, policy_key: "policy-new", name: body?.name ?? "New Rule", status: "draft" }));
on("PUT", "/v1/runtime-policies/:key", ({ params }) => blocked(findDemoPolicy(params.key) ?? notFound("policy")));
on("POST", "/v1/runtime-policies/:key/submit-for-review", ({ params }) => blocked(findDemoPolicy(params.key) ?? notFound("policy")));
on("POST", "/v1/runtime-policies/:key/approve", ({ params }) => blocked(findDemoPolicy(params.key) ?? notFound("policy")));
on("POST", "/v1/runtime-policies/:key/reject", ({ params }) => blocked(findDemoPolicy(params.key) ?? notFound("policy")));
on("POST", "/v1/runtime-policies/:key/compile", ({ params }) => {
  const p = findDemoPolicy(params.key);
  return { ok: true, errors: [], bundle_id: p?.bundle_id ?? "bundle-demo", bundle_hash: p?.bundle_hash ?? "sha256:demo" };
});
on("POST", "/v1/runtime-policies/:key/dry-run", ({ params, body }) => {
  const p = findDemoPolicy(params.key);
  const amount = Number(body?.amount ?? 0);
  const overLimit = amount > 50000;
  return {
    decision: overLimit ? "HUMAN_REVIEW" : "ALLOW",
    allow: !overLimit,
    deny: false,
    requires_review: overLimit,
    evaluated_mandates: p ? [p.policy_key] : [],
    review_reason: overLimit ? "Exceeds the $50,000 delegated Treasury spending limit." : null,
    deny_reason: null,
    evidence_required: true,
  };
});
on("POST", "/v1/runtime-policies/:key/deploy", ({ params }) => blocked({
  bundle_id: findDemoPolicy(params.key)?.bundle_id ?? "bundle-demo",
  bundle_hash: findDemoPolicy(params.key)?.bundle_hash ?? "sha256:demo",
  deployed_at: new Date().toISOString(),
  authority_id: findDemoPolicy(params.key)?.constraints.authority_id ?? null,
  mandate_id: findDemoPolicy(params.key)?.constraints.mandate_id ?? null,
}));

// ---------------------------------------------------------------------
// Runtime Policy Lifecycle (Phase 5) -- dashboard, timeline, activation
// preview, search, and the write actions (all `blocked`, per this
// file's own convention -- see the docstring on `blocked` above).
// ---------------------------------------------------------------------

/** RuntimePolicy -> PolicyLifecycleSummary, the dashboard/search row
 * shape (server/app/schemas/runtime_policy_lifecycle.py's
 * PolicyLifecycleSummary). `effective_status` is "superseded" for the
 * one demo policy a newer active policy actually replaced, matching
 * the real read-side label; every other field defaults to "nothing
 * scheduled/attested" and can be overridden per call site (e.g. the
 * Authority Freshness fields below). */
function toLifecycleSummary(p: (typeof demoPolicies)[number], overrides: Record<string, unknown> = {}) {
  return {
    policy_key: p.policy_key,
    version: p.version,
    name: p.name,
    status: p.status,
    effective_status: p.policy_key === POLICY_LEGACY_VENDOR_PAYMENT ? "superseded" : p.status,
    scope: p.scope,
    created_at: p.created_at,
    activated_by: p.status === "active" ? p.metadata.owner : null,
    activated_at: p.status === "active" ? agoMs(30 * DAY) : null,
    activation_reason: null,
    effective_from: null,
    effective_until: null,
    deprecated_at: null,
    deprecation_reason: null,
    rollback_of_version: null,
    last_attested_at: null,
    next_review_at: null,
    review_cadence_days: null,
    authority_expires_at: null,
    ...overrides,
  };
}

function buildLifecycleDashboard() {
  const countsByState: Record<string, number> = {};
  for (const p of demoPolicies) countsByState[p.status] = (countsByState[p.status] ?? 0) + 1;

  // Authority Freshness (Milestone 17, Part B): two distinct demo rows,
  // kept deliberately separate the same way the real schema keeps them
  // separate -- one merely review-due, one with its authority actually
  // expired (isAuthorityExpired in RuntimePolicyDashboardPage.tsx),
  // never conflated into a single status.
  const dueForReattestation = [
    toLifecycleSummary(findDemoPolicy(POLICY_SYSTEM_ACCESS)!, {
      last_attested_at: agoMs(100 * DAY),
      next_review_at: agoMs(5 * DAY),
      review_cadence_days: 90,
      authority_expires_at: null,
    }),
    toLifecycleSummary(findDemoPolicy(POLICY_VENDOR_ONBOARDING)!, {
      last_attested_at: agoMs(200 * DAY),
      next_review_at: agoMs(20 * DAY),
      review_cadence_days: 180,
      authority_expires_at: agoMs(10 * DAY),
    }),
  ];

  return {
    counts_by_state: countsByState,
    pending_approvals: demoPolicies.filter((p) => p.status === "pending_review").map((p) => toLifecycleSummary(p)),
    upcoming_activations: [],
    upcoming_expirations: [],
    upcoming_retirements: [],
    recently_activated: demoPolicies.filter((p) => p.status === "active").map((p) => toLifecycleSummary(p)),
    deprecated_policies: [],
    rollback_history: [],
    conflict_alerts: [],
    due_for_reattestation: dueForReattestation,
  };
}

on("GET", "/v1/runtime-policy-lifecycle/dashboard", () => buildLifecycleDashboard());

on("GET", "/v1/runtime-policy-lifecycle/search", ({ query }) => {
  const principal = query.get("principal")?.toLowerCase();
  const action = query.get("action")?.toLowerCase();
  const state = query.get("state");
  const version = query.get("version");
  let rows = demoPolicies.map((p) => toLifecycleSummary(p));
  if (principal) rows = rows.filter((r) => r.scope.principal.toLowerCase().includes(principal));
  if (action) rows = rows.filter((r) => r.scope.action.toLowerCase().includes(action));
  if (state) rows = rows.filter((r) => r.status === state || r.effective_status === state);
  if (version) rows = rows.filter((r) => String(r.version) === version);
  return { results: rows };
});

on("GET", "/v1/runtime-policies/:key/lifecycle/timeline", ({ params }) => {
  const p = findDemoPolicy(params.key);
  if (!p) return { policy_key: params.key, events: [] };
  const steps: Array<{ type: string; offset: number; actor: string | null }> = [
    { type: "draft_created", offset: 60 * DAY, actor: p.metadata.created_by },
    { type: "submitted_for_review", offset: 55 * DAY, actor: p.metadata.created_by },
  ];
  if (p.status !== "pending_review" && p.status !== "draft") {
    const reviewedBy = (p.audit as { last_reviewed_by?: string } | null)?.last_reviewed_by;
    steps.push({ type: "approved", offset: 50 * DAY, actor: reviewedBy ?? p.metadata.owner });
    steps.push({ type: "activated", offset: 30 * DAY, actor: p.metadata.owner });
  }
  if (p.status === "retired") {
    steps.push({ type: "retired", offset: 5 * DAY, actor: p.metadata.owner });
  }
  return {
    policy_key: params.key,
    events: steps.map((s, i) => ({
      id: `lifecycle-${params.key}-${i}`,
      policy_key: params.key,
      version: p.version,
      event_type: s.type,
      actor: s.actor ?? null,
      reason: null,
      payload: {},
      event_hash: `sha256:evt${i.toString(16).padStart(4, "0")}${params.key.slice(0, 8)}`,
      occurred_at: agoMs(s.offset),
    })),
  };
});

on("GET", "/v1/runtime-policies/:key/lifecycle/activation-preview", ({ params }) => {
  const p = findDemoPolicy(params.key);
  return {
    policy_key: params.key,
    candidate_version: p?.version ?? 1,
    current_active_version: p?.status === "active" ? p.version : null,
    diff: null,
    safety: { ok: true, violations: [] },
  };
});

on("POST", "/v1/runtime-policies/:key/lifecycle/activate", ({ params }) => {
  const p = findDemoPolicy(params.key);
  return blocked(p ? toLifecycleSummary(p) : notFound("policy"));
});
on("POST", "/v1/runtime-policies/:key/lifecycle/schedule-activation", ({ params, body }) => {
  const p = findDemoPolicy(params.key);
  return blocked({
    id: `schedule-${params.key}`,
    policy_key: params.key,
    version: p?.version ?? 1,
    action: "activate",
    effective_at: body?.effective_at ?? new Date().toISOString(),
    reason: body?.reason ?? null,
    status: "pending",
    created_by: body?.actor ?? null,
    created_at: new Date().toISOString(),
    executed_at: null,
    execution_error: null,
  });
});
on("POST", "/v1/runtime-policies/:key/lifecycle/deprecate", ({ params, body }) => {
  const p = findDemoPolicy(params.key);
  return blocked(
    p
      ? toLifecycleSummary(p, { deprecated_at: new Date().toISOString(), deprecation_reason: body?.reason ?? null })
      : notFound("policy")
  );
});
on("POST", "/v1/runtime-policies/:key/lifecycle/retire", ({ params }) => {
  const p = findDemoPolicy(params.key);
  return blocked(p ? toLifecycleSummary(p) : notFound("policy"));
});
on("POST", "/v1/runtime-policies/:key/lifecycle/archive", ({ params }) => {
  const p = findDemoPolicy(params.key);
  return blocked(p ? toLifecycleSummary(p) : notFound("policy"));
});
on("POST", "/v1/runtime-policies/:key/lifecycle/rollback", ({ params, body }) => {
  const p = findDemoPolicy(params.key);
  return blocked(p ? toLifecycleSummary(p, { rollback_of_version: body?.target_version ?? null }) : notFound("policy"));
});
on("POST", "/v1/runtime-policies/:key/lifecycle/attest", ({ params, body }) => {
  const p = findDemoPolicy(params.key);
  return blocked(
    p
      ? toLifecycleSummary(p, {
          last_attested_at: new Date().toISOString(),
          review_cadence_days: body?.review_cadence_days ?? null,
        })
      : notFound("policy")
  );
});

// ---------------------------------------------------------------------
// Legacy simplified /v1/policies (PlatformOverview, LiveAssurance)
// ---------------------------------------------------------------------
on("GET", "/v1/policies", () =>
  demoPolicies.map((p) => ({
    policy_id: p.policy_key,
    version: p.version,
    status: p.status === "active" ? "active" : p.status === "retired" ? "retired" : p.status === "compiled" ? "compiled" : "draft",
    bundle_hash: p.bundle_hash ?? "sha256:demo",
    compiled_at: p.bundle_id ? agoMs(30 * DAY) : null,
    activated_at: p.status === "active" ? agoMs(30 * DAY) : null,
    retired_at: p.status === "retired" ? agoMs(5 * DAY) : null,
  }))
);

// ---------------------------------------------------------------------
// Evidence + Decisions + Intents (Live pages)
// ---------------------------------------------------------------------
on("GET", "/v1/evidence", ({ query }) => {
  ensureLiveFeedStarted();
  const decisionId = query.get("decision_id");
  const records = getLiveEvidence();
  return decisionId ? records.filter((e) => e.decision_id === decisionId) : records;
});
on("POST", "/v1/evidence/:id/verify", () => ({ valid: true }));
// The full signing-key history (EVIDENCE_KEY_ROTATION.md): active plus
// retired. One active key is enough for the demo -- reuses the same
// key_id every Evidence/audit record in this demo is already signed
// under, never a second, disconnected key.
on("GET", "/v1/evidence/verification-keys", () => ({
  keys: [
    {
      key_id: "key-meridian-signing-2025-q1",
      algorithm: "ed25519",
      public_key_b64: "TWVyaWRpYW5EZW1vRGVtb1B1YmxpY0tleUVkMjU1MTk=",
      created_at: agoMs(90 * DAY),
      retired_at: null,
      active: true,
    },
  ],
}));
// Independent chain verification (PHASE_5_EVIDENCE.md): an honest
// "intact" result over the demo's own evidence set -- no invalid
// signatures, no broken links, since none is ever actually introduced
// in this in-memory demo feed.
on("GET", "/v1/evidence/chain/verify", () => {
  ensureLiveFeedStarted();
  const records = getLiveEvidence();
  return { organization_id: ORG_ID, total: records.length, intact: true, invalid_signatures: [], broken_links: [] };
});
// Pending Review queue: derived the same way the real backend derives
// it (outcome === HUMAN_REVIEW with no resolution yet), not a fabricated
// always-full list -- if every scripted demo decision happens to already
// be resolved, the queue honestly shows empty rather than faking activity.
on("GET", "/v1/decisions", () => {
  ensureLiveFeedStarted();
  const pending = getLiveDecisions().filter((d) => d.outcome === "HUMAN_REVIEW" && d.resolution === null);
  return { decisions: pending, total: pending.length, limit: 100, offset: 0 };
});
// Product Experience Remediation Milestone 1, Phase 6: mirrors the real
// GET /v1/assurance/summary contract -- every field computed from this
// demo's own fixtures/live feed, the same way the real endpoint
// computes them from real rows, not a second, independently-invented
// set of demo numbers.
on("GET", "/v1/assurance/summary", () => {
  ensureLiveFeedStarted();
  const dashboard = buildLifecycleDashboard();
  const decisions = getLiveDecisions();
  const pending = decisions.filter((d) => d.outcome === "HUMAN_REVIEW" && d.resolution === null);
  const resolvedReviews = decisions.filter((d) => d.outcome === "HUMAN_REVIEW" && d.resolution !== null);
  const oldestPending = pending.length
    ? pending.reduce((oldest, d) => (d.created_at < oldest ? d.created_at : oldest), pending[0].created_at)
    : null;
  const evidenceRecords = getLiveEvidence();
  const evidenceByStatus: Record<string, number> = {};
  for (const e of evidenceRecords) evidenceByStatus[e.status] = (evidenceByStatus[e.status] ?? 0) + 1;

  return {
    total_agents: demoAgents.length,
    active_agents: demoAgents.filter((a) => a.status === "active").length,
    active_policies: dashboard.counts_by_state["active"] ?? 0,
    policies_review_due: dashboard.due_for_reattestation.length,
    policies_authority_expired: dashboard.due_for_reattestation.filter((p) => p.authority_expires_at !== null).length,
    allow_count: decisions.filter((d) => d.outcome === "ALLOW").length,
    deny_count: decisions.filter((d) => d.outcome === "DENY").length,
    human_review_count: decisions.filter((d) => d.outcome === "HUMAN_REVIEW").length,
    pending_review_count: pending.length,
    oldest_pending_review_at: oldestPending,
    resolved_review_count: resolvedReviews.length,
    evidence_total: evidenceRecords.length,
    evidence_verified: evidenceByStatus["VERIFIED"] ?? 0,
    evidence_pending: evidenceByStatus["PENDING"] ?? 0,
    evidence_rejected: evidenceByStatus["REJECTED"] ?? 0,
  };
});
// Core Product Experience Redesign, section 4: the Decision Center's
// primary data source. Registered before GET /v1/decisions/:id below so
// this router's own first-match-wins scan (resolveMockResponse) matches
// "history" as this static route, not as a decision id -- mirroring the
// exact reason the real backend registers GET /v1/decisions/history
// before GET /v1/decisions/{decision_id} (routers/intents.py). Rows are
// derived from this demo's own live feed/fixtures, not a second,
// independently-invented history list; demo decisions predate the real
// backend's provenance/freshness/capability tracking, so `source` stays
// honestly absent here rather than fabricated.
on("GET", "/v1/decisions/history", ({ query }) => {
  ensureLiveFeedStarted();
  let rows = getLiveDecisions();

  const outcome = query.get("outcome");
  if (outcome) rows = rows.filter((d) => d.outcome === outcome);
  const agentId = query.get("agent_id");
  if (agentId) rows = rows.filter((d) => d.agent_id === agentId);
  const action = query.get("action");
  if (action) rows = rows.filter((d) => d.action === action);
  const resource = query.get("resource");
  if (resource) rows = rows.filter((d) => (d.resource ?? "").includes(resource));
  const source = query.get("source");
  if (source) rows = rows.filter((d) => (d as { source?: string }).source === source);

  const total = rows.length;
  const limit = Math.min(Number(query.get("limit") ?? 50) || 50, 500);
  const offset = Math.max(Number(query.get("offset") ?? 0) || 0, 0);
  const page = rows.slice(offset, offset + limit);

  const items = page.map((d) => {
    const agent = findDemoAgent(d.agent_id);
    const principal = agent ? demoPrincipals.find((p) => p.id === agent.acting_for_principal_id) : undefined;
    const matchedPolicy = d.evaluated_mandates.length > 0 ? findDemoPolicy(d.evaluated_mandates[0]) : undefined;
    const hasEvidence = !!findLiveEvidenceByDecision(d.id);
    const humanReviewState = d.outcome === "HUMAN_REVIEW" ? (d.resolution ? "resolved" : "pending") : null;
    return {
      id: d.id,
      created_at: d.created_at,
      agent_id: d.agent_id,
      agent_name: agent?.name ?? null,
      principal_name: principal?.name ?? null,
      action: d.action,
      resource: d.resource,
      outcome: d.outcome,
      reason: d.reason,
      matched_policy_name: matchedPolicy?.name ?? null,
      source: (d as { source?: string }).source ?? null,
      has_evidence: hasEvidence,
      human_review_state: humanReviewState,
      correlation_id: d.correlation_id,
    };
  });

  return { decisions: items, total, limit, offset };
});
on("GET", "/v1/decisions/:id", ({ params }) => findLiveDecision(params.id) ?? notFound("decision"));
on("POST", "/v1/decisions/:id/resolve", ({ params }) => blocked(findLiveDecision(params.id) ?? notFound("decision")));
// Phase 2B (live per-condition explainability): reconstructs the exact
// historical policy state a decision was evaluated against, never a
// live re-evaluation. Built generically from whichever policies the
// decision itself recorded as evaluated (evaluated_mandates), so it
// works for the hero ALLOW/DENY/HUMAN_REVIEW decisions and any
// background one alike, not just one hardcoded case.
function evalConditionOperator(operator: string, actual: unknown, expected: unknown): boolean {
  switch (operator) {
    case "<=":
      return Number(actual) <= Number(expected);
    case ">=":
      return Number(actual) >= Number(expected);
    case "<":
      return Number(actual) < Number(expected);
    case ">":
      return Number(actual) > Number(expected);
    case "==":
      return actual === expected;
    case "!=":
      return actual !== expected;
    default:
      return true;
  }
}
on("GET", "/v1/decisions/:id/explanation", ({ params }) => {
  const decision = findLiveDecision(params.id);
  if (!decision) {
    return {
      decision_id: params.id,
      available: false,
      unavailable_reason: "No historical policy binding exists for this decision.",
      outcome: null,
      reason: null,
      policy_id: null,
      bundle_hash: null,
      bundle_version: null,
      compiled_at: null,
      activated_at: null,
      retired_at: null,
      evaluated_at: null,
      causal_policy_id: null,
      rules: [],
    };
  }
  const rules = decision.evaluated_mandates
    .map((policyKey) => {
      const p = findDemoPolicy(policyKey);
      if (!p) return null;
      const scopeMatched = p.scope.action === decision.action;
      const conditions = p.conditions.map((c) => {
        const actual = c.field === "amount" ? decision.amount : c.value;
        return {
          field: c.field,
          operator: c.operator,
          expected_value: c.value,
          actual_value: actual,
          passed: evalConditionOperator(c.operator, actual, c.value),
        };
      });
      const matched = scopeMatched && conditions.every((c) => c.passed);
      return {
        policy_id: p.policy_key,
        policy_name: p.name,
        principal: p.scope.principal,
        action: p.scope.action,
        effect: p.effect,
        scope_matched: scopeMatched,
        conditions,
        matched,
        summary: matched
          ? `Matched: ${p.name}.`
          : scopeMatched
            ? "Scope matched, but a condition on this policy did not."
            : "Scoped to a different principal or action -- not evaluated against this request.",
      };
    })
    .filter((r): r is NonNullable<typeof r> => r !== null);
  const causal = rules.find((r) => r.matched) ?? null;
  const causalPolicy = causal ? findDemoPolicy(causal.policy_id) : undefined;
  return {
    decision_id: params.id,
    available: true,
    unavailable_reason: null,
    outcome: decision.outcome,
    reason: decision.reason,
    policy_id: causal?.policy_id ?? null,
    bundle_hash: causalPolicy?.bundle_hash ?? null,
    bundle_version: causalPolicy?.version ?? null,
    compiled_at: agoMs(60 * DAY),
    activated_at: agoMs(30 * DAY),
    retired_at: null,
    evaluated_at: decision.created_at,
    causal_policy_id: causal?.policy_id ?? null,
    rules,
  };
});
// Issue #4 (Authorization Receipts): the demo's own read-only projection
// over the same fixture data GET /v1/decisions/:id and /explanation
// already expose -- not a second data source, just a different named
// view of it, matching the real backend's own "assembly, not new
// storage" scope for this endpoint.
on("GET", "/v1/decisions/:id/receipt", ({ params }) => {
  const decision = findLiveDecision(params.id) ?? notFound("decision");
  const evidenceRecord = findLiveEvidenceByDecision(params.id);
  if (!evidenceRecord) notFound("receipt");
  const agent = findAnyDemoAgent(decision.agent_id);
  const causalPolicy = decision.evaluated_mandates.map(findDemoPolicy).find((p): p is NonNullable<typeof p> => !!p);
  const policies = decision.evaluated_mandates
    .map(findDemoPolicy)
    .filter((p): p is NonNullable<typeof p> => !!p)
    .map((p) => ({ id: p.policy_key, name: p.name, version: p.version, effect: p.effect, scope: p.scope }));
  return {
    receipt_id: evidenceRecord.evidence_id,
    evidence_id: evidenceRecord.evidence_id,
    generated_at: new Date().toISOString(),
    decision: {
      decision_id: decision.id,
      outcome: decision.outcome,
      created_at: decision.created_at,
      source: decision.source,
    },
    actor: {
      agent_id: decision.agent_id,
      agent_name: agent?.name ?? null,
      principal_id: evidenceRecord.payload.principal_id ?? null,
      principal_name: decision.principal_name,
    },
    request: {
      action: decision.action,
      resource: decision.resource,
      amount: decision.amount,
      currency: decision.currency,
      context: {},
      correlation_id: decision.correlation_id,
    },
    authority: {
      policy_id: causalPolicy?.policy_key ?? null,
      bundle_hash: decision.policy_bundle_hash ?? causalPolicy?.bundle_hash ?? null,
      bundle_version: decision.policy_version ?? causalPolicy?.version ?? null,
      compiled_at: agoMs(60 * DAY),
      activated_at: agoMs(30 * DAY),
      retired_at: null,
      authority_version: decision.authority_version,
      policies,
    },
    facts: decision.facts_evaluated ?? [],
    human_review: decision.resolution
      ? {
          resolution: decision.resolution.resolution,
          resolved_by: decision.resolution.resolved_by,
          reason: decision.resolution.reason,
          resolved_at: decision.resolution.created_at,
        }
      : null,
    capability: decision.capability,
    evidence: {
      evidence_id: evidenceRecord.evidence_id,
      key_id: evidenceRecord.key_id,
      signature: evidenceRecord.signature,
      previous_hash: evidenceRecord.payload.previous_hash,
      payload_hash: `sha256:demo${evidenceRecord.evidence_id.replace(/[^a-z0-9]/gi, "")}`,
      status: evidenceRecord.status,
      created_at: evidenceRecord.created_at,
    },
    verification: {
      signature_valid: true,
      key_id: evidenceRecord.key_id,
      algorithm: "ed25519",
      verified_at: new Date().toISOString(),
    },
  };
});
on("POST", "/v1/intents", () => {
  ensureLiveFeedStarted();
  const decision = findLiveDecision(DECISION_HERO_ALLOW)!;
  const evidenceRecord = findLiveEvidenceByDecision(DECISION_HERO_ALLOW)!;
  const result: SubmitIntentResult = {
    intent_id: `intent-${Date.now()}`,
    decision: {
      outcome: decision.outcome,
      decision_id: decision.id,
      evaluated_mandates: decision.evaluated_mandates,
      evaluated_mandate_ids: decision.evaluated_mandate_ids,
      enterprise_system_id: decision.enterprise_system_id,
      enterprise_system_name: decision.enterprise_system_name,
      reason: decision.reason,
    },
    evidence_id: evidenceRecord.evidence_id,
    status: "RESOLVED",
  };
  return result;
});

// ---------------------------------------------------------------------
// Organization
// ---------------------------------------------------------------------
on("GET", "/v1/organization/settings", () => demoOrganizationSettings);
on("PATCH", "/v1/organization/settings", () => blocked(demoOrganizationSettings));
on("GET", "/v1/organization/integrations", () => demoIntegrationsStatus);
on("GET", "/v1/organization/health", () => demoHealthStatus);
on("GET", "/v1/organization/exports/evidence", () => getLiveEvidence());
on("GET", "/v1/organization/api-keys", () => DEMO_API_KEYS);
on("POST", "/v1/organization/api-keys", () => blocked({ api_key: DEMO_API_KEYS[0], raw_key: "pr_demo_disabled" }));
on("DELETE", "/v1/organization/api-keys/:id", () => blocked(undefined));

// Milestone 3 (Enterprise Surface Isolation): inviting a member into my
// own organization. Honestly empty -- this demo's own "Pending Review
// queue" convention (see the Evidence + Decisions section above):
// nothing has actually been invited in this session, so the list says
// so rather than fabricating activity.
on("GET", "/v1/organization/invitations", () => []);
on("POST", "/v1/organization/invitations", ({ body }) =>
  blocked({
    invitation: {
      id: "invitation-new",
      organization_id: ORG_ID,
      email: body?.email ?? "new.invitee@meridianindustrial.com",
      role: body?.role ?? "auditor",
      status: "pending",
      invited_by: demoCurrentUser.name,
      created_at: new Date().toISOString(),
      expires_at: agoMs(-7 * DAY),
      accepted_at: null,
    },
    raw_token: "disabled-in-demo",
  })
);
on("DELETE", "/v1/organization/invitations/:id", ({ params }) =>
  blocked({
    id: params.id,
    organization_id: ORG_ID,
    email: "revoked@meridianindustrial.com",
    role: "auditor",
    status: "revoked",
    invited_by: demoCurrentUser.name,
    created_at: agoMs(DAY),
    expires_at: agoMs(-6 * DAY),
    accepted_at: null,
  })
);

// Milestone 3 (Enterprise Surface Isolation): the platform-admin-only
// Organization Lifecycle (create/list/deactivate/reactivate/archive an
// ARBITRARY organization), distinct from the per-tenant `/v1/organization`
// endpoints above. Only this demo's own Meridian Industrial Group
// exists -- no second organization is fabricated.
function demoOrganizationLifecycle() {
  return {
    id: ORG_ID,
    name: ORG_NAME,
    status: "active",
    created_at: agoMs(400 * DAY),
    deactivated_at: null,
    deactivated_by: null,
    archived_at: null,
    archived_by: null,
  };
}
on("GET", "/v1/organizations", () => [demoOrganizationLifecycle()]);
on("POST", "/v1/organizations", ({ body }) =>
  blocked({
    organization: { ...demoOrganizationLifecycle(), name: body?.name ?? ORG_NAME },
    owner: demoUsers[0],
    temporary_password: "disabled-in-demo",
  })
);
on("POST", "/v1/organizations/:id/deactivate", () => blocked(demoOrganizationLifecycle()));
on("POST", "/v1/organizations/:id/reactivate", () => blocked(demoOrganizationLifecycle()));
on("POST", "/v1/organizations/:id/archive", () => blocked(demoOrganizationLifecycle()));

on("GET", "/v1/enterprise-systems", () => demoEnterpriseSystems);
on("POST", "/v1/enterprise-systems", ({ body }) => blocked({ ...demoEnterpriseSystems[0], id: "es-new", name: body?.name ?? "New System" }));

on("GET", "/v1/business-units", () => demoBusinessUnits);
on("POST", "/v1/business-units", ({ body }) => blocked({ ...demoBusinessUnits[0], id: "bu-new", name: body?.name ?? "New Business Unit" }));
on("PATCH", "/v1/business-units/:id", ({ params }) => blocked(demoBusinessUnits.find((b) => b.id === params.id) ?? demoBusinessUnits[0]));
on("DELETE", "/v1/business-units/:id", () => blocked(undefined));

on("GET", "/v1/departments", ({ query }) => {
  const buId = query.get("business_unit_id");
  return buId ? demoDepartments.filter((d) => d.business_unit_id === buId) : demoDepartments;
});
on("POST", "/v1/departments", ({ body }) => blocked({ ...demoDepartments[0], id: "dept-new", name: body?.name ?? "New Department" }));
on("PATCH", "/v1/departments/:id", ({ params }) => blocked(demoDepartments.find((d) => d.id === params.id) ?? demoDepartments[0]));
on("DELETE", "/v1/departments/:id", () => blocked(undefined));

on("GET", "/v1/teams", ({ query }) => {
  const deptId = query.get("department_id");
  return deptId ? demoTeams.filter((t) => t.department_id === deptId) : demoTeams;
});
on("POST", "/v1/teams", ({ body }) => blocked({ ...demoTeams[0], id: "team-new", name: body?.name ?? "New Team" }));
on("PATCH", "/v1/teams/:id", ({ params }) => blocked(demoTeams.find((t) => t.id === params.id) ?? demoTeams[0]));
on("DELETE", "/v1/teams/:id", () => blocked(undefined));

on("GET", "/v1/users", () => demoUsers);
on("POST", "/v1/users", ({ body }) => blocked({ user: { ...demoUsers[0], id: "user-new", name: body?.name ?? "New User", email: body?.email ?? "new.user@meridianindustrial.com" }, temporary_password: "disabled-in-demo" }));
on("PATCH", "/v1/users/:id/role", ({ params }) => blocked(demoUsers.find((u) => u.id === params.id) ?? demoUsers[0]));
on("PATCH", "/v1/users/:id/status", ({ params }) => blocked(demoUsers.find((u) => u.id === params.id) ?? demoUsers[0]));

const DEMO_API_KEYS = [
  { id: "apikey-ci", name: "CI Pipeline", key_prefix: "pr_live_8a2f", role: "auditor", created_at: agoMs(60 * DAY), last_used_at: agoMs(2 * DAY), revoked_at: null },
  { id: "apikey-erp", name: "SAP Integration", key_prefix: "pr_live_c91d", role: "governance_admin", created_at: agoMs(90 * DAY), last_used_at: agoMs(3600_000), revoked_at: null },
];

// ---------------------------------------------------------------------
// AI Authority Builder
// ---------------------------------------------------------------------
const AUTH_BUILDER = "/v1/ai-authority-builder";
on("GET", `${AUTH_BUILDER}/status`, () => ({ ai_enabled: true }));
on("POST", `${AUTH_BUILDER}/corpora`, () => demoCorpus);
on("GET", `${AUTH_BUILDER}/corpora`, () => [demoCorpus]);
on("GET", `${AUTH_BUILDER}/corpora/:id`, () => demoCorpus);
on("GET", `${AUTH_BUILDER}/corpora/:id/summary`, () => demoGraphSummary);
on("GET", `${AUTH_BUILDER}/corpora/:id/principals`, () => demoAuthorityPrincipals);
on("GET", `${AUTH_BUILDER}/corpora/:id/resources`, () => demoResources);
on("GET", `${AUTH_BUILDER}/corpora/:id/operations`, () => demoOperations);
on("GET", `${AUTH_BUILDER}/corpora/:id/relationships`, () => demoRelationships);
on("GET", `${AUTH_BUILDER}/corpora/:id/conflicts`, () => demoConflicts);
on("GET", `${AUTH_BUILDER}/corpora/:id/gaps`, () => demoGaps);
on("GET", `${AUTH_BUILDER}/corpora/:id/questions`, () => demoQuestions);
on("POST", `${AUTH_BUILDER}/questions/:id/answer`, ({ params }) => blocked(demoQuestions.find((q) => q.id === params.id) ?? demoQuestions[0]));
on("GET", `${AUTH_BUILDER}/principals/:id/candidates`, () => demoPrincipalCandidates);
on("POST", `${AUTH_BUILDER}/principals/:id/resolve`, () => blocked(demoAuthorityPrincipals[0]));
on("POST", `${AUTH_BUILDER}/relationships/:id/resolve`, ({ params }) => blocked(demoRelationships.find((r) => r.id === params.id) ?? demoRelationships[0]));
on("POST", `${AUTH_BUILDER}/relationships/:id/activate`, ({ params }) => blocked(demoRelationships.find((r) => r.id === params.id) ?? demoRelationships[0]));

// Phase 3: Explainability & Human Review (Corpus Review page). Coverage
// is a deterministic parsing statistic, never an LLM's self-report;
// missing-information is the deterministic backstop for the model's
// own self-reported Gaps/Questions (already covered by demoGaps/
// demoQuestions above) -- a different, complementary finding, not a
// duplicate of either. Diff and approval history are both honestly
// empty: this demo corpus has no prior in-force graph to compare
// against and has not yet been approved.
on("GET", `${AUTH_BUILDER}/corpora/:id/coverage`, () => ({
  documents_processed: 3,
  clauses_analysed: 48,
  clauses_ignored: 4,
  tables_extracted: 2,
  images_skipped: 1,
  sections_unsupported: 0,
  coverage_percent: 92.3,
}));
on("GET", `${AUTH_BUILDER}/corpora/:id/missing-information`, () => [
  {
    category: "unknown_reporting_line",
    subject: "Elena Ruiz",
    description: "No document specifies who the VP of Procurement reports to.",
  },
]);
on("GET", `${AUTH_BUILDER}/corpora/:id/diff`, () => ({
  new_authorities: [],
  removed_authorities: [],
  new_thresholds: [],
  changed_thresholds: [],
  changed_reporting_lines: [],
  changed_responsibilities: [],
}));
on("GET", `${AUTH_BUILDER}/corpora/:id/approvals`, () => []);
on("POST", `${AUTH_BUILDER}/corpora/:id/approve`, ({ params, body }) => blocked({
  id: "approval-demo",
  corpus_id: params.id,
  reviewer: demoCurrentUser.name,
  version: 1,
  approval_reason: body?.approval_reason ?? null,
  graph_hash: "sha256:demo-graph-hash",
  approved_at: new Date().toISOString(),
}));

// ---------------------------------------------------------------------
// AI Policy Builder
// ---------------------------------------------------------------------
const POLICY_BUILDER = "/v1/ai-policy-builder";
on("GET", `${POLICY_BUILDER}/status`, () => ({ ai_enabled: true }));
on("POST", `${POLICY_BUILDER}/uploads`, () => demoUploads[0]);
on("GET", `${POLICY_BUILDER}/uploads`, () => demoUploads);
on("GET", `${POLICY_BUILDER}/uploads/:id`, () => demoUploads.find((u) => u.upload_id === DEMO_UPLOAD_ID) ?? demoUploads[0]);
on("GET", `${POLICY_BUILDER}/uploads/:id/candidates`, () => demoCandidates);
on("GET", `${POLICY_BUILDER}/candidates`, () => demoCandidates);
on("PUT", `${POLICY_BUILDER}/candidates/:id`, ({ params }) => blocked(demoCandidates.find((c) => c.candidate_id === params.id) ?? demoCandidates[0]));
on("POST", `${POLICY_BUILDER}/candidates/:id/dismiss`, ({ params }) => blocked(demoCandidates.find((c) => c.candidate_id === params.id) ?? demoCandidates[0]));
on("POST", `${POLICY_BUILDER}/candidates/:id/promote`, () => blocked({ policy_key: POLICY_VENDOR_PAYMENT_UNDER_50K, version: 1, status: "draft", authority_id: null }));

// ---------------------------------------------------------------------
// Runtime Policy Simulator (Authority Intelligence Program, Phase 4).
// Read-only with respect to Runtime Authority itself, same as the real
// router: nothing here ever edits, compiles, or deploys a policy, or
// writes a real Decision/Evidence row. Reuses the exact same amount-
// threshold logic as the existing /v1/runtime-policies/:key/dry-run
// mock above, not a second, disconnected rule.
// ---------------------------------------------------------------------
const POLICY_SIMULATION = "/v1/policy-simulation";

interface DemoScenario {
  id: string;
  policy_key: string;
  name: string;
  input: Record<string, unknown>;
  expected_outcome: string;
  created_by: string | null;
  created_at: string;
}
// In-memory only, the same "seeded, then grows for this session" pattern
// liveFeed.ts already uses -- never persisted, never shared across tabs.
const demoScenarios: DemoScenario[] = [];

function buildSimulationResult(policyKey: string, input: Record<string, unknown> | undefined) {
  const p = findDemoPolicy(policyKey);
  const amount = Number(input?.amount ?? 0);
  const overLimit = amount > 50000;
  const decision = overLimit ? "HUMAN_REVIEW" : "ALLOW";
  const now = new Date().toISOString();
  const principal = (input?.principal as string | undefined) ?? p?.scope.principal ?? "";
  const action = (input?.action as string | undefined) ?? p?.scope.action ?? "";
  const resource = (input?.resource as string | undefined) ?? null;
  const rule = p
    ? {
        policy_id: p.policy_key,
        policy_name: p.name,
        principal,
        action,
        effect: p.effect,
        scope_matched: true,
        conditions: p.conditions.map((c) => ({
          field: c.field,
          operator: c.operator,
          expected_value: c.value,
          actual_value: c.field === "amount" ? amount : c.value,
          passed: c.field === "amount" ? !overLimit : true,
        })),
        matched: !overLimit,
        summary: overLimit
          ? "Not matched: exceeds the delegated Treasury spending limit."
          : "Matched: within the delegated Treasury spending limit.",
      }
    : null;
  return {
    decision,
    policy_key: policyKey,
    policy_name: p?.name ?? "Unknown policy",
    policy_version: p?.version ?? 1,
    policy_bundle_hash: p?.bundle_hash ?? "sha256:demo",
    generated_at: now,
    review_reason: overLimit ? "Exceeds the $50,000 delegated Treasury spending limit." : null,
    deny_reason: null,
    rules: rule ? [rule] : [],
    authority_trace: [
      { label: "Principal resolved", detail: principal || null },
      { label: "Policy evaluated", detail: p?.name ?? null },
      { label: "Decision reached", detail: decision },
    ],
    evidence_preview: {
      decision,
      policy_version: p?.version ?? 1,
      policy_bundle_hash: p?.bundle_hash ?? "sha256:demo",
      principal,
      action,
      resource,
      evaluated_at: now,
      receipt_hash: `sha256:preview${Math.abs(amount).toString(16)}${policyKey.length}`,
      preview: true,
    },
  };
}

on("POST", `${POLICY_SIMULATION}/:key/simulate`, ({ params, body }) => buildSimulationResult(params.key, body));
on("GET", `${POLICY_SIMULATION}/:key/scenarios`, ({ params }) => demoScenarios.filter((s) => s.policy_key === params.key));
on("POST", `${POLICY_SIMULATION}/:key/scenarios`, ({ params, body }) => {
  const scenario: DemoScenario = {
    id: `scenario-${params.key}-${demoScenarios.length}`,
    policy_key: params.key,
    name: body?.name ?? "Untitled scenario",
    input: body?.input ?? {},
    expected_outcome: body?.expected_outcome ?? "ALLOW",
    created_by: demoCurrentUser.name,
    created_at: new Date().toISOString(),
  };
  demoScenarios.push(scenario);
  return scenario;
});
on("POST", `${POLICY_SIMULATION}/scenarios/:id/run`, ({ params }) => {
  const scenario = demoScenarios.find((s) => s.id === params.id);
  if (!scenario) notFound("scenario");
  const result = buildSimulationResult(scenario.policy_key, scenario.input);
  return {
    scenario_id: scenario.id,
    scenario_name: scenario.name,
    expected_outcome: scenario.expected_outcome,
    actual_outcome: result.decision,
    passed: result.decision === scenario.expected_outcome,
    result,
  };
});
// The uploaded CSV's rows aren't inspectable here (multipart form body,
// never JSON-parsed by this router) -- a short, plausible aggregate
// consistent with the demo's own AP-Invoice story stands in, the same
// "plausible, internally-consistent demo data" every other mock in this
// file already uses instead of a literal replay of the input.
on("POST", `${POLICY_SIMULATION}/:key/batch`, ({ params }) => {
  const p = findDemoPolicy(params.key);
  return {
    total: 5,
    allowed: 4,
    denied: 0,
    escalated: 1,
    errors: 0,
    sample_rows: [
      { row_number: 1, principal: "David Okonkwo", action: "vendor_payment", decision: "ALLOW", error: null },
      { row_number: 2, principal: "David Okonkwo", action: "vendor_payment", decision: "ALLOW", error: null },
      { row_number: 3, principal: "David Okonkwo", action: "vendor_payment", decision: "HUMAN_REVIEW", error: null },
      { row_number: 4, principal: "David Okonkwo", action: "vendor_payment", decision: "ALLOW", error: null },
      { row_number: 5, principal: "David Okonkwo", action: "vendor_payment", decision: "ALLOW", error: null },
    ],
    sample_truncated: false,
    policy_version: p?.version ?? 1,
    policy_bundle_hash: p?.bundle_hash ?? "sha256:demo",
  };
});

// ---------------------------------------------------------------------
// Resolver
// ---------------------------------------------------------------------
export function resolveMockResponse<T>(method: string, fullPath: string, rawBody: unknown): Promise<T> {
  const [path, qs] = fullPath.split("?");
  const query = new URLSearchParams(qs ?? "");
  let body: any = undefined;
  if (typeof rawBody === "string") {
    try {
      body = JSON.parse(rawBody);
    } catch {
      body = undefined;
    }
  }
  for (const route of routes) {
    if (route.method !== method) continue;
    const match = route.test.exec(path);
    if (!match) continue;
    const params: Record<string, string> = {};
    route.keys.forEach((key, i) => (params[key] = decodeURIComponent(match[i + 1])));
    try {
      const result = route.handler({ params, query, body });
      return Promise.resolve(result as T);
    } catch (e) {
      return Promise.reject(e);
    }
  }
  // eslint-disable-next-line no-console
  console.warn(`[demo] no mock route for ${method} ${fullPath}`);
  return Promise.reject(new Error(`No demo mock registered for ${method} ${fullPath}`));
}
