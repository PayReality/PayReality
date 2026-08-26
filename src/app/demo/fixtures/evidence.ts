import type { LiveEvidence, EvidencePayload } from "../../live/types";
import { demoDecisions, demoDecisionCreatedAt } from "./decisions";
import { findDemoAgent } from "./agents";
import { demoAuthorityContextByPrincipal } from "./principals";
import { AUTHORITY_CFO_DELEGATION, findDemoPolicy } from "./policies";

// Domain Generalization Milestone: mirrors the real backend's own
// precedence (intent_service.append_evidence) -- (1) an explicit
// RiskLevel authored on any matched policy's own constraints.risk_level
// wins; (2) the amount-threshold heuristic, only when no matched policy
// declared one; (3) a conservative MEDIUM default -- never LOW -- when
// neither signal exists, so a non-financial decision is never silently
// under-classified purely because it has no amount.
function riskFor(outcome: string, amount: number | null, evaluatedMandates: string[]): EvidencePayload["risk_classification"] {
  if (outcome === "DENY") return "HIGH";
  for (const policyKey of evaluatedMandates) {
    const declared = findDemoPolicy(policyKey)?.constraints.risk_level;
    if (declared) return declared as EvidencePayload["risk_classification"];
  }
  if (amount != null) {
    if (amount > 50000) return "MEDIUM";
    return "LOW";
  }
  return "MEDIUM";
}

export const demoEvidence: LiveEvidence[] = demoDecisions.map((d, i) => {
  const agent = findDemoAgent(d.agent_id);
  const principalId = agent?.acting_for_principal_id;
  const authorityContext = principalId ? demoAuthorityContextByPrincipal[principalId] : undefined;
  const createdAt = demoDecisionCreatedAt[d.id];

  const payload: EvidencePayload = {
    payload_version: 2,
    decision_id: d.id,
    agent_id: d.agent_id,
    action: d.action,
    // Domain Generalization Milestone: resource/amount/currency are
    // all optional -- included only when the decision actually had
    // them, matching the real backend's own Evidence builder. A
    // non-financial decision (disable_user) carries no fabricated
    // amount at all.
    ...(d.resource != null ? { resource: d.resource } : {}),
    ...(d.amount != null ? { amount: d.amount.toFixed(2) } : {}),
    ...(d.currency != null ? { currency: d.currency } : {}),
    matched_mandate_ids: d.evaluated_mandates,
    authority_outcome: d.outcome,
    approval_outcome: d.resolution?.resolution ?? null,
    risk_classification: riskFor(d.outcome, d.amount, d.evaluated_mandates),
    approver: d.resolution?.resolved_by ?? null,
    recorded_at: createdAt,
    previous_hash: i === 0 ? null : `sha256:${(i - 1).toString(16).padStart(4, "0")}f2c9e1b7a3d5${i.toString(16).padStart(2, "0")}`,
    principal_id: principalId,
    authority_context: authorityContext,
    delegation_chain: authorityContext?.delegations,
    evaluated_mandate_ids: d.evaluated_mandate_ids,
    authority_ids: d.evaluated_mandate_ids.length > 0 ? [AUTHORITY_CFO_DELEGATION] : undefined,
    enterprise_system_id: d.enterprise_system_id ?? undefined,
    enterprise_system_name: d.enterprise_system_name ?? undefined,
  };

  return {
    evidence_id: `evidence-${d.id}`,
    decision_id: d.id,
    payload,
    key_id: "key-meridian-signing-2025-q1",
    signature: `ed25519:${i.toString(16).padStart(4, "0")}b8a1c9d3e7f2054ae9c1b7d3f8a2e60${i}`,
    status: "VERIFIED",
    created_at: createdAt,
  };
});

export function findDemoEvidenceByDecision(decisionId: string): LiveEvidence | undefined {
  return demoEvidence.find((e) => e.decision_id === decisionId);
}

export function findDemoEvidence(evidenceId: string): LiveEvidence | undefined {
  return demoEvidence.find((e) => e.evidence_id === evidenceId);
}
