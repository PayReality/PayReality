import type { Corpus, Principal, PrincipalCandidate, Resource, Operation, Relationship, Conflict, Gap, Question, GraphSummary } from "../../ai-authority-builder/types";
import { agoMs, DAY } from "../liveClock";
import { PRINCIPAL_OKONKWO, PRINCIPAL_RUIZ, PRINCIPAL_WEBB, PRINCIPAL_CHANDRASEKARAN } from "./principals";

export const DEMO_CORPUS_ID = "corpus-meridian-governance-docs";

export const demoCorpus: Corpus = {
  corpus_id: DEMO_CORPUS_ID,
  name: "Meridian Delegation of Authority Policy (FY25)",
  status: "extracted",
  error: null,
  document_count: 3,
  created_at: agoMs(21 * DAY),
};

export const demoGraphSummary: GraphSummary = {
  policy_count: 2,
  principal_count: 4,
  resource_count: 3,
  operation_count: 4,
  relationship_count: 2,
  conflict_count: 1,
  gap_count: 1,
  question_count: 1,
};

export const demoAuthorityPrincipals: Principal[] = [
  { id: "authprin-cfo", name: "Priya Chandrasekaran", role: "Chief Financial Officer", reports_to: null, confidence: 0.97, source_excerpt: "The Chief Financial Officer holds ultimate delegated authority over all Treasury and Accounts Payable disbursements.", source_location: "Delegation of Authority Policy, p. 2", resolved_principal_id: PRINCIPAL_CHANDRASEKARAN },
  { id: "authprin-treasury", name: "David Okonkwo", role: "Head of Treasury", reports_to: "Priya Chandrasekaran", confidence: 0.95, source_excerpt: "The Head of Treasury may approve supplier payments up to $50,000 without further sign-off.", source_location: "Delegation of Authority Policy, p. 3", resolved_principal_id: PRINCIPAL_OKONKWO },
  { id: "authprin-procurement", name: "Elena Ruiz", role: "VP, Procurement", reports_to: null, confidence: 0.93, source_excerpt: "The VP of Procurement is authorized to approve purchase orders up to $250,000.", source_location: "Delegation of Authority Policy, p. 4", resolved_principal_id: PRINCIPAL_RUIZ },
  { id: "authprin-ciso", name: "Marcus Webb", role: "Chief Information Security Officer", reports_to: null, confidence: 0.91, source_excerpt: "The CISO governs all system access provisioning outside of administrative escalation.", source_location: "Delegation of Authority Policy, p. 6", resolved_principal_id: PRINCIPAL_WEBB },
];

export const demoPrincipalCandidates: PrincipalCandidate[] = [
  { id: PRINCIPAL_OKONKWO, name: "David Okonkwo", organization_id: null },
  { id: PRINCIPAL_RUIZ, name: "Elena Ruiz", organization_id: null },
];

export const demoResources: Resource[] = [
  { id: "authres-ap-ledger", name: "Accounts Payable Ledger", description: "The SAP S/4HANA ledger recording all supplier invoice payments.", confidence: 0.9, source_excerpt: "All disbursements are recorded in the Accounts Payable Ledger within SAP S/4HANA.", source_location: "Delegation of Authority Policy, p. 3" },
  { id: "authres-procurement-system", name: "Procurement System", description: "Coupa, the system of record for purchase orders.", confidence: 0.88, source_excerpt: "Purchase orders are issued and tracked in the Procurement System.", source_location: "Delegation of Authority Policy, p. 4" },
  { id: "authres-iam", name: "Identity & Access Management", description: "ServiceNow-backed access provisioning.", confidence: 0.85, source_excerpt: "System access requests are provisioned through Identity & Access Management.", source_location: "Delegation of Authority Policy, p. 6" },
];

export const demoOperations: Operation[] = [
  { id: "authop-pay-invoice", name: "vendor_payment", description: "Disburse funds against a supplier invoice.", confidence: 0.94, source_excerpt: "Paying a supplier invoice requires delegated Treasury authority.", source_location: "Delegation of Authority Policy, p. 3" },
  { id: "authop-approve-po", name: "approve_purchase_order", description: "Approve a purchase order against budget.", confidence: 0.9, source_excerpt: "Purchase order approval sits with Procurement leadership.", source_location: "Delegation of Authority Policy, p. 4" },
  { id: "authop-onboard-vendor", name: "onboard_vendor", description: "Admit a new supplier after due diligence.", confidence: 0.87, source_excerpt: "New suppliers require a passed sanctions and risk screening before onboarding.", source_location: "Delegation of Authority Policy, p. 5" },
  { id: "authop-grant-access", name: "grant_system_access", description: "Provision a system access request.", confidence: 0.86, source_excerpt: "Access grants below administrative level may be automated.", source_location: "Delegation of Authority Policy, p. 6" },
];

export const demoRelationships: Relationship[] = [
  {
    id: "authrel-cfo-treasury",
    kind: "delegation",
    from_principal: "Priya Chandrasekaran",
    to_principal: "David Okonkwo",
    description: "CFO delegates Treasury disbursement authority up to $50,000 per invoice.",
    confidence: 0.95,
    source_excerpt: "The Chief Financial Officer delegates disbursement authority to the Head of Treasury up to $50,000 per transaction.",
    source_location: "Delegation of Authority Policy, p. 3",
    from_principal_id: PRINCIPAL_CHANDRASEKARAN,
    to_principal_id: PRINCIPAL_OKONKWO,
    status: "active",
  },
  {
    id: "authrel-treasury-escalation",
    kind: "escalation",
    from_principal: "David Okonkwo",
    to_principal: "Priya Chandrasekaran",
    description: "Invoices above $50,000 escalate back to the CFO for review.",
    confidence: 0.92,
    source_excerpt: "Amounts exceeding the delegated threshold require CFO sign-off before disbursement.",
    source_location: "Delegation of Authority Policy, p. 3",
    from_principal_id: PRINCIPAL_OKONKWO,
    to_principal_id: PRINCIPAL_CHANDRASEKARAN,
    status: "active",
  },
];

export const demoConflicts: Conflict[] = [
  {
    id: "authconflict-0",
    description: "The Procurement charter and the Delegation of Authority Policy disagree on the purchase-order approval ceiling ($200,000 vs. $250,000).",
    reasoning: "Section 4.2 of the Procurement charter caps PO approval at $200,000, while the Delegation of Authority Policy (p. 4) states $250,000. The higher, more recent document should govern pending reviewer confirmation.",
    confidence: 0.81,
  },
];

export const demoGaps: Gap[] = [
  {
    id: "authgap-0",
    description: "No document specifies a delegated approval limit for the Chief Information Security Officer's own access-provisioning actions above standard user level.",
    confidence: 0.76,
    source_excerpt: null,
    source_location: null,
  },
];

export const demoQuestions: Question[] = [
  {
    id: "authq-0",
    question: "Should the Head of Treasury's $50,000 disbursement limit apply per invoice, or per supplier per day?",
    context: "The Delegation of Authority Policy is ambiguous on aggregation -- confirmed with Treasury as per-invoice.",
    answered: true,
    answer: "Per invoice, confirmed by David Okonkwo (Head of Treasury).",
  },
];
