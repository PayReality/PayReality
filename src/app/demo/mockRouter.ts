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
import { demoPolicies, findDemoPolicy, DEMO_ACTIONS, POLICY_VENDOR_PAYMENT_UNDER_50K } from "./fixtures/policies";
import { demoEnterpriseSystems } from "./fixtures/enterpriseSystems";
import {
  demoBusinessUnits,
  demoDepartments,
  demoTeams,
  demoOrganizationSettings,
  demoIntegrationsStatus,
  demoHealthStatus,
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
    .map((p) => ({ policy_key: p.policy_key, name: p.name, version: p.version, status: p.status }));
  const decisions = getLiveDecisions().filter((d) => d.agent_id === agentId).slice(0, 5);
  const evidence = getLiveEvidence().filter((e) => e.payload.agent_id === agentId).slice(0, 5);
  return {
    agent,
    principal_name: principal?.name ?? "Unknown principal",
    policies: linkedPolicies,
    certificates: buildCertificates(agentId),
    recent_decisions: decisions.map((d) => ({ id: d.id, outcome: d.outcome, reason: d.reason, created_at: agoMs(0) })),
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
// Pending Review queue: derived the same way the real backend derives
// it (outcome === HUMAN_REVIEW with no resolution yet), not a fabricated
// always-full list -- if every scripted demo decision happens to already
// be resolved, the queue honestly shows empty rather than faking activity.
on("GET", "/v1/decisions", () => {
  ensureLiveFeedStarted();
  const pending = getLiveDecisions().filter((d) => d.outcome === "HUMAN_REVIEW" && d.resolution === null);
  return { decisions: pending, total: pending.length, limit: 100, offset: 0 };
});
on("GET", "/v1/decisions/:id", ({ params }) => findLiveDecision(params.id) ?? notFound("decision"));
on("POST", "/v1/decisions/:id/resolve", ({ params }) => blocked(findLiveDecision(params.id) ?? notFound("decision")));
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
