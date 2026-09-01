import type {
  ActionMapping,
  AllowedAgent,
  IntegrationSystem,
  RuntimeConnection,
  TrustedConnection,
  TrustedConnectionCertificate,
} from "../../integrations/types";
import { AGENT_AP_INVOICE } from "./agents";

// Trusted Integration Architecture, Phase 4: one curated, already-set-up
// example so a visitor sees a working connection immediately, not an
// empty state -- the same "seed one real example" convention this
// demo's other fixtures already follow (demoDecisions, demoEvidence).

export const DEMO_SYSTEM_SAP = "system-sap-demo";
export const DEMO_MAPPING_SAP_APPROVED = "mapping-sap-approved-demo";
export const DEMO_TRUSTED_CONNECTION_SAP = "trusted-connection-sap-demo";
export const DEMO_CERTIFICATE_SAP = "certificate-sap-demo";
export const DEMO_CONNECTION_SAP = "connection-sap-demo";

export const demoSystems: IntegrationSystem[] = [
  {
    id: DEMO_SYSTEM_SAP,
    organization_id: "org-demo",
    external_system_label: "SAP S/4HANA",
    created_by: "demo@example.com",
    created_at: "2026-06-01T09:00:00Z",
  },
];

export const demoMappings: ActionMapping[] = [
  {
    id: DEMO_MAPPING_SAP_APPROVED,
    integration_id: DEMO_SYSTEM_SAP,
    organization_id: "org-demo",
    source_operation: "ChangeSupplierBankDetails",
    version: 1,
    // Trusted Integration Architecture, Phase 6.1 (Production
    // Authorization Assurance, Part C): was "vendor_payment", the
    // closest value the closed vocabulary had when this fixture was
    // first written. Changing a supplier's bank details and actually
    // paying a vendor are materially different authorities; this
    // mapping now uses its own precise canonical action instead
    // (compiler_v2.GENERALIZATION_PROOF_SCOPES). No amount_path/
    // currency_path: this operation itself moves no money, so it never
    // had a real payment.amount/payment.currency to bind -- the
    // demo's own earlier "$84,000" framing was a narrative liberty this
    // milestone's own precision goal corrects, not a real field of the
    // reference business system's actual API.
    canonical_action: "supplier_bank_details_change",
    resource_path: "supplier.id",
    fact_subject_path: "supplier.id",
    amount_path: null,
    currency_path: null,
    context_bindings: { department: "dept.name" },
    content_hash: "sha256:demo-mapping-hash-v1",
    source_schema_fingerprint: null,
    status: "approved",
    created_by: "demo@example.com",
    created_at: "2026-06-01T09:05:00Z",
    validated_at: "2026-06-01T09:10:00Z",
    approved_by: "demo@example.com",
    approved_at: "2026-06-01T09:15:00Z",
    retired_at: null,
  },
];

export const demoTrustedConnections: TrustedConnection[] = [
  {
    id: DEMO_TRUSTED_CONNECTION_SAP,
    organization_id: "org-demo",
    name: "SAP Procurement Adapter",
    status: "active",
    created_by: "demo@example.com",
    created_at: "2026-06-01T09:20:00Z",
  },
];

export const demoTrustedConnectionCertificates: TrustedConnectionCertificate[] = [
  {
    id: DEMO_CERTIFICATE_SAP,
    integration_identity_id: DEMO_TRUSTED_CONNECTION_SAP,
    status: "active",
    issued_at: "2026-06-01T09:20:00Z",
    activated_at: "2026-06-01T09:21:00Z",
    rotated_at: null,
    expires_at: null,
    revoked_at: null,
  },
];

export const demoConnections: RuntimeConnection[] = [
  {
    id: DEMO_CONNECTION_SAP,
    organization_id: "org-demo",
    integration_identity_id: DEMO_TRUSTED_CONNECTION_SAP,
    integration_contract_version_id: DEMO_MAPPING_SAP_APPROVED,
    integration_id: DEMO_SYSTEM_SAP,
    source_operation: "ChangeSupplierBankDetails",
    environment: "production",
    status: "active",
    created_by: "demo@example.com",
    created_at: "2026-06-01T09:25:00Z",
    activated_at: "2026-06-01T09:26:00Z",
    retired_at: null,
    allowed_agent_ids: [AGENT_AP_INVOICE],
  },
];

export const demoAllowedAgents: Record<string, AllowedAgent[]> = {
  [DEMO_CONNECTION_SAP]: [{ id: AGENT_AP_INVOICE, name: "AP Invoice Agent", status: "active" }],
};
