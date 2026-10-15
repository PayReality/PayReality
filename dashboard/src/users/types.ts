// Hand-synced against server/app/schemas/users.py.
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

export interface CreateUserResponse {
  user: OrgUser;
  // Shown exactly once, at creation time -- there is no email delivery
  // in this platform yet, so this response is the real, disclosed way an
  // Owner hands a new teammate their first credential today.
  temporary_password: string;
}
