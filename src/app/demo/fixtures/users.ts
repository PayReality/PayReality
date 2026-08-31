import type { OrgUser } from "../../organization/types";
import type { CurrentUser } from "../../auth/types";
import { agoMs, MINUTE, DAY } from "../liveClock";
import { ORG_ID } from "./organization";

export const USER_OKONKWO = "user-okonkwo";
export const USER_CHANDRASEKARAN = "user-chandrasekaran";
export const USER_RUIZ = "user-ruiz";
export const USER_WEBB = "user-webb";
export const USER_KIM = "user-kim";
export const USER_WHITFIELD = "user-whitfield";

export const demoUsers: OrgUser[] = [
  { id: USER_CHANDRASEKARAN, email: "priya.chandrasekaran@meridianindustrial.com", name: "Priya Chandrasekaran", role: "owner", status: "active", mfa_enabled: true, last_login_at: agoMs(35 * MINUTE), created_at: agoMs(300 * DAY) },
  { id: USER_OKONKWO, email: "david.okonkwo@meridianindustrial.com", name: "David Okonkwo", role: "governance_admin", status: "active", mfa_enabled: true, last_login_at: agoMs(2 * MINUTE), created_at: agoMs(280 * DAY) },
  { id: USER_RUIZ, email: "elena.ruiz@meridianindustrial.com", name: "Elena Ruiz", role: "reviewer", status: "active", mfa_enabled: true, last_login_at: agoMs(50 * MINUTE), created_at: agoMs(250 * DAY) },
  { id: USER_WEBB, email: "marcus.webb@meridianindustrial.com", name: "Marcus Webb", role: "agent_admin", status: "active", mfa_enabled: true, last_login_at: agoMs(4 * 60 * MINUTE), created_at: agoMs(250 * DAY) },
  { id: USER_KIM, email: "sarah.kim@meridianindustrial.com", name: "Sarah Kim", role: "auditor", status: "active", mfa_enabled: false, last_login_at: agoMs(DAY), created_at: agoMs(180 * DAY) },
  { id: USER_WHITFIELD, email: "james.whitfield@meridianindustrial.com", name: "James Whitfield", role: "executive", status: "active", mfa_enabled: true, last_login_at: agoMs(3 * DAY), created_at: agoMs(180 * DAY) },
];

// The identity a demo visitor is transparently "signed in" as.
//
// Trusted Integration Architecture, Phase 4 follow-up: switched from
// David Okonkwo (governance_admin) to Priya Chandrasekaran (owner).
// governance_admin has neither settings.view nor
// integration_contract.manage/.publish in the real RBAC model
// (server/app/domain/rbac/permissions.py's own ROLE_PERMISSIONS), so
// Organisation Settings -- and everything under it, including the new
// Settings > Integrations feature -- correctly never appeared for that
// identity. That was a real, if previously invisible, gap: a visitor
// could never see the guided Integrations journey at all. Owner has
// every permission in the system by design (ROLE_PERMISSIONS[OWNER] =
// the full Permission enum, no hand-picked subset), so this is the
// smallest fixture change that makes every existing gated surface
// visible without diverging the demo's permission list from any real
// role's own definition -- the exact drift this file's previous
// comment already warned against for governance_admin. Priya already
// appears elsewhere in the fixtures as an approver identity (Authority
// Graph corpus approvals), so this is consistent with, not new
// against, that existing narrative thread.
export const demoCurrentUser: CurrentUser = {
  id: USER_CHANDRASEKARAN,
  organization_id: ORG_ID,
  email: "priya.chandrasekaran@meridianindustrial.com",
  name: "Priya Chandrasekaran",
  role: "owner",
  status: "active",
  mfa_enabled: true,
  must_reset_password: false,
  last_login_at: agoMs(35 * MINUTE),
  // Must equal server/app/domain/rbac/permissions.py's full Permission
  // enum exactly (ROLE_PERMISSIONS[OWNER] = _ALL_PERMISSIONS, not a
  // hand-picked subset) -- Layout.tsx's nav gate and every
  // RequirePermission/hasPermission call in the app checks this list
  // the same way it checks a real session's permissions, so drifting
  // from the real role definition silently hides real pages (this
  // exact failure mode already happened once for governance_admin,
  // see git history).
  permissions: [
    "organisation.manage",
    "organisation.delete",
    "users.manage",
    "integrations.manage",
    "api_keys.manage",
    "operator_keys.view",
    "audit.export",
    "settings.view",
    "runtime_policy.create",
    "runtime_policy.edit",
    "runtime_policy.publish",
    "runtime_policy.view",
    "authority.review",
    "agent.register",
    "agent.activate",
    "agent.suspend",
    "agent.retire",
    "agent.revoke",
    "agent.rotate",
    "agent.manage",
    "agent.view",
    "principal.manage",
    "evidence.view",
    "decisions.view",
    "decisions.resolve",
    "assurance.view",
    "facts.manage",
    "capability.issue",
    "integration_contract.manage",
    "integration_contract.publish",
    "integration_identity.manage",
  ],
};
