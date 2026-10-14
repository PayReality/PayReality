import { apiClient } from "../lib/apiClient";
import type { CreateUserResponse, OrgUser } from "./types";

// /v1/users is gated on Permission.USERS_MANAGE for EVERY route,
// including list (server/app/routers/users.py's router-level
// `dependencies`) -- only a role holding USERS_MANAGE (Owner, per
// ROLE_PERMISSIONS in permissions.py) can call any of this. The People &
// Ownership page checks `hasPermission("users.manage")` before even
// attempting these calls.
export const usersApi = {
  list: () => apiClient.get<OrgUser[]>("/v1/users"),
  create: (body: { email: string; name: string; role: string }) =>
    apiClient.post<CreateUserResponse>("/v1/users", body),
  updateRole: (userId: string, role: string) => apiClient.patch<OrgUser>(`/v1/users/${userId}/role`, { role }),
  updateStatus: (userId: string, status: string) => apiClient.patch<OrgUser>(`/v1/users/${userId}/status`, { status }),
};
