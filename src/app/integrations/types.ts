// Trusted Integration Architecture, Phase 4: TypeScript mirrors of the
// backend's Phase 1-3 response schemas (server/app/schemas/integration_
// contract.py, integration_identity.py, enforcement_binding.py). Field
// names match the wire shape exactly -- the product-language relabeling
// (System, Action mapping, Trusted connection, Runtime connection)
// happens in the UI copy, never by renaming these fields.

export interface IntegrationSystem {
  id: string;
  organization_id: string;
  external_system_label: string;
  created_by: string | null;
  created_at: string;
}

export type MappingStatus = "draft" | "validated" | "approved" | "retired";

export interface ActionMapping {
  id: string;
  integration_id: string;
  organization_id: string;
  source_operation: string;
  version: number;
  canonical_action: string;
  resource_path: string | null;
  fact_subject_path: string | null;
  amount_path: string | null;
  currency_path: string | null;
  context_bindings: Record<string, string>;
  content_hash: string | null;
  source_schema_fingerprint: string | null;
  status: MappingStatus;
  created_by: string | null;
  created_at: string;
  validated_at: string | null;
  approved_by: string | null;
  approved_at: string | null;
  retired_at: string | null;
}

export type TrustedConnectionStatus = "registered" | "active" | "suspended" | "revoked" | "retired";

export interface TrustedConnection {
  id: string;
  organization_id: string;
  name: string;
  status: TrustedConnectionStatus;
  created_by: string | null;
  created_at: string;
}

export type CertificateStatus = "issued" | "active" | "rotated" | "expired" | "revoked";

export interface TrustedConnectionCertificate {
  id: string;
  integration_identity_id: string;
  status: CertificateStatus;
  issued_at: string;
  activated_at: string | null;
  rotated_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

export type ConnectionStatus = "draft" | "active" | "retired";

export interface RuntimeConnection {
  id: string;
  organization_id: string;
  integration_identity_id: string;
  integration_contract_version_id: string;
  integration_id: string;
  source_operation: string;
  environment: string;
  status: ConnectionStatus;
  created_by: string | null;
  created_at: string;
  activated_at: string | null;
  retired_at: string | null;
  allowed_agent_ids: string[];
}

export interface AllowedAgent {
  id: string;
  name: string;
  status: string;
}
