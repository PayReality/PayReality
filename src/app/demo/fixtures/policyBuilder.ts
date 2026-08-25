import type { Upload, Candidate } from "../../ai-policy-builder/types";
import { agoMs, DAY } from "../liveClock";
import { PRINCIPAL_RUIZ } from "./principals";
import { AGENT_VENDOR_RISK } from "./agents";
import { ES_COUPA } from "./enterpriseSystems";

export const DEMO_UPLOAD_ID = "upload-meridian-vendor-risk-memo";

export const demoUploads: Upload[] = [
  { upload_id: DEMO_UPLOAD_ID, filename: "Vendor Risk Escalation Memo.pdf", format: "pdf", status: "extracted", error: null, uploaded_at: agoMs(9 * DAY) },
];

export const DEMO_CANDIDATE_ID = "candidate-vendor-risk-hold";

export const demoCandidates: Candidate[] = [
  {
    candidate_id: DEMO_CANDIDATE_ID,
    upload_id: DEMO_UPLOAD_ID,
    content: {
      name: "Hold payments to high-risk suppliers pending review",
      description: "Blocks invoice payment to any supplier flagged high-risk by Vendor-Risk-Agent until Procurement clears it.",
      scope: { principal: PRINCIPAL_RUIZ, action: "vendor_payment", agent: AGENT_VENDOR_RISK, resource: null },
      conditions: [{ field: "supplier_risk_flag", operator: "==", value: "high" }],
      effect: "require_human_review",
      constraints: { delegated_by: "Elena Ruiz, VP Procurement", expires: null, evidence_required: true, risk_level: "HIGH", authority_id: null, mandate_id: null, enterprise_system_id: ES_COUPA },
      metadata: { owner: "Elena Ruiz", created_by: "Elena Ruiz", tags: ["procurement", "risk"] },
    },
    confidence: 0.88,
    missing_fields: [],
    source_excerpt: "Payments to suppliers flagged high-risk by continuous screening should be held for Procurement review before disbursement.",
    source_location: "Vendor Risk Escalation Memo, p. 1",
    status: "pending_review",
    promoted_policy_key: null,
    created_at: agoMs(9 * DAY),
  },
];
