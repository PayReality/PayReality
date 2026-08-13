"""Milestone 3 (Enterprise Surface Isolation): the Organization Lifecycle
-- create/deactivate/reactivate/archive an Organization, and invite/
accept/revoke membership. Confirmed in MULTI_TENANT_ARCHITECTURE_
VERIFICATION.md: before this milestone, `Organization(...)` was
constructed in exactly one place in the whole codebase (a startup-only
bootstrap hook), and there was no lifecycle status, no invitation flow,
of any kind.

Follows this codebase's established convention for testing DB-touching
service functions without a real database: a minimal fake Session
answering get/scalar with pre-wired results, recording (but not really
persisting) add/flush/commit/refresh calls. create_organization's own
success path (the two-row create-org-and-owner transaction) is NOT
unit-tested here, matching create_agent/create_policy's own precedent in
this codebase: a genuinely multi-row creation transaction is verified
against a live database, not a fake session standing in for one.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services import organization_lifecycle_service as svc

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()


class _FakeSession:
    def __init__(self, get_results=None, scalar_results=None, scalars_results=None):
        self._get_results = dict(get_results or {})
        self._scalar_results = list(scalar_results or [])
        self._scalars_results = list(scalars_results or [])
        self.added = []

    def get(self, model, id):
        return self._get_results.get(str(id))

    def scalar(self, stmt):
        return self._scalar_results.pop(0) if self._scalar_results else None

    def scalars(self, stmt):
        return self._scalars_results.pop(0) if self._scalars_results else []

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass

    def commit(self):
        pass

    def refresh(self, obj):
        pass


class _FakeOrganization:
    def __init__(self, id, status="active"):
        self.id = id
        self.status = status
        self.deactivated_at = None
        self.deactivated_by = None
        self.archived_at = None
        self.archived_by = None


class _FakeInvitation:
    def __init__(self, id, organization_id, status="pending", expires_at=None, email="a@example.com", role="reviewer"):
        self.id = id
        self.organization_id = organization_id
        self.status = status
        self.expires_at = expires_at or (datetime.now(timezone.utc) + timedelta(days=1))
        self.email = email
        self.role = role
        self.accepted_at = None
        self.accepted_by_user_id = None


# --- Organization status transitions --------------------------------------


def test_deactivate_organization_transitions_active_to_deactivated():
    org_id = uuid.uuid4()
    org = _FakeOrganization(org_id, status="active")
    result = svc.deactivate_organization(_FakeSession(get_results={str(org_id): org}), org_id, actor="alice")
    assert result.status == "deactivated"
    assert result.deactivated_by == "alice"
    assert result.deactivated_at is not None


def test_deactivate_organization_rejects_a_non_active_organization():
    org_id = uuid.uuid4()
    org = _FakeOrganization(org_id, status="deactivated")
    with pytest.raises(svc.InvalidOrganizationStatusError):
        svc.deactivate_organization(_FakeSession(get_results={str(org_id): org}), org_id)


def test_reactivate_organization_transitions_deactivated_to_active():
    org_id = uuid.uuid4()
    org = _FakeOrganization(org_id, status="deactivated")
    result = svc.reactivate_organization(_FakeSession(get_results={str(org_id): org}), org_id)
    assert result.status == "active"
    assert result.deactivated_at is None
    assert result.deactivated_by is None


def test_reactivate_organization_rejects_an_active_organization():
    org_id = uuid.uuid4()
    org = _FakeOrganization(org_id, status="active")
    with pytest.raises(svc.InvalidOrganizationStatusError):
        svc.reactivate_organization(_FakeSession(get_results={str(org_id): org}), org_id)


def test_archive_organization_requires_deactivation_first():
    org_id = uuid.uuid4()
    org = _FakeOrganization(org_id, status="active")
    with pytest.raises(svc.InvalidOrganizationStatusError):
        svc.archive_organization(_FakeSession(get_results={str(org_id): org}), org_id)


def test_archive_organization_transitions_deactivated_to_archived():
    org_id = uuid.uuid4()
    org = _FakeOrganization(org_id, status="deactivated")
    result = svc.archive_organization(_FakeSession(get_results={str(org_id): org}), org_id, actor="bob")
    assert result.status == "archived"
    assert result.archived_by == "bob"


def test_get_organization_raises_for_a_missing_organization():
    with pytest.raises(svc.OrganizationNotFoundError):
        svc.get_organization(_FakeSession(), uuid.uuid4())


def test_list_organizations_returns_every_organization():
    """Organization Discovery: deliberately not organization-scoped --
    this is the one function that must see every organization, for the
    Operator Key's own discovery need."""
    db = _FakeSession()
    assert svc.list_organizations(db) == []


# --- Invitations ------------------------------------------------------------


def test_revoke_invitation_rejects_an_invitation_from_a_different_organization():
    invitation_id = uuid.uuid4()
    invitation = _FakeInvitation(invitation_id, ORG_B)
    with pytest.raises(svc.InvitationNotFoundError):
        svc.revoke_invitation(_FakeSession(get_results={str(invitation_id): invitation}), invitation_id, ORG_A)


def test_revoke_invitation_rejects_a_non_pending_invitation():
    invitation_id = uuid.uuid4()
    invitation = _FakeInvitation(invitation_id, ORG_A, status="accepted")
    with pytest.raises(svc.InvitationNotPendingError):
        svc.revoke_invitation(_FakeSession(get_results={str(invitation_id): invitation}), invitation_id, ORG_A)


def test_revoke_invitation_succeeds_for_a_pending_invitation_in_the_right_organization():
    invitation_id = uuid.uuid4()
    invitation = _FakeInvitation(invitation_id, ORG_A, status="pending")
    result = svc.revoke_invitation(_FakeSession(get_results={str(invitation_id): invitation}), invitation_id, ORG_A)
    assert result.status == "revoked"


def test_accept_invitation_rejects_an_unknown_token():
    with pytest.raises(svc.InvitationNotFoundError):
        svc.accept_invitation(_FakeSession(), "bad-token", "Name", "password123")


def test_accept_invitation_rejects_an_already_accepted_invitation():
    invitation = _FakeInvitation(uuid.uuid4(), ORG_A, status="accepted")
    with pytest.raises(svc.InvitationNotPendingError):
        svc.accept_invitation(_FakeSession(scalar_results=[invitation]), "token", "Name", "password123")


def test_accept_invitation_rejects_an_expired_invitation():
    """Membership Validation: expiry is checked, and the row is
    transitioned to 'expired' as a side effect of the check failing --
    a second accept attempt against the same token hits the same
    rejection, not a re-evaluated expiry window."""
    invitation = _FakeInvitation(
        uuid.uuid4(), ORG_A, status="pending", expires_at=datetime.now(timezone.utc) - timedelta(days=1)
    )
    with pytest.raises(svc.InvitationExpiredError):
        svc.accept_invitation(_FakeSession(scalar_results=[invitation]), "token", "Name", "password123")
    assert invitation.status == "expired"


def test_accept_invitation_rejects_when_the_email_is_already_registered():
    invitation = _FakeInvitation(uuid.uuid4(), ORG_A, status="pending", email="taken@example.com")
    db = _FakeSession(scalar_results=[invitation, object()])
    with pytest.raises(svc.EmailAlreadyRegisteredError):
        svc.accept_invitation(db, "token", "Name", "password123")


def test_accept_invitation_creates_a_user_scoped_to_the_invitations_organization():
    invitation = _FakeInvitation(uuid.uuid4(), ORG_A, status="pending", email="new@example.com", role="reviewer")
    db = _FakeSession(scalar_results=[invitation, None])
    user = svc.accept_invitation(db, "token", "New Person", "password123")
    assert user.organization_id == ORG_A
    assert user.email == "new@example.com"
    assert user.role == "reviewer"
    assert invitation.status == "accepted"
    assert invitation.accepted_by_user_id == user.id
