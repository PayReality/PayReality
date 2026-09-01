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

    # Trusted Enterprise Facts (PAYREALITY_FUTURE_VISION.md Part A):
    # registering/revoking a FactSource and reading ingested facts is a
    # governance action over what the org treats as trusted external
    # reality -- not the same privilege as viewing a decision
    # (DECISIONS_VIEW) or managing a Principal (PRINCIPAL_MANAGE), and
    # deliberately its own permission rather than folded into either,
    # since a role could plausibly need one without the other. Fact
    # INGESTION itself is authenticated by the fact's own signature
    # (fact_service.ingest_fact), never gated by this or any other RBAC
    # permission -- the same model Intent submission already uses
    # (verify_agent_signature, not require_permission).
    FACTS_MANAGE = "facts.manage"

    # Capability Authorization Protocol (PAYREALITY_FUTURE_VISION.md
    # Part C): deliberately NOT reusing DECISIONS_VIEW. Viewing a
    # decision and minting an executable, short-lived authorization
    # capability for it are different privileges -- a role that can see
    # a decision has not thereby demonstrated it should be able to
    # authorize the underlying action to actually execute.
    CAPABILITY_ISSUE = "capability.issue"

    # Phase 6.1 (Production Authorization Assurance, Part B): verifying
    # and consuming a Capability is a distinct privilege from ISSUING
    # one -- the party that approved/issued the authority is not
    # necessarily the same party operating the downstream enforcement
    # checkpoint that redeems it. Deliberately its own permission, not
    # folded into CAPABILITY_ISSUE, so an organisation can hand a
    # narrowly-scoped credential to its own reference PEP (via a real,
    # tenant-bound ApiKey) without that credential also being able to
    # mint new Capabilities.
    CAPABILITY_VERIFY = "capability.verify"

    # Trusted Integration Architecture, Phase 1 (Founder Decisions &
    # Design Closure Addendum, RBAC decision): deliberately NOT reusing
    # RUNTIME_POLICY_PUBLISH -- mapping-semantic governance (does this
    # Integration Contract mapping truthfully represent an external
    # operation?) and RuntimePolicy governance (does this rule reflect
    # organizational authority?) are different questions that may
    # legitimately be delegated to different enterprise roles. MANAGE
    # covers authoring a draft mapping and triggering its own
    # deterministic validation (validation authorizes nothing, per the
    # addendum's own validation-permission decision); PUBLISH is the one
    # governance-relevant boundary -- approving a validated mapping, or
    # retiring an approved one.
    INTEGRATION_CONTRACT_MANAGE = "integration_contract.manage"
    INTEGRATION_CONTRACT_PUBLISH = "integration_contract.publish"

    # Trusted Integration Architecture, Phase 2: IntegrationIdentity
    # credential/workload lifecycle (register/rotate/suspend/revoke/
    # retire) is a distinct privilege from EITHER Contract-mapping
    # permission above -- deliberately granted to Agent Administrator,
    # not Governance Administrator (Phase 2's own RBAC decision,
    # section 32): the person who can register or rotate an Adapter's
    # credential must not thereby also gain the authority to activate a
    # new governed semantic path (EnforcementBinding activation stays
    # gated on INTEGRATION_CONTRACT_PUBLISH alone). Mirrors exactly how
    # Agent Administrator already manages Agent's own credential
    # lifecycle without holding RUNTIME_POLICY_PUBLISH.
    INTEGRATION_IDENTITY_MANAGE = "integration_identity.manage"


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
            Permission.FACTS_MANAGE,
            Permission.CAPABILITY_ISSUE,
            Permission.CAPABILITY_VERIFY,
            Permission.INTEGRATION_CONTRACT_MANAGE,
            Permission.INTEGRATION_CONTRACT_PUBLISH,
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
            Permission.INTEGRATION_IDENTITY_MANAGE,
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
