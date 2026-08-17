import { apiClient } from "../live/apiClient";
import type { LiveEvidence } from "../live/types";
import { notifyResourceChanged } from "../services/resourceSync";
import type {
  ApiKey,
  BusinessUnit,
  CreateApiKeyResult,
  CreateOrganizationResult,
  CreateUserResult,
  Department,
  EnterpriseSystem,
  EnterpriseSystemType,
  HealthStatus,
  IntegrationsStatus,
  Invitation,
  InviteMemberResult,
  OrganizationLifecycle,
  OrganizationSettings,
  OrgUser,
  Team,
} from "./types";

export const organizationApi = {
  getSettings: () => apiClient.get<OrganizationSettings>("/v1/organization/settings"),
  updateSettings: (body: Partial<OrganizationSettings>) =>
    apiClient.patch<OrganizationSettings>("/v1/organization/settings", body).then((r) => { notifyResourceChanged("organization"); return r; }),
  getIntegrations: () => apiClient.get<IntegrationsStatus>("/v1/organization/integrations"),
  getHealth: () => apiClient.get<HealthStatus>("/v1/organization/health"),
  exportEvidence: () => apiClient.get<LiveEvidence[]>("/v1/organization/exports/evidence"),

  listApiKeys: () => apiClient.get<ApiKey[]>("/v1/organization/api-keys"),
  createApiKey: (name: string, role: string) =>
    apiClient.post<CreateApiKeyResult>("/v1/organization/api-keys", { name, role }),
  revokeApiKey: (id: string) => apiClient.delete<void>(`/v1/organization/api-keys/${id}`),

  listEnterpriseSystems: () => apiClient.get<EnterpriseSystem[]>("/v1/enterprise-systems"),
  createEnterpriseSystem: (name: string, type: EnterpriseSystemType) =>
    apiClient.post<EnterpriseSystem>("/v1/enterprise-systems", { name, type }),
};

// Phase 5, Release 1: Organisation Structure (Business Units / Departments / Teams).
// Milestone 13 Phase 6A: every mutation here signals "organization
// changed" once it succeeds -- Agent registration's business-unit
// picker, Authority Builder's principal assignment, and any other
// org-structure-dependent view can pick up the change without a reload.
export const organizationStructureApi = {
  listBusinessUnits: () => apiClient.get<BusinessUnit[]>("/v1/business-units"),
  createBusinessUnit: (name: string) =>
    apiClient.post<BusinessUnit>("/v1/business-units", { name }).then((r) => { notifyResourceChanged("organization"); return r; }),
  updateBusinessUnit: (id: string, name: string) =>
    apiClient.patch<BusinessUnit>(`/v1/business-units/${id}`, { name }).then((r) => { notifyResourceChanged("organization"); return r; }),
  deleteBusinessUnit: (id: string) =>
    apiClient.delete<void>(`/v1/business-units/${id}`).then((r) => { notifyResourceChanged("organization"); return r; }),

  listDepartments: (businessUnitId?: string) =>
    apiClient.get<Department[]>(
      `/v1/departments${businessUnitId ? `?business_unit_id=${encodeURIComponent(businessUnitId)}` : ""}`
    ),
  createDepartment: (businessUnitId: string, name: string) =>
    apiClient.post<Department>("/v1/departments", { business_unit_id: businessUnitId, name }).then((r) => { notifyResourceChanged("organization"); return r; }),
  updateDepartment: (id: string, name: string) =>
    apiClient.patch<Department>(`/v1/departments/${id}`, { name }).then((r) => { notifyResourceChanged("organization"); return r; }),
  deleteDepartment: (id: string) =>
    apiClient.delete<void>(`/v1/departments/${id}`).then((r) => { notifyResourceChanged("organization"); return r; }),

  listTeams: (departmentId?: string) =>
    apiClient.get<Team[]>(`/v1/teams${departmentId ? `?department_id=${encodeURIComponent(departmentId)}` : ""}`),
  createTeam: (departmentId: string, name: string) =>
    apiClient.post<Team>("/v1/teams", { department_id: departmentId, name }).then((r) => { notifyResourceChanged("organization"); return r; }),
  updateTeam: (id: string, name: string) =>
    apiClient.patch<Team>(`/v1/teams/${id}`, { name }).then((r) => { notifyResourceChanged("organization"); return r; }),
  deleteTeam: (id: string) =>
    apiClient.delete<void>(`/v1/teams/${id}`).then((r) => { notifyResourceChanged("organization"); return r; }),
};

export const usersApi = {
  list: () => apiClient.get<OrgUser[]>("/v1/users"),
  create: (email: string, name: string, role: string) =>
    apiClient.post<CreateUserResult>("/v1/users", { email, name, role }),
  updateRole: (userId: string, role: string) =>
    apiClient.patch<OrgUser>(`/v1/users/${userId}/role`, { role }),
  updateStatus: (userId: string, status: string) =>
    apiClient.patch<OrgUser>(`/v1/users/${userId}/status`, { status }),
};

// Milestone 3 (Enterprise Surface Isolation): inviting a member into MY
// OWN organization -- an ordinary per-tenant action (USERS_MANAGE, same
// as usersApi.create above), distinct from platformOrganizationsApi
// below. The real email-and-accept flow usersApi.create never was: a
// one-time token, shown once, delivered however the inviter chooses.
export const invitationsApi = {
  list: (status?: string) =>
    apiClient.get<Invitation[]>(`/v1/organization/invitations${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  invite: (email: string, role: string) =>
    apiClient.post<InviteMemberResult>("/v1/organization/invitations", { email, role }),
  revoke: (invitationId: string) =>
    apiClient.delete<Invitation>(`/v1/organization/invitations/${invitationId}`),
};

// Milestone 3 (Enterprise Surface Isolation): create/list/deactivate/
// archive an ARBITRARY organization. Platform-admin only -- every call
// here requires the Operator Key AND an explicit target organization on
// the ones that act on one (see OperatorKeyField.tsx), matching the
// backend's own verify_operator_key gate
// (routers/organization_lifecycle.py). Confirmed as the first UI ever
// built for this: before this milestone, an Organization could only be
// created by a startup-only server hook, with no API or UI at all.
export const platformOrganizationsApi = {
  list: () => apiClient.get<OrganizationLifecycle[]>("/v1/organizations"),
  create: (name: string, ownerEmail: string, ownerName: string) =>
    apiClient.post<CreateOrganizationResult>("/v1/organizations", {
      name,
      owner_email: ownerEmail,
      owner_name: ownerName,
    }),
  deactivate: (organizationId: string) =>
    apiClient.post<OrganizationLifecycle>(`/v1/organizations/${organizationId}/deactivate`, {}),
  reactivate: (organizationId: string) =>
    apiClient.post<OrganizationLifecycle>(`/v1/organizations/${organizationId}/reactivate`, {}),
  archive: (organizationId: string) =>
    apiClient.post<OrganizationLifecycle>(`/v1/organizations/${organizationId}/archive`, {}),
};
