import type { LiveDecision, LiveEvidence, EvidencePayload, LiveAgent, LivePrincipal } from "../live/types";
import { demoDecisions, demoDecisionCreatedAt } from "./fixtures/decisions";
import { demoEvidence } from "./fixtures/evidence";
import { AGENT_AP_INVOICE, AGENT_PO_APPROVAL, findDemoAgent } from "./fixtures/agents";
import { demoAuthorityContextByPrincipal } from "./fixtures/principals";
import { POLICY_VENDOR_PAYMENT_UNDER_50K, POLICY_PURCHASE_ORDER_APPROVAL, MANDATE_AP_INVOICE_50K } from "./fixtures/policies";
import { ES_SAP, ES_COUPA } from "./fixtures/enterpriseSystems";
import { SUPPLIERS } from "./fixtures/organization";

// A small, module-scope "operating platform" simulation: seeded with the
// full fixture set, then a queued run of pre-scripted next-events gets
// appended one at a time on an interval, so a visitor who lingers on
// Evidence/Assurance/Governance sees the numbers and the feed itself
// visibly advance instead of staying frozen at whatever loaded first.
// Entirely client-side and in-memory -- never touches a real backend.

let decisions: LiveDecision[] = [...demoDecisions];
let evidence: LiveEvidence[] = [...demoEvidence];
let tickCount = 0;
let started = false;

// A visitor's own session-local creations (agent registration, principal
// creation) aren't part of the shared curated demo dataset the rest of
// this file replays, so they get their own small mutable overlay --
// same architectural shape as `decisions`/`evidence` above, just seeded
// empty instead of from a fixture, and never touched by the ticker.
let registeredAgents: LiveAgent[] = [];
let registeredPrincipals: LivePrincipal[] = [];

const NEXT_EVENTS: Array<{ agentId: string; action: string; amount: number; policyId: string; mandateId: string | null; enterpriseSystemId: string; enterpriseSystemName: string }> = [
  { agentId: AGENT_AP_INVOICE, action: "vendor_payment", amount: 9800, policyId: POLICY_VENDOR_PAYMENT_UNDER_50K, mandateId: MANDATE_AP_INVOICE_50K, enterpriseSystemId: ES_SAP, enterpriseSystemName: "SAP S/4HANA" },
  { agentId: AGENT_PO_APPROVAL, action: "approve_purchase_order", amount: 41200, policyId: POLICY_PURCHASE_ORDER_APPROVAL, mandateId: null, enterpriseSystemId: ES_COUPA, enterpriseSystemName: "Coupa" },
  { agentId: AGENT_AP_INVOICE, action: "vendor_payment", amount: 27650, policyId: POLICY_VENDOR_PAYMENT_UNDER_50K, mandateId: MANDATE_AP_INVOICE_50K, enterpriseSystemId: ES_SAP, enterpriseSystemName: "SAP S/4HANA" },
  { agentId: AGENT_AP_INVOICE, action: "vendor_payment", amount: 15300, policyId: POLICY_VENDOR_PAYMENT_UNDER_50K, mandateId: MANDATE_AP_INVOICE_50K, enterpriseSystemId: ES_SAP, enterpriseSystemName: "SAP S/4HANA" },
  { agentId: AGENT_PO_APPROVAL, action: "approve_purchase_order", amount: 68000, policyId: POLICY_PURCHASE_ORDER_APPROVAL, mandateId: null, enterpriseSystemId: ES_COUPA, enterpriseSystemName: "Coupa" },
];

function appendNextEvent() {
  const spec = NEXT_EVENTS[tickCount % NEXT_EVENTS.length];
  tickCount += 1;
  const supplier = SUPPLIERS[tickCount % SUPPLIERS.length];
  const id = `decision-live-${tickCount}`;
  const now = new Date().toISOString();
  const agent = findDemoAgent(spec.agentId);
  const principalId = agent?.acting_for_principal_id;
  const authorityContext = principalId ? demoAuthorityContextByPrincipal[principalId] : undefined;

  const decision: LiveDecision = {
    id,
    status: "RESOLVED",
    outcome: "ALLOW",
    reason: spec.action === "vendor_payment"
      ? `Within David Okonkwo's delegated $50,000 Treasury spending limit for supplier payments (${supplier}).`
      : "Within Elena Ruiz's delegated purchase-order approval authority.",
    agent_id: spec.agentId,
    action: spec.action,
    amount: spec.amount,
    currency: "USD",
    created_at: now,
    evaluated_mandates: [spec.policyId],
    evaluated_mandate_ids: spec.mandateId ? [spec.mandateId] : [],
    enterprise_system_id: spec.enterpriseSystemId,
    enterprise_system_name: spec.enterpriseSystemName,
    policy_version: null,
    policy_bundle_hash: null,
    authority_version: null,
    resolution: null,
  };
  demoDecisionCreatedAt[id] = now;

  const payload: EvidencePayload = {
    payload_version: 2,
    decision_id: id,
    agent_id: spec.agentId,
    action: spec.action,
    amount: spec.amount.toFixed(2),
    matched_mandate_ids: [spec.policyId],
    authority_outcome: "ALLOW",
    approval_outcome: null,
    risk_classification: spec.amount > 50000 ? "MEDIUM" : "LOW",
    approver: null,
    recorded_at: now,
    previous_hash: `sha256:live${tickCount.toString(16).padStart(4, "0")}`,
    principal_id: principalId,
    authority_context: authorityContext,
    delegation_chain: authorityContext?.delegations,
    evaluated_mandate_ids: spec.mandateId ? [spec.mandateId] : [],
    enterprise_system_id: spec.enterpriseSystemId,
    enterprise_system_name: spec.enterpriseSystemName,
  };
  const ev: LiveEvidence = {
    evidence_id: `evidence-${id}`,
    decision_id: id,
    payload,
    key_id: "key-meridian-signing-2025-q1",
    signature: `ed25519:live${tickCount.toString(16).padStart(4, "0")}b8a1c9d3e7f2054ae9c1b7d3f8a2e6`,
    status: "VERIFIED",
    created_at: now,
  };

  decisions = [decision, ...decisions];
  evidence = [ev, ...evidence];
}

const TICK_INTERVAL_MS = 75_000;

/** Starts the background ticker once. Safe to call from multiple mount points. */
export function ensureLiveFeedStarted() {
  if (started || typeof window === "undefined") return;
  started = true;
  window.setInterval(appendNextEvent, TICK_INTERVAL_MS);
}

export function getLiveDecisions(): LiveDecision[] {
  return decisions;
}

export function getLiveEvidence(): LiveEvidence[] {
  return evidence;
}

export function getLiveDecisionCreatedAt(id: string): string | undefined {
  return demoDecisionCreatedAt[id];
}

export function findLiveDecision(id: string): LiveDecision | undefined {
  return decisions.find((d) => d.id === id);
}

// Demo V2 (Trusted Authority Story): simulates an enterprise system
// retrying the same real business operation, the exact scenario
// Trusted Integration Architecture Phase 3's operation idempotency
// exists for (see SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md
// §50.7). This can only ever return an id already present in `decisions`;
// there is no code path here that fabricates a new one, which is
// itself the honest demonstration: the mechanism cannot create a second
// decision for an operation it already has one for, not just "doesn't
// happen to" in this particular call.
export function findDecisionForExternalOperation(externalOperationId: string): LiveDecision | undefined {
  return decisions.find((d) => d.integration?.external_operation_id === externalOperationId);
}

export function findLiveEvidenceByDecision(decisionId: string): LiveEvidence | undefined {
  return evidence.find((e) => e.decision_id === decisionId);
}

export function getRegisteredAgents(): LiveAgent[] {
  return registeredAgents;
}

export function findRegisteredAgent(id: string): LiveAgent | undefined {
  return registeredAgents.find((a) => a.id === id);
}

export function addRegisteredAgent(agent: LiveAgent) {
  registeredAgents = [agent, ...registeredAgents];
}

export function updateRegisteredAgent(id: string, patch: Partial<LiveAgent>): LiveAgent | undefined {
  if (!findRegisteredAgent(id)) return undefined;
  let updated: LiveAgent | undefined;
  registeredAgents = registeredAgents.map((a) => {
    if (a.id !== id) return a;
    updated = { ...a, ...patch, updated_at: new Date().toISOString() };
    return updated;
  });
  return updated;
}

export function getRegisteredPrincipals(): LivePrincipal[] {
  return registeredPrincipals;
}

export function findRegisteredPrincipal(id: string): LivePrincipal | undefined {
  return registeredPrincipals.find((p) => p.id === id);
}

export function addRegisteredPrincipal(principal: LivePrincipal) {
  registeredPrincipals = [principal, ...registeredPrincipals];
}
