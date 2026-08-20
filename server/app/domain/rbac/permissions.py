"""Phase 10 (RBAC.md): the permission model. Pure module, no DB, no
network, matching this codebase's existing convention for fixed
vocabularies (scope_vocabulary.py's KNOWN_SCOPES, compiler_v2.py's
FinancialVocabulary) -- a fixed enumeration of roles and permissions is
a schema/code change here, not a runtime-configurable table, for the
same reason those other vocabularies aren't: a new permission or role
is a real security decision that deserves a code review, not a config
toggle an Owner can silently flip.

"Never check roles directly. Always check permissions" (the phase's own
directive): every enforcement point in this codebase checks
`has_permission(role, permission)`, never `role == Role.OWNER` or
similar. The role -> permission mapping is the ONE place role identity
turns into an actual authorization decision.
"""

from enum import Enum


class Role(str, Enum):
    OWNER = "owner"
    GOVERNANCE_ADMIN = "governance_admin"
    AGENT_ADMIN = "agent_admin"
    REVIEWER = "reviewer"
    AUDITOR = "auditor"
    EXECUTIVE = "executive"


class Permission(str, Enum):
    # Organisation & platform administration -- Owner only, no exceptions.
    ORGANISATION_MANAGE = "organisation.manage"
    ORGANISATION_DELETE = "organisation.delete"
    USERS_MANAGE = "users.manage"
    INTEGRATIONS_MANAGE = "integrations.manage"
    API_KEYS_MANAGE = "api_keys.manage"
    OPERATOR_KEYS_VIEW = "operator_keys.view"
    AUDIT_EXPORT = "audit.export"
    SETTINGS_VIEW = "settings.view"

    # Runtime Policy (Governance).
    RUNTIME_POLICY_CREATE = "runtime_policy.create"
    RUNTIME_POLICY_EDIT = "runtime_policy.edit"
    RUNTIME_POLICY_PUBLISH = "runtime_policy.publish"
    RUNTIME_POLICY_VIEW = "runtime_policy.view"

    # AI Authority Builder / AI Policy Builder: upload, review, approve,
    # reject, promote a candidate to a draft Runtime Policy. Explicitly
    # NOT runtime_policy.publish -- promoting a candidate produces a
    # draft; publishing it still requires that separate permission,
    # which is exactly how "Reviewer... cannot publish" stays true even
    # though a Reviewer can promote.
    AUTHORITY_REVIEW = "authority.review"

    # Agent Lifecycle (AGENT_LIFECYCLE.md's full state machine, not just
    # the five verbs Phase 10's spec named as examples: a role that can
    # suspend but not reactivate an agent isn't a coherent role).
    AGENT_REGISTER = "agent.register"
    AGENT_ACTIVATE = "agent.activate"
    AGENT_SUSPEND = "agent.suspend"
    AGENT_RETIRE = "agent.retire"
    AGENT_REVOKE = "agent.revoke"
    AGENT_ROTATE = "agent.rotate"
    AGENT_MANAGE = "agent.manage"  # metadata edits, ownership transfer, group management
    AGENT_VIEW = "agent.view"

    PRINCIPAL_MANAGE = "principal.manage"

    EVIDENCE_VIEW = "evidence.view"
    DECISIONS_VIEW = "decisions.view"
    DECISIONS_RESOLVE = "decisions.resolve"
    ASSURANCE_VIEW = "assurance.view"


# The full permission set, used to grant Owner "full platform control"
# without hand-maintaining a second, parallel list that would drift
# from the Permission enum above.
_ALL_PERMISSIONS = frozenset(Permission)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: _ALL_PERMISSIONS,
    Role.GOVERNANCE_ADMIN: frozenset(
        {
            Permission.RUNTIME_POLICY_CREATE,
            Permission.RUNTIME_POLICY_EDIT,
            Permission.RUNTIME_POLICY_PUBLISH,
            Permission.RUNTIME_POLICY_VIEW,
            Permission.AUTHORITY_REVIEW,
            Permission.EVIDENCE_VIEW,
            Permission.DECISIONS_VIEW,
            Permission.DECISIONS_RESOLVE,
            Permission.ASSURANCE_VIEW,
            Permission.PRINCIPAL_MANAGE,
            Permission.AGENT_VIEW,
        }
    ),
    Role.AGENT_ADMIN: frozenset(
        {
            Permission.AGENT_REGISTER,
            Permission.AGENT_ACTIVATE,
            Permission.AGENT_SUSPEND,
            Permission.AGENT_RETIRE,
            Permission.AGENT_REVOKE,
            Permission.AGENT_ROTATE,
            Permission.AGENT_MANAGE,
            Permission.AGENT_VIEW,
            Permission.PRINCIPAL_MANAGE,
        }
    ),
    Role.REVIEWER: frozenset(
        {
            Permission.AUTHORITY_REVIEW,
            Permission.DECISIONS_VIEW,
            Permission.DECISIONS_RESOLVE,
        }
    ),
    Role.AUDITOR: frozenset(
        {
            Permission.EVIDENCE_VIEW,
            Permission.DECISIONS_VIEW,
            Permission.RUNTIME_POLICY_VIEW,
            Permission.AGENT_VIEW,
            Permission.ASSURANCE_VIEW,
        }
    ),
    Role.EXECUTIVE: frozenset({Permission.ASSURANCE_VIEW}),
}


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def permissions_for_role(role: Role) -> list[str]:
    """Sorted so the frontend gets a stable list to render/diff against,
    not an order that shuffles per process based on set iteration."""
    return sorted(permission.value for permission in ROLE_PERMISSIONS.get(role, frozenset()))
