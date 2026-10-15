import { apiClient } from "../lib/apiClient";
import type { CurrentUser, LoginResponse } from "./types";

// This dashboard never implements its own signup/user-creation flow and
// never surfaces the Operator Key (see AGENTS.md / the task brief) -- a
// real reviewer logs in with real credentials an org admin already
// created for them via POST /v1/users (see src/users/api.ts), the same
// way every other login in this platform works.
export const authApi = {
  login: (email: string, password: string) => apiClient.post<LoginResponse>("/v1/auth/login", { email, password }),
  logout: () => apiClient.post<void>("/v1/auth/logout"),
  me: () => apiClient.get<CurrentUser>("/v1/auth/me"),
};
