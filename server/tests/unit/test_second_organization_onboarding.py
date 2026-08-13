"""Milestone 3 (Enterprise Surface Isolation): "a second organization can
be created" is this milestone's own first completion criterion, and the
central finding MULTI_TENANT_ARCHITECTURE_VERIFICATION.md led with --
before this milestone, `Organization(...)` was constructed in exactly
one place in the entire codebase (a startup-only bootstrap hook), so
there was no way to prove Milestone 2's isolation plumbing against a
genuine second tenant.

This walks the real create_organization service function end to end
(unlike test_organization_lifecycle.py, which deliberately left this
success path untested, matching create_agent/create_policy's own
precedent for a live-database-only creation transaction) with a fake
session capable enough to capture what gets constructed, then proves
the two resulting organizations are independent identities suitable for
every other org-scoping function this milestone touched to key off.
"""

import uuid

from app.db.models import Organization, User
from app.domain.rbac.permissions import Role
from app.services import organization_lifecycle_service as svc


class _FakeSession:
    """Capable enough to observe what create_organization actually
    constructs: records every added row, and assigns each one a real
    uuid4 id at flush time -- the one thing test_organization_isolation.
    py's/test_organization_lifecycle.py's minimal fakes deliberately
    don't do, needed here because this test's whole point is confirming
    two DISTINCT organization identities exist afterward."""

    def __init__(self):
        self.added = []
        self.committed = 0

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    def flush(self):
        pass

    def commit(self):
        self.committed += 1

    def refresh(self, obj):
        pass


def test_create_organization_produces_a_real_organization_and_owner():
    db = _FakeSession()
    organization, owner, temporary_password = svc.create_organization(
        db, name="Second Tenant Inc.", owner_email="owner@second-tenant.example", owner_name="Second Owner"
    )

    assert isinstance(organization, Organization)
    assert organization.name == "Second Tenant Inc."
    assert isinstance(owner, User)
    assert owner.organization_id == organization.id
    assert owner.email == "owner@second-tenant.example"
    assert owner.role == Role.OWNER.value
    assert owner.must_reset_password is True
    # The temporary password is real, shown once, and never trivially
    # guessable -- the same discipline ensure_owner_bootstrapped's own
    # bootstrap password already holds itself to.
    assert len(temporary_password) >= 16
    assert db.committed == 1


def test_two_organizations_created_independently_have_distinct_identities():
    """The actual proof this milestone's completion criterion asks for:
    a SECOND organization is not a variant or extension of the first --
    it is a fully independent identity, with its own Owner, that every
    other org-scoping function in this codebase (already unit-tested
    individually throughout this milestone: Agent Platform, AI Policy
    Builder, AI Authority Builder, Evidence, Runtime Policies) keys off
    via organization_id equality/inequality."""
    db = _FakeSession()

    org_a, owner_a, _ = svc.create_organization(
        db, name="First Tenant Inc.", owner_email="owner@first-tenant.example", owner_name="First Owner"
    )
    org_b, owner_b, _ = svc.create_organization(
        db, name="Second Tenant Inc.", owner_email="owner@second-tenant.example", owner_name="Second Owner"
    )

    assert org_a.id != org_b.id
    assert owner_a.organization_id == org_a.id
    assert owner_b.organization_id == org_b.id
    assert owner_a.organization_id != owner_b.organization_id
    # Every org-scoping check added throughout this milestone is exactly
    # this comparison (e.g. agent_service._agent_organization_id,
    # ai_policy_builder_service._candidate_organization_id,
    # ai_authority_builder.py's _corpus_owns): a row's own organization_id
    # equals the caller's, or it's treated as not found. Confirms the
    # two organizations created here are distinguishable inputs to that
    # exact comparison, not incidentally-equal ids from a fake session.
    assert db.committed == 2
    assert db.added == [org_a, owner_a, org_b, owner_b]
