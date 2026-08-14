import { apiClient, ApiError } from "../live/apiClient";
import type { CurrentUser, LoginResponse } from "./types";

interface OrganizationSummary {
  id: string;
}

export const authApi = {
  login: (email: string, password: string) =>
    apiClient.post<LoginResponse>("/v1/auth/login", { email, password }),
  logout: () => apiClient.post<void>("/v1/auth/logout"),
  me: () => apiClient.get<CurrentUser>("/v1/auth/me"),
  // Uses the Operator Key directly as this one request's credential
  // (not necessarily whatever's already saved in the sidebar) -- see
  // SetupOwnerPage.tsx for why this exists. Every operator-gated,
  // org-scoped request needs an explicit X-PayReality-Organization-Id
  // (Milestone 3); a first-time visitor claiming the bootstrapped Owner
  // has no organization id stored yet, the exact chicken-and-egg problem
  // this page exists to solve, so it's discovered here the same way
  // scripts/smoke_test.py's own docstring already recommends: list
  // organizations with just the key, and use the one that exists.
  setupOwner: async (email: string, password: string, operatorKey: string) => {
    const operatorHeaders = { headers: { "X-PayReality-Operator-Key": operatorKey } };
    const organizations = await apiClient.get<OrganizationSummary[]>("/v1/organizations", operatorHeaders);
    if (organizations.length === 0) {
      throw new ApiError(503, { detail: "no_organization_bootstrapped" });
    }
    return apiClient.post<CurrentUser>(
      "/v1/auth/setup-owner",
      { email, password },
      {
        headers: {
          "X-PayReality-Operator-Key": operatorKey,
          "X-PayReality-Organization-Id": organizations[0].id,
        },
      },
    );
  },
};
