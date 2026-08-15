import type { LiveDecision, DecisionOutcome } from "../../live/types";
import { agoMs, SECOND, MINUTE } from "../liveClock";
import { AGENT_AP_INVOICE, AGENT_PO_APPROVAL, AGENT_VENDOR_ONBOARDING, AGENT_ACCESS_PROVISIONING } from "./agents";
import {
  POLICY_PAY_INVOICE_UNDER_50K,
  POLICY_INVOICE_REVIEW_OVER_50K,
  POLICY_PURCHASE_ORDER_APPROVAL,
  POLICY_VENDOR_ONBOARDING,
  POLICY_SYSTEM_ACCESS,
  MANDATE_AP_INVOICE_50K,
} from "./policies";
import { ES_SAP, ES_COUPA, ES_SERVICENOW } from "./enterpriseSystems";
import { SUPPLIERS } from "./organization";

interface DemoDecisionSeed {
  id: string;
  offsetMs: number;
  outcome: DecisionOutcome;
  reason: string | null;
  agent_id: string;
  action: string;
  amount: number;
  currency: string;
  evaluated_mandates: string[];
  evaluated_mandate_ids: string[];
  enterprise_system_id: string | null;
  enterprise_system_name: string | null;
  status: "PENDING" | "RESOLVED";
  resolution: LiveDecision["resolution"];
}

// The story's protagonist decision: this exact ID is what the guided
// tour and the demo landing page's "Explore this decision" link point
// to, so it must stay stable.
export const DECISION_HERO_ALLOW = "decision-hero-ap-invoice-allow";
export const DECISION_HERO_DENY = "decision-hero-ap-invoice-deny";
export const DECISION_HERO_REVIEW = "decision-hero-ap-invoice-review";

const seeds: DemoDecisionSeed[] = [
  {
    id: DECISION_HERO_ALLOW,
    offsetMs: 14 * SECOND,
    outcome: "ALLOW",
    reason: "Within David Okonkwo's delegated $50,000 Treasury spending limit for supplier payments.",
    agent_id: AGENT_AP_INVOICE,
    action: "pay_invoice",
    amount: 18450,
    currency: "USD",
    evaluated_mandates: [POLICY_PAY_INVOICE_UNDER_50K],
    evaluated_mandate_ids: [MANDATE_AP_INVOICE_50K],
    enterprise_system_id: ES_SAP,
    enterprise_system_name: "SAP S/4HANA",
    status: "RESOLVED",
    resolution: null,
  },
  {
    id: DECISION_HERO_DENY,
    offsetMs: 6 * MINUTE,
    outcome: "DENY",
    reason: "Exceeds David Okonkwo's delegated spending limit of $50,000 -- no active policy authorizes this agent to pay above that threshold.",
    agent_id: AGENT_AP_INVOICE,
    action: "pay_invoice",
    amount: 187500,
    currency: "USD",
    evaluated_mandates: [POLICY_PAY_INVOICE_UNDER_50K, POLICY_INVOICE_REVIEW_OVER_50K],
    evaluated_mandate_ids: [MANDATE_AP_INVOICE_50K],
    enterprise_system_id: ES_SAP,
    enterprise_system_name: "SAP S/4HANA",
    status: "RESOLVED",
    resolution: null,
  },
  {
    id: DECISION_HERO_REVIEW,
    offsetMs: 22 * MINUTE,
    outcome: "HUMAN_REVIEW",
    reason: "Invoice amount exceeds the $50,000 auto-approval threshold -- routed to Treasury for manual sign-off.",
    agent_id: AGENT_AP_INVOICE,
    action: "pay_invoice",
    amount: 76200,
    currency: "USD",
    evaluated_mandates: [POLICY_INVOICE_REVIEW_OVER_50K],
    evaluated_mandate_ids: [],
    enterprise_system_id: ES_SAP,
    enterprise_system_name: "SAP S/4HANA",
    status: "RESOLVED",
    resolution: { resolution: "approved", resolved_by: "Priya Chandrasekaran", reason: "Confirmed against the Q3 capital equipment budget.", created_at: agoMs(18 * MINUTE) },
  },
];

// A further ~20 background decisions -- mostly the AP-Invoice-Agent
// paying the four suppliers under the delegated limit, plus a scattering
// of PO/vendor/access decisions from the other agents -- so Governance,
// Assurance, and Evidence all show real volume, not three rows.
function buildBackgroundSeeds(): DemoDecisionSeed[] {
  const out: DemoDecisionSeed[] = [];
  let t = 40 * MINUTE;
  for (let i = 0; i < 14; i++) {
    const supplier = SUPPLIERS[i % SUPPLIERS.length];
    out.push({
      id: `decision-ap-${i}`,
      offsetMs: t,
      outcome: "ALLOW",
      reason: `Within David Okonkwo's delegated $50,000 Treasury spending limit for supplier payments (${supplier}).`,
      agent_id: AGENT_AP_INVOICE,
      action: "pay_invoice",
      amount: 4200 + i * 1375,
      currency: "USD",
      evaluated_mandates: [POLICY_PAY_INVOICE_UNDER_50K],
      evaluated_mandate_ids: [MANDATE_AP_INVOICE_50K],
      enterprise_system_id: ES_SAP,
      enterprise_system_name: "SAP S/4HANA",
      status: "RESOLVED",
      resolution: null,
    });
    t += (25 + i * 7) * MINUTE;
  }
  for (let i = 0; i < 5; i++) {
    out.push({
      id: `decision-po-${i}`,
      offsetMs: t,
      outcome: "ALLOW",
      reason: "Within Elena Ruiz's delegated purchase-order approval authority.",
      agent_id: AGENT_PO_APPROVAL,
      action: "approve_purchase_order",
      amount: 32000 + i * 9000,
      currency: "USD",
      evaluated_mandates: [POLICY_PURCHASE_ORDER_APPROVAL],
      evaluated_mandate_ids: [],
      enterprise_system_id: ES_COUPA,
      enterprise_system_name: "Coupa",
      status: "RESOLVED",
      resolution: null,
    });
    t += 45 * MINUTE;
  }
  out.push({
    id: "decision-vendor-onboard-0",
    offsetMs: t,
    outcome: "ALLOW",
    reason: "Sanctions and risk screening passed for the new supplier.",
    agent_id: AGENT_VENDOR_ONBOARDING,
    action: "onboard_vendor",
    amount: 0,
    currency: "USD",
    evaluated_mandates: [POLICY_VENDOR_ONBOARDING],
    evaluated_mandate_ids: [],
    enterprise_system_id: ES_COUPA,
    enterprise_system_name: "Coupa",
    status: "RESOLVED",
    resolution: null,
  });
  t += 30 * MINUTE;
  out.push({
    id: "decision-access-0",
    offsetMs: t,
    outcome: "ALLOW",
    reason: "Requested access level does not escalate to admin.",
    agent_id: AGENT_ACCESS_PROVISIONING,
    action: "grant_system_access",
    amount: 0,
    currency: "USD",
    evaluated_mandates: [POLICY_SYSTEM_ACCESS],
    evaluated_mandate_ids: [],
    enterprise_system_id: ES_SERVICENOW,
    enterprise_system_name: "ServiceNow",
    status: "RESOLVED",
    resolution: null,
  });
  return out;
}

const allSeeds = [...seeds, ...buildBackgroundSeeds()];

export const demoDecisions: LiveDecision[] = allSeeds.map((s) => ({
  id: s.id,
  status: s.status,
  outcome: s.outcome,
  reason: s.reason,
  agent_id: s.agent_id,
  action: s.action,
  amount: s.amount,
  currency: s.currency,
  created_at: agoMs(s.offsetMs),
  evaluated_mandates: s.evaluated_mandates,
  evaluated_mandate_ids: s.evaluated_mandate_ids,
  enterprise_system_id: s.enterprise_system_id,
  enterprise_system_name: s.enterprise_system_name,
  // Not set in the demo fixtures (evidence.ts doesn't compute these
  // either) -- null matches the real backend's own semantics for a
  // decision with no matching Evidence-pinned policy version yet,
  // rather than inventing demo values only on this side.
  policy_version: null,
  policy_bundle_hash: null,
  authority_version: null,
  resolution: s.resolution,
}));

export const demoDecisionCreatedAt: Record<string, string> = Object.fromEntries(
  allSeeds.map((s) => [s.id, agoMs(s.offsetMs)])
);

export function findDemoDecision(id: string): LiveDecision | undefined {
  return demoDecisions.find((d) => d.id === id);
}
