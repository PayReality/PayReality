"""Pure logic, no DB (this codebase's established pattern for the fixed
vocabularies -- see test_scope tests for scope_vocabulary.py, test_compiler_v2
for FinancialVocabulary): encodes Phase 10 (RBAC.md)'s exact can/cannot
lists as assertions, so a future change to ROLE_PERMISSIONS that silently
breaks one of those promises fails a test, not a support ticket."""

from app.domain.rbac.permissions import Permission, Role, has_permission, permissions_for_role


def test_owner_has_every_permission():
    for permission in Permission:
        assert has_permission(Role.OWNER, permission)


def test_governance_admin_cannot_manage_organisation_billing_or_users():
    for forbidden in (
        Permission.ORGANISATION_MANAGE,
        Permission.ORGANISATION_DELETE,
        Permission.USERS_MANAGE,
        Permission.API_KEYS_MANAGE,
    ):
        assert not has_permission(Role.GOVERNANCE_ADMIN, forbidden)


def test_governance_admin_can_author_and_publish_runtime_policy():
    for allowed in (
        Permission.RUNTIME_POLICY_CREATE,
        Permission.RUNTIME_POLICY_EDIT,
        Permission.RUNTIME_POLICY_PUBLISH,
        Permission.RUNTIME_POLICY_VIEW,
        Permission.AUTHORITY_REVIEW,
    ):
        assert has_permission(Role.GOVERNANCE_ADMIN, allowed)


def test_agent_admin_cannot_edit_or_publish_runtime_policy():
    assert not has_permission(Role.AGENT_ADMIN, Permission.RUNTIME_POLICY_EDIT)
    assert not has_permission(Role.AGENT_ADMIN, Permission.RUNTIME_POLICY_PUBLISH)


def test_agent_admin_can_manage_the_full_agent_lifecycle():
    for allowed in (
        Permission.AGENT_REGISTER,
        Permission.AGENT_SUSPEND,
        Permission.AGENT_RETIRE,
        Permission.AGENT_ROTATE,
        Permission.AGENT_ACTIVATE,
        Permission.AGENT_REVOKE,
        Permission.AGENT_MANAGE,
    ):
        assert has_permission(Role.AGENT_ADMIN, allowed)


def test_reviewer_can_review_but_never_publish():
    assert has_permission(Role.REVIEWER, Permission.AUTHORITY_REVIEW)
    assert not has_permission(Role.REVIEWER, Permission.RUNTIME_POLICY_PUBLISH)
    assert not has_permission(Role.REVIEWER, Permission.RUNTIME_POLICY_EDIT)
    assert not has_permission(Role.REVIEWER, Permission.RUNTIME_POLICY_CREATE)


def test_reviewer_can_view_and_resolve_decisions():
    """Added alongside the Pending Review queue (GET /v1/decisions): a
    Reviewer is the role this queue is actually for, so it needs
    decisions.view (to see the queue) and decisions.resolve (to act on
    it) -- previously the Reviewer role had neither, despite its name,
    and could only review Authority Graphs."""
    assert has_permission(Role.REVIEWER, Permission.DECISIONS_VIEW)
    assert has_permission(Role.REVIEWER, Permission.DECISIONS_RESOLVE)


def test_governance_admin_can_manage_facts_and_issue_capabilities():
    """Trusted Enterprise Facts and the Capability Authorization
    Protocol (PAYREALITY_FUTURE_VISION.md Parts A/C): both new,
    deliberately narrow permissions -- neither reuses an existing one,
    since registering a fact source and minting an executable
    authorization are each distinct privileges from anything already
    modeled (see permissions.py's own comments on each)."""
    assert has_permission(Role.GOVERNANCE_ADMIN, Permission.FACTS_MANAGE)
    assert has_permission(Role.GOVERNANCE_ADMIN, Permission.CAPABILITY_ISSUE)


def test_reviewer_cannot_manage_facts_or_issue_capabilities():
    """Neither new permission is granted to Reviewer -- re-attesting
    authority (AUTHORITY_REVIEW) is not the same privilege as
    registering what the org treats as a trusted fact source, or as
    minting an executable capability for a decision."""
    assert not has_permission(Role.REVIEWER, Permission.FACTS_MANAGE)
    assert not has_permission(Role.REVIEWER, Permission.CAPABILITY_ISSUE)


def test_auditor_is_strictly_read_only():
    view_permissions = {
        Permission.EVIDENCE_VIEW,
        Permission.DECISIONS_VIEW,
        Permission.RUNTIME_POLICY_VIEW,
        Permission.AGENT_VIEW,
        Permission.ASSURANCE_VIEW,
    }
    assert set(permissions_for_role(Role.AUDITOR)) == {p.value for p in view_permissions}
    for permission in Permission:
        if permission not in view_permissions:
            assert not has_permission(Role.AUDITOR, permission)


def test_executive_has_only_assurance_view():
    assert permissions_for_role(Role.EXECUTIVE) == [Permission.ASSURANCE_VIEW.value]


def test_unknown_role_has_no_permissions():
    assert not has_permission("not_a_real_role", Permission.EVIDENCE_VIEW)


def test_permissions_for_role_is_sorted_and_stable():
    result = permissions_for_role(Role.OWNER)
    assert result == sorted(result)


def test_governance_admin_can_manage_and_publish_integration_contracts():
    """Trusted Integration Architecture, Phase 1 (Founder Decisions &
    Design Closure Addendum, RBAC decision): two new, deliberately NOT-
    reused permissions -- mapping-semantic governance is a different
    privilege from RuntimePolicy governance, even though today's default
    role holds both."""
    assert has_permission(Role.GOVERNANCE_ADMIN, Permission.INTEGRATION_CONTRACT_MANAGE)
    assert has_permission(Role.GOVERNANCE_ADMIN, Permission.INTEGRATION_CONTRACT_PUBLISH)


def test_integration_contract_permissions_are_not_runtime_policy_publish():
    """The whole point of the founder decision: these are structurally
    independent permissions, not an alias for runtime_policy.publish --
    a future custom role could hold one without the other."""
    assert Permission.INTEGRATION_CONTRACT_PUBLISH != Permission.RUNTIME_POLICY_PUBLISH
    assert Permission.INTEGRATION_CONTRACT_PUBLISH.value == "integration_contract.publish"
    assert Permission.INTEGRATION_CONTRACT_MANAGE.value == "integration_contract.manage"


def test_agent_admin_reviewer_auditor_executive_cannot_manage_integration_contracts():
    for role in (Role.AGENT_ADMIN, Role.REVIEWER, Role.AUDITOR, Role.EXECUTIVE):
        assert not has_permission(role, Permission.INTEGRATION_CONTRACT_MANAGE)
        assert not has_permission(role, Permission.INTEGRATION_CONTRACT_PUBLISH)


def test_agent_admin_manages_integration_identity_but_cannot_publish_bindings():
    """Trusted Integration Architecture, Phase 2's own RBAC decision
    (section 32): registering/rotating an Adapter's credential must not
    automatically grant authority to activate a new governed semantic
    path -- the two permissions are held by different roles by design."""
    assert has_permission(Role.AGENT_ADMIN, Permission.INTEGRATION_IDENTITY_MANAGE)
    assert not has_permission(Role.AGENT_ADMIN, Permission.INTEGRATION_CONTRACT_PUBLISH)
    assert not has_permission(Role.AGENT_ADMIN, Permission.INTEGRATION_CONTRACT_MANAGE)


def test_governance_admin_cannot_manage_integration_identity_credentials():
    """The reverse of the same separation-of-duties invariant: governance
    can approve/activate a Binding but cannot itself register or rotate
    the Adapter credential a Binding points at."""
    assert not has_permission(Role.GOVERNANCE_ADMIN, Permission.INTEGRATION_IDENTITY_MANAGE)
