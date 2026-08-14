import type { BusinessUnit, Department, Team, OrganizationSettings, IntegrationsStatus, HealthStatus } from "../../organization/types";

// One fictional enterprise, referenced consistently across every fixture
// file: Meridian Industrial Group, a diversified industrial manufacturer.
// IDs are readable slugs (not opaque UUIDs) on purpose -- a visitor
// clicking through Evidence/Audit screens should be able to recognize
// the same agent/principal/policy recurring, which is what makes this
// read as one deployment instead of disconnected sample rows.

export const ORG_ID = "org-meridian-industrial";
export const ORG_NAME = "Meridian Industrial Group";

export const BU_CORPORATE_SERVICES = "bu-corporate-services";
export const BU_MANUFACTURING = "bu-manufacturing-operations";
export const BU_ENERGY = "bu-energy-systems";

export const DEPT_FINANCE = "dept-finance";
export const DEPT_PROCUREMENT = "dept-procurement";
export const DEPT_IT = "dept-it";
export const DEPT_SECURITY = "dept-security-compliance";

export const TEAM_ACCOUNTS_PAYABLE = "team-accounts-payable";
export const TEAM_TREASURY = "team-treasury";
export const TEAM_VENDOR_MANAGEMENT = "team-vendor-management";
export const TEAM_IDENTITY_ACCESS = "team-identity-access";

export const demoBusinessUnits: BusinessUnit[] = [
  { id: BU_CORPORATE_SERVICES, organization_id: ORG_ID, name: "Corporate Services", created_at: "2025-02-03T09:00:00Z" },
  { id: BU_MANUFACTURING, organization_id: ORG_ID, name: "Manufacturing Operations", created_at: "2025-02-03T09:00:00Z" },
  { id: BU_ENERGY, organization_id: ORG_ID, name: "Energy Systems", created_at: "2025-02-03T09:00:00Z" },
];

export const demoDepartments: Department[] = [
  { id: DEPT_FINANCE, business_unit_id: BU_CORPORATE_SERVICES, name: "Finance", created_at: "2025-02-04T09:00:00Z" },
  { id: DEPT_PROCUREMENT, business_unit_id: BU_CORPORATE_SERVICES, name: "Procurement", created_at: "2025-02-04T09:00:00Z" },
  { id: DEPT_IT, business_unit_id: BU_CORPORATE_SERVICES, name: "IT", created_at: "2025-02-04T09:00:00Z" },
  { id: DEPT_SECURITY, business_unit_id: BU_CORPORATE_SERVICES, name: "Security & Compliance", created_at: "2025-02-04T09:00:00Z" },
];

export const demoTeams: Team[] = [
  { id: TEAM_ACCOUNTS_PAYABLE, department_id: DEPT_FINANCE, name: "Accounts Payable", created_at: "2025-02-05T09:00:00Z" },
  { id: TEAM_TREASURY, department_id: DEPT_FINANCE, name: "Treasury", created_at: "2025-02-05T09:00:00Z" },
  { id: TEAM_VENDOR_MANAGEMENT, department_id: DEPT_PROCUREMENT, name: "Vendor Management", created_at: "2025-02-05T09:00:00Z" },
  { id: TEAM_IDENTITY_ACCESS, department_id: DEPT_IT, name: "Identity & Access", created_at: "2025-02-05T09:00:00Z" },
];

export const demoOrganizationSettings: OrganizationSettings = {
  name: ORG_NAME,
  logo_url: null,
  timezone: "America/Chicago",
  default_currency: "USD",
  default_language: "en",
  settings: {
    session_timeout_minutes: 480,
    notifications: { email: true, slack: true },
  },
};

export const demoIntegrationsStatus: IntegrationsStatus = {
  anthropic: "connected",
  azure_ai_foundry: "connected",
  azure_openai: "connected",
  aws_bedrock: "configuration_required",
  opa: "connected",
  postgresql: "connected",
};

export const demoHealthStatus: HealthStatus = {
  runtime_authority: "healthy",
  evidence_engine: "healthy",
  opa: "healthy",
  compiler: "healthy",
  database: "healthy",
  anthropic: "healthy",
};

export const SUPPLIERS = [
  "Ashford Precision Components",
  "Northgate Industrial Supply",
  "Delta Fabrication Partners",
  "Sterling Logistics Solutions",
] as const;
