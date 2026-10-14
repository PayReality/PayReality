// Hand-synced against server/app/schemas/auth.py's CurrentUserResponse /
// LoginResponse -- the same "hand-written frontend types matching the
// real backend response shape" convention this codebase already follows
// (see the recovered src/app/decision-intelligence/types.ts for
// precedent, read from git history during this build).
export interface CurrentUser {
  id: string;
  organization_id: string;
  email: string;
  name: string;
  role: string;
  status: string;
  mfa_enabled: boolean;
  must_reset_password: boolean;
  last_login_at: string | null;
  permissions: string[];
}

export interface LoginResponse {
  token: string;
  expires_at: string;
  user: CurrentUser;
}

// Mirrors server/app/domain/rbac/permissions.py's Role enum.
export const ROLE_LABELS: Record<string, string> = {
  owner: "Organisation Owner",
  governance_admin: "Governance Administrator",
  agent_admin: "Agent Administrator",
  reviewer: "Reviewer",
  auditor: "Auditor",
  executive: "Executive",
};
