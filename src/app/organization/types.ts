export interface OrganizationSettings {
  name: string;
  logo_url: string | null;
  timezone: string;
  default_currency: string;
  default_language: string;
  settings: Record<string, unknown>;
}

export type IntegrationStatus = "connected" | "disconnected" | "configuration_required";

// Authority-as-a-continuous-object, Stage J: the downstream systems
// Runtime Authority is meant to eventually gate -- a registered
// existence, never a connection. `status` mirrors the table's own
// check constraint; no connector code anywhere sets it to "connected".
export type EnterpriseSystemType =
  | "erp"
  | "crm"
  | "finance"
  | "hr"
  | "procurement"
  | "legal"
  | "manufacturing"
  | "other";
export type EnterpriseSystemStatus = "configuration_required" | "connected";

export interface EnterpriseSystem {
  id: string;
  organization_id: string;
  name: string;
  type: EnterpriseSystemType;
  status: EnterpriseSystemStatus;
  created_at: string;
}

// Phase 5, Release 1: the Authority Model's org hierarchy
// (PHASE_1_AUTHORITY_MODEL.md) -- existing tables, now authorable.
// Business Unit belongs to Organization; Department belongs to a
// Business Unit; Team belongs to a Department.
export interface BusinessUnit {
  id: string;
  organization_id: string;
  name: string;
  created_at: string;
}

export interface Department {
  id: string;
  business_unit_id: string;
  name: string;
  created_at: string;
}

export interface Team {
  id: string;
  department_id: string;
  name: string;
  created_at: string;
}

export interface IntegrationsStatus {
  anthropic: IntegrationStatus;
  azure_ai_foundry: IntegrationStatus;
  azure_openai: IntegrationStatus;
  aws_bedrock: IntegrationStatus;
  opa: IntegrationStatus;
  postgresql: IntegrationStatus;
}

export type HealthState = "healthy" | "warning" | "offline";

export interface HealthStatus {
  runtime_authority: HealthState;
  evidence_engine: HealthState;
  opa: HealthState;
  compiler: HealthState;
  database: HealthState;
  anthropic: HealthState;
}

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  role: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface CreateApiKeyResult {
  api_key: ApiKey;
  raw_key: string;
}

export interface OrgUser {
  id: string;
  email: string;
  name: string;
  role: string;
  status: string;
  mfa_enabled: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface CreateUserResult {
  user: OrgUser;
  temporary_password: string;
}

// Milestone 3 (Enterprise Surface Isolation): the Organization Lifecycle.
export type OrganizationLifecycleStatus = "active" | "deactivated" | "archived";

export interface OrganizationLifecycle {
  id: string;
  name: string;
  status: OrganizationLifecycleStatus;
  created_at: string;
  deactivated_at: string | null;
  deactivated_by: string | null;
  archived_at: string | null;
  archived_by: string | null;
}

export interface CreateOrganizationResult {
  organization: OrganizationLifecycle;
  owner: OrgUser;
  temporary_password: string;
}

export type InvitationStatus = "pending" | "accepted" | "revoked" | "expired";

export interface Invitation {
  id: string;
  organization_id: string;
  email: string;
  role: string;
  status: InvitationStatus;
  invited_by: string | null;
  created_at: string;
  expires_at: string;
  accepted_at: string | null;
}

export interface InviteMemberResult {
  invitation: Invitation;
  raw_token: string;
}
