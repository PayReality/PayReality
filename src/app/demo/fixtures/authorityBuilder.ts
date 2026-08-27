import type { Corpus, Principal, PrincipalCandidate, Resource, Operation, Relationship, Conflict, Gap, Question, GraphSummary, GraphApproval } from "../../ai-authority-builder/types";
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
  { id: "authprin-cfo", name: "Priya Chandrasekaran", role: "Chief Financial Officer", reports_to: null, confidence: 0.97, source_excerpt: "The Chief Financial Officer holds ultimate delegated authority over all Treasury and Accounts Payable disbursements.", source_location: "Delegation of Authority Policy, p. 2", resolved_principal_id: PRINCIPAL_CHANDRASEKARAN, clause_reference: "Delegation of Authority Policy, Sec. 2.1", extraction_reasoning: "Explicit title-to-authority statement naming the CFO directly.", detected_assumptions: [], ambiguity_flags: [] },
  { id: "authprin-treasury", name: "David Okonkwo", role: "Head of Treasury", reports_to: "Priya Chandrasekaran", confidence: 0.95, source_excerpt: "The Head of Treasury may approve supplier payments up to $50,000 without further sign-off.", source_location: "Delegation of Authority Policy, p. 3", resolved_principal_id: PRINCIPAL_OKONKWO, clause_reference: "Delegation of Authority Policy, Sec. 3.2", extraction_reasoning: "Explicit dollar threshold tied to the role title.", detected_assumptions: ["Assumes \"Head of Treasury\" reports to the CFO; reporting line inferred from org chart, not stated in this clause."], ambiguity_flags: [] },
  { id: "authprin-procurement", name: "Elena Ruiz", role: "VP, Procurement", reports_to: null, confidence: 0.93, source_excerpt: "The VP of Procurement is authorized to approve purchase orders up to $250,000.", source_location: "Delegation of Authority Policy, p. 4", resolved_principal_id: PRINCIPAL_RUIZ, clause_reference: "Delegation of Authority Policy, Sec. 4.1", extraction_reasoning: "Explicit dollar threshold tied to the role title.", detected_assumptions: [], ambiguity_flags: ["This clause's $250,000 ceiling conflicts with the Procurement charter's $200,000 ceiling; see the flagged conflict below."] },
  { id: "authprin-ciso", name: "Marcus Webb", role: "Chief Information Security Officer", reports_to: null, confidence: 0.91, source_excerpt: "The CISO governs all system access provisioning outside of administrative escalation.", source_location: "Delegation of Authority Policy, p. 6", resolved_principal_id: PRINCIPAL_WEBB, clause_reference: "Delegation of Authority Policy, Sec. 6.1", extraction_reasoning: "Explicit scope statement naming the CISO directly.", detected_assumptions: [], ambiguity_flags: ["\"Outside of administrative escalation\" is not defined elsewhere in the document; see the related gap below."] },
];

export const demoPrincipalCandidates: PrincipalCandidate[] = [
  { id: PRINCIPAL_OKONKWO, name: "David Okonkwo", organization_id: null },
  { id: PRINCIPAL_RUIZ, name: "Elena Ruiz", organization_id: null },
];

export const demoResources: Resource[] = [
  { id: "authres-ap-ledger", name: "Accounts Payable Ledger", description: "The SAP S/4HANA ledger recording all supplier invoice payments.", confidence: 0.9, source_excerpt: "All disbursements are recorded in the Accounts Payable Ledger within SAP S/4HANA.", source_location: "Delegation of Authority Policy, p. 3", clause_reference: "Delegation of Authority Policy, Sec. 3.1", extraction_reasoning: "Named system of record for disbursements.", detected_assumptions: [], ambiguity_flags: [] },
  { id: "authres-procurement-system", name: "Procurement System", description: "Coupa, the system of record for purchase orders.", confidence: 0.88, source_excerpt: "Purchase orders are issued and tracked in the Procurement System.", source_location: "Delegation of Authority Policy, p. 4", clause_reference: "Delegation of Authority Policy, Sec. 4.1", extraction_reasoning: "Named system of record for purchase orders; vendor name (Coupa) inferred from context, not stated in this clause.", detected_assumptions: ["Assumes \"Procurement System\" refers to Coupa; the clause names the system by function, not by vendor."], ambiguity_flags: [] },
  { id: "authres-iam", name: "Identity & Access Management", description: "ServiceNow-backed access provisioning.", confidence: 0.85, source_excerpt: "System access requests are provisioned through Identity & Access Management.", source_location: "Delegation of Authority Policy, p. 6", clause_reference: "Delegation of Authority Policy, Sec. 6.1", extraction_reasoning: "Named system of record for access provisioning; vendor (ServiceNow) inferred from context, not stated in this clause.", detected_assumptions: ["Assumes the IAM system is ServiceNow-backed; the clause does not name a vendor."], ambiguity_flags: [] },
];

export const demoOperations: Operation[] = [
  { id: "authop-pay-invoice", name: "vendor_payment", description: "Disburse funds against a supplier invoice.", confidence: 0.94, source_excerpt: "Paying a supplier invoice requires delegated Treasury authority.", source_location: "Delegation of Authority Policy, p. 3", clause_reference: "Delegation of Authority Policy, Sec. 3.2", extraction_reasoning: "Explicit action tied to the Treasury delegation clause.", detected_assumptions: [], ambiguity_flags: [] },
  { id: "authop-approve-po", name: "approve_purchase_order", description: "Approve a purchase order against budget.", confidence: 0.9, source_excerpt: "Purchase order approval sits with Procurement leadership.", source_location: "Delegation of Authority Policy, p. 4", clause_reference: "Delegation of Authority Policy, Sec. 4.1", extraction_reasoning: "Explicit action tied to the Procurement delegation clause.", detected_assumptions: [], ambiguity_flags: [] },
  { id: "authop-onboard-vendor", name: "onboard_vendor", description: "Admit a new supplier after due diligence.", confidence: 0.87, source_excerpt: "New suppliers require a passed sanctions and risk screening before onboarding.", source_location: "Delegation of Authority Policy, p. 5", clause_reference: "Delegation of Authority Policy, Sec. 5.1", extraction_reasoning: "Explicit precondition (screening) tied to the onboarding action, but no named approving role.", detected_assumptions: [], ambiguity_flags: ["No principal is named as the approver of this action in the source document."] },
  { id: "authop-grant-access", name: "grant_system_access", description: "Provision a system access request.", confidence: 0.86, source_excerpt: "Access grants below administrative level may be automated.", source_location: "Delegation of Authority Policy, p. 6", clause_reference: "Delegation of Authority Policy, Sec. 6.2", extraction_reasoning: "Explicit action tied to the CISO's IAM oversight clause.", detected_assumptions: ["Assumes \"automated\" grants still require CISO-delegated authority rather than none at all."], ambiguity_flags: [] },
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
    clause_reference: "Delegation of Authority Policy, Sec. 3.2",
    extraction_reasoning: "Explicit delegation statement naming both principals and a dollar ceiling.",
    detected_assumptions: [],
    ambiguity_flags: [],
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
    clause_reference: "Delegation of Authority Policy, Sec. 3.2",
    extraction_reasoning: "Explicit escalation statement tied to the same delegation clause's ceiling.",
    detected_assumptions: [],
    ambiguity_flags: [],
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

// Authority Graph Lineage & Versioning (issue #5): a real two-version
// lineage built from this file's own principal/relationship/conflict/gap
// fixtures above -- v1 is an honest, smaller subset (only the CFO/
// Treasury delegation was captured yet); v2 is the full current graph.
// Snapshot shape matches AuthorityGraphApproval.evidence_snapshot exactly
// (server/app/services/ai_authority_builder_service.py's
// _corpus_evidence_snapshot), so the demo diff is real structural
// comparison, not a scripted narrative.
function _principalSnapshot(p: Principal) {
  return { id: p.id, name: p.name, role: p.role, reports_to: p.reports_to, confidence: p.confidence, resolved_principal_id: p.resolved_principal_id };
}
function _relationshipSnapshot(r: Relationship) {
  return { id: r.id, kind: r.kind, from_principal: r.from_principal, to_principal: r.to_principal, status: r.status, confidence: r.confidence };
}
function _conflictSnapshot(c: Conflict) {
  return { id: c.id, description: c.description, conflict_type: null, reviewer_recommendation: null, confidence: c.confidence };
}
function _gapSnapshot(g: Gap) {
  return { id: g.id, description: g.description };
}

const DEMO_APPROVAL_V1_ID = "graph-approval-meridian-v1";
const DEMO_APPROVAL_V2_ID = "graph-approval-meridian-v2";

export const demoGraphApprovalV1Snapshot = {
  principals: [demoAuthorityPrincipals[0], demoAuthorityPrincipals[1]].map(_principalSnapshot),
  relationships: [] as ReturnType<typeof _relationshipSnapshot>[],
  conflicts: [] as ReturnType<typeof _conflictSnapshot>[],
  gaps: [] as ReturnType<typeof _gapSnapshot>[],
  coverage: {
    documents_processed: 2, clauses_analysed: 30, clauses_ignored: 3, tables_extracted: 1,
    images_skipped: 0, sections_unsupported: 0, coverage_percent: 90.9,
  },
};

export const demoGraphApprovalV2Snapshot = {
  principals: demoAuthorityPrincipals.map(_principalSnapshot),
  relationships: demoRelationships.map(_relationshipSnapshot),
  conflicts: demoConflicts.map(_conflictSnapshot),
  gaps: demoGaps.map(_gapSnapshot),
  coverage: {
    documents_processed: 3, clauses_analysed: 48, clauses_ignored: 4, tables_extracted: 2,
    images_skipped: 1, sections_unsupported: 0, coverage_percent: 92.3,
  },
};

export const demoGraphApprovals: GraphApproval[] = [
  {
    id: DEMO_APPROVAL_V2_ID,
    corpus_id: DEMO_CORPUS_ID,
    reviewer: "Priya Chandrasekaran",
    version: 2,
    approval_reason: "Added Procurement and CISO authority after the Q1 governance review.",
    graph_hash: "sha256:demo-graph-hash-v2",
    approved_at: agoMs(2 * DAY),
    predecessor_approval_id: DEMO_APPROVAL_V1_ID,
    superseded_by_approval_id: null,
  },
  {
    id: DEMO_APPROVAL_V1_ID,
    corpus_id: DEMO_CORPUS_ID,
    reviewer: "Priya Chandrasekaran",
    version: 1,
    approval_reason: "Initial Treasury delegation captured and approved.",
    graph_hash: "sha256:demo-graph-hash-v1",
    approved_at: agoMs(21 * DAY),
    predecessor_approval_id: null,
    superseded_by_approval_id: DEMO_APPROVAL_V2_ID,
  },
];

export const demoGraphApprovalSnapshots: Record<string, typeof demoGraphApprovalV1Snapshot> = {
  [DEMO_APPROVAL_V1_ID]: demoGraphApprovalV1Snapshot,
  [DEMO_APPROVAL_V2_ID]: demoGraphApprovalV2Snapshot,
};

export const demoQuestions: Question[] = [
  {
    id: "authq-0",
    question: "Should the Head of Treasury's $50,000 disbursement limit apply per invoice, or per supplier per day?",
    context: "The Delegation of Authority Policy is ambiguous on aggregation -- confirmed with Treasury as per-invoice.",
    answered: true,
    answer: "Per invoice, confirmed by David Okonkwo (Head of Treasury).",
  },
];
