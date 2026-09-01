import type { RuntimePolicy } from "../../policy-studio/types";
import { agoMs, DAY } from "../liveClock";
import { PRINCIPAL_OKONKWO, PRINCIPAL_RUIZ, PRINCIPAL_WEBB } from "./principals";
import { AGENT_AP_INVOICE, AGENT_PO_APPROVAL, AGENT_VENDOR_ONBOARDING, AGENT_ACCESS_PROVISIONING, AGENT_CONTRACT_REVIEW, AGENT_LEGACY_RECON } from "./agents";
import { ES_SAP, ES_COUPA, ES_SERVICENOW } from "./enterpriseSystems";

export const DEMO_ACTIONS = [
  "vendor_payment",
  "approve_purchase_order",
  "onboard_vendor",
  "grant_system_access",
  "reconcile_treasury",
  "audit_expense",
  "renew_contract",
  // Domain Generalization Milestone: the platform's proof, in the demo
  // itself, that it isn't a payments product -- no amount/currency
  // anywhere in this policy or the decision it produces.
  "disable_user",
  // Trusted Integration Architecture, Phase 6.1 (Part C): its own
  // precise action, distinct from vendor_payment -- changing a
  // supplier's bank details and actually paying a vendor are different
  // authorities. Was represented as "vendor_payment" before this phase.
  "supplier_bank_details_change",
] as const;

export const POLICY_VENDOR_PAYMENT_UNDER_50K = "vendor-payment-under-50k";
export const POLICY_INVOICE_REVIEW_OVER_50K = "invoice-review-over-50k";
export const POLICY_PURCHASE_ORDER_APPROVAL = "purchase-order-approval";
export const POLICY_VENDOR_ONBOARDING = "vendor-onboarding-due-diligence";
export const POLICY_SYSTEM_ACCESS = "system-access-provisioning";
export const POLICY_CONTRACT_RENEWAL = "contract-auto-renewal-restriction";
export const POLICY_LEGACY_VENDOR_PAYMENT = "legacy-vendor-payment-rule";
export const POLICY_DISABLE_PRIVILEGED_ACCOUNT = "disable-privileged-production-account";
export const POLICY_SUPPLIER_BANK_DETAILS_REVIEW = "supplier-bank-details-change-review";

export const AUTHORITY_CFO_DELEGATION = "authority-cfo-treasury-delegation";
export const MANDATE_AP_INVOICE_50K = "mandate-ap-invoice-under-50k";

export const demoPolicies: RuntimePolicy[] = [
  {
    policy_key: POLICY_VENDOR_PAYMENT_UNDER_50K,
    version: 3,
    status: "active",
    name: "Invoice payments under $50K — AP delegated authority",
    description: "Allows AP-Invoice-Agent to pay supplier invoices within David Okonkwo's delegated Treasury spending limit.",
    scope: { principal: PRINCIPAL_OKONKWO, action: "vendor_payment", agent: AGENT_AP_INVOICE, resource: null },
    conditions: [{ field: "amount", operator: "<=", value: 50000 }],
    effect: "allow",
    constraints: {
      delegated_by: "Priya Chandrasekaran, CFO",
      expires: null,
      evidence_required: true,
      risk_level: "LOW",
      authority_id: AUTHORITY_CFO_DELEGATION,
      mandate_id: MANDATE_AP_INVOICE_50K,
      enterprise_system_id: ES_SAP,
    },
    metadata: { owner: "David Okonkwo", created_by: "David Okonkwo", tags: ["finance", "accounts-payable"] },
    audit: { last_reviewed_by: "Priya Chandrasekaran", last_reviewed_at: agoMs(14 * DAY) },
    bundle_id: "bundle-pay-invoice-under-50k-v3",
    bundle_hash: "sha256:8f2a1c9e7b3d4560af12e9c8d7b6a5341",
    created_at: agoMs(60 * DAY),
  },
  {
    policy_key: POLICY_INVOICE_REVIEW_OVER_50K,
    version: 2,
    status: "active",
    name: "High-value invoice review (>$50K)",
    description: "Routes supplier invoices above the delegated limit to human review instead of auto-approving.",
    scope: { principal: PRINCIPAL_OKONKWO, action: "vendor_payment", agent: AGENT_AP_INVOICE, resource: null },
    conditions: [{ field: "amount", operator: ">", value: 50000 }],
    effect: "require_human_review",
    constraints: {
      delegated_by: "Priya Chandrasekaran, CFO",
      expires: null,
      evidence_required: true,
      risk_level: "MEDIUM",
      authority_id: AUTHORITY_CFO_DELEGATION,
      mandate_id: null,
      enterprise_system_id: ES_SAP,
    },
    metadata: { owner: "David Okonkwo", created_by: "Priya Chandrasekaran", tags: ["finance", "accounts-payable", "review"] },
    audit: { last_reviewed_by: "Priya Chandrasekaran", last_reviewed_at: agoMs(14 * DAY) },
    bundle_id: "bundle-invoice-review-over-50k-v2",
    bundle_hash: "sha256:1b7e9d2f4a6c8035be29f1a0d3c7b6294",
    created_at: agoMs(60 * DAY),
  },
  {
    // Trusted Integration Architecture, Phase 6.1 (Part C): the
    // reference scenario's own precise authority -- unconditional
    // (no amount condition at all, unlike the vendor-payment policies
    // above, since this action carries no amount/currency), matching
    // the decision's own reason text ("routed to human review every
    // time, regardless of amount"): a deliberate control, not a
    // fallback for an unmatched action.
    policy_key: POLICY_SUPPLIER_BANK_DETAILS_REVIEW,
    version: 1,
    status: "active",
    name: "Supplier bank details change — always reviewed",
    description: "Routes any supplier bank-details change to human review, regardless of amount — a deliberate control against vendor-fraud (payment redirection), not an auto-approved administrative edit.",
    scope: { principal: PRINCIPAL_OKONKWO, action: "supplier_bank_details_change", agent: AGENT_AP_INVOICE, resource: null },
    conditions: [],
    effect: "require_human_review",
    constraints: {
      delegated_by: "Priya Chandrasekaran, CFO",
      expires: null,
      evidence_required: true,
      risk_level: "HIGH",
      authority_id: AUTHORITY_CFO_DELEGATION,
      mandate_id: null,
      enterprise_system_id: ES_SAP,
    },
    metadata: { owner: "David Okonkwo", created_by: "Priya Chandrasekaran", tags: ["finance", "accounts-payable", "review", "fraud-control"] },
    audit: { last_reviewed_by: "Priya Chandrasekaran", last_reviewed_at: agoMs(14 * DAY) },
    bundle_id: "bundle-supplier-bank-details-change-review-v1",
    bundle_hash: "sha256:2c8f0e3a5b7d9146cf30a2b1e4d8c7305",
    created_at: agoMs(60 * DAY),
  },
  {
    policy_key: POLICY_PURCHASE_ORDER_APPROVAL,
    version: 2,
    status: "active",
    name: "Purchase order approval",
    description: "Allows PO-Approval-Agent to approve purchase orders against sourcing contracts and budget.",
    scope: { principal: PRINCIPAL_RUIZ, action: "approve_purchase_order", agent: AGENT_PO_APPROVAL, resource: null },
    conditions: [{ field: "amount", operator: "<=", value: 250000 }],
    effect: "allow",
    constraints: {
      delegated_by: "Elena Ruiz, VP Procurement",
      expires: null,
      evidence_required: true,
      risk_level: "LOW",
      authority_id: null,
      mandate_id: null,
      enterprise_system_id: ES_COUPA,
    },
    metadata: { owner: "Elena Ruiz", created_by: "Elena Ruiz", tags: ["procurement"] },
    audit: null,
    bundle_id: "bundle-purchase-order-approval-v2",
    bundle_hash: "sha256:4c8a3e1d9f7b2065ce38a2f1e5d9c7401",
    created_at: agoMs(45 * DAY),
  },
  {
    policy_key: POLICY_VENDOR_ONBOARDING,
    version: 1,
    status: "active",
    name: "Vendor onboarding due diligence",
    description: "Requires a passed sanctions/risk check before a new supplier can be onboarded for payment.",
    scope: { principal: PRINCIPAL_RUIZ, action: "onboard_vendor", agent: AGENT_VENDOR_ONBOARDING, resource: null },
    conditions: [{ field: "sanctions_check", operator: "==", value: "passed" }],
    effect: "allow",
    constraints: {
      delegated_by: "Elena Ruiz, VP Procurement",
      expires: null,
      evidence_required: true,
      risk_level: "MEDIUM",
      authority_id: null,
      mandate_id: null,
      enterprise_system_id: ES_COUPA,
    },
    metadata: { owner: "Elena Ruiz", created_by: "Elena Ruiz", tags: ["procurement", "vendor-management"] },
    audit: null,
    bundle_id: "bundle-vendor-onboarding-v1",
    bundle_hash: "sha256:6d1f2b9c8e4a70351bf9d2c8a1e7b3652",
    created_at: agoMs(38 * DAY),
  },
  {
    policy_key: POLICY_SYSTEM_ACCESS,
    version: 4,
    status: "active",
    name: "System access provisioning — least privilege",
    description: "Allows Access-Provisioning-Agent to grant access requests that don't escalate to admin-level.",
    scope: { principal: PRINCIPAL_WEBB, action: "grant_system_access", agent: AGENT_ACCESS_PROVISIONING, resource: null },
    conditions: [{ field: "access_level", operator: "!=", value: "admin" }],
    effect: "allow",
    constraints: {
      delegated_by: "Marcus Webb, CISO",
      expires: null,
      evidence_required: true,
      risk_level: "MEDIUM",
      authority_id: null,
      mandate_id: null,
      enterprise_system_id: ES_SERVICENOW,
    },
    metadata: { owner: "Marcus Webb", created_by: "Marcus Webb", tags: ["it", "security"] },
    audit: { last_reviewed_by: "Marcus Webb", last_reviewed_at: agoMs(7 * DAY) },
    bundle_id: "bundle-system-access-v4",
    bundle_hash: "sha256:9a3c7e1b5d2f80469ce1a7d3b8f2e6015",
    created_at: agoMs(90 * DAY),
  },
  {
    policy_key: POLICY_CONTRACT_RENEWAL,
    version: 1,
    status: "pending_review",
    name: "Contract auto-renewal restriction",
    description: "Caps how large an auto-renewal Contract-Review-Agent can approve without a human sign-off.",
    scope: { principal: PRINCIPAL_RUIZ, action: "renew_contract", agent: AGENT_CONTRACT_REVIEW, resource: null },
    conditions: [{ field: "auto_renew_cap", operator: "<=", value: 100000 }],
    effect: "require_human_review",
    constraints: {
      delegated_by: "Elena Ruiz, VP Procurement",
      expires: null,
      evidence_required: true,
      risk_level: "MEDIUM",
      authority_id: null,
      mandate_id: null,
      enterprise_system_id: null,
    },
    metadata: { owner: "Elena Ruiz", created_by: "Elena Ruiz", tags: ["procurement", "legal"] },
    audit: null,
    bundle_id: null,
    bundle_hash: null,
    created_at: agoMs(3 * DAY),
  },
  {
    policy_key: POLICY_LEGACY_VENDOR_PAYMENT,
    version: 5,
    status: "retired",
    name: "Legacy vendor payment rule",
    description: "Superseded by \"Invoice payments under $50K\" — kept for historical audit only.",
    scope: { principal: PRINCIPAL_OKONKWO, action: "vendor_payment", agent: AGENT_LEGACY_RECON, resource: null },
    conditions: [],
    effect: "allow",
    constraints: {
      delegated_by: "Priya Chandrasekaran, CFO",
      expires: null,
      evidence_required: false,
      risk_level: null,
      authority_id: null,
      mandate_id: null,
      enterprise_system_id: ES_SAP,
    },
    metadata: { owner: "David Okonkwo", created_by: "David Okonkwo", tags: ["finance", "legacy"] },
    audit: null,
    bundle_id: "bundle-legacy-vendor-payment-v5",
    bundle_hash: "sha256:2e5b8a1c9d3f70264ae8c1f9b5d2a7043",
    created_at: agoMs(400 * DAY),
  },
  {
    // Domain Generalization Milestone: the platform's non-financial
    // reference scenario. Resource-scoped (unlike every financial
    // policy above, whose Scope.resource is still null), and its risk
    // is explicit (Constraints.risk_level), not inferred from an
    // amount that doesn't exist for this action.
    policy_key: POLICY_DISABLE_PRIVILEGED_ACCOUNT,
    version: 1,
    status: "active",
    name: "Disable privileged account — production requires review",
    description: "Allows Access-Provisioning-Agent to disable a privileged account, but routes production environments to human review rather than auto-approving.",
    scope: { principal: PRINCIPAL_WEBB, action: "disable_user", agent: AGENT_ACCESS_PROVISIONING, resource: "account:USR-829" },
    conditions: [
      { field: "context.privileged_account", operator: "==", value: true },
      { field: "context.environment", operator: "==", value: "production" },
    ],
    effect: "require_human_review",
    constraints: {
      delegated_by: "Marcus Webb, CISO",
      expires: null,
      evidence_required: true,
      risk_level: "HIGH",
      authority_id: null,
      mandate_id: null,
      enterprise_system_id: ES_SERVICENOW,
    },
    metadata: { owner: "Marcus Webb", created_by: "Marcus Webb", tags: ["it", "security"] },
    audit: { last_reviewed_by: "Marcus Webb", last_reviewed_at: agoMs(2 * DAY) },
    bundle_id: "bundle-disable-privileged-account-v1",
    bundle_hash: "sha256:7f4a2e9c1b6d80357ae1c9d4b7e3a1f5f",
    created_at: agoMs(9 * DAY),
  },
];

export function findDemoPolicy(policyKey: string): RuntimePolicy | undefined {
  return demoPolicies.find((p) => p.policy_key === policyKey);
}
