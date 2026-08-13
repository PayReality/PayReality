"""Milestone 3 (Enterprise Surface Isolation): ensure_owner_bootstrapped
used to resolve "the organization" via `order_by(created_at).limit(1)`
-- "whichever organization happens to be oldest" -- and re-checked
whether THAT org had an Owner on every single boot. Confirmed as the one
remaining "first organization" assumption in the codebase by this
milestone's own audit (MULTI_TENANT_ARCHITECTURE_VERIFICATION.md; the
other one, dependencies.get_current_organization's Operator Key default,
was already fixed in Milestone 2). Now: bootstrap only when ZERO
organizations exist anywhere; once any exist, do nothing, ever again.
"""

from app.services import organization_service


class _FakeSession:
    def __init__(self, scalar_results=None):
        self._scalar_results = list(scalar_results or [])
        self.added = []
        self.committed = 0

    def scalar(self, stmt):
        return self._scalar_results.pop(0) if self._scalar_results else None

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass

    def commit(self):
        self.committed += 1


def test_bootstraps_an_organization_and_owner_when_none_exist():
    db = _FakeSession(scalar_results=[None])
    organization_service.ensure_owner_bootstrapped(db)
    assert len(db.added) == 2  # the Organization, then its Owner
    assert db.committed == 1


def test_does_nothing_when_any_organization_already_exists():
    """The fix itself: previously, this re-checked "does the oldest org
    have an owner" on every boot regardless of how many organizations
    existed. Now it short-circuits the moment any organization is
    found -- never inspecting, or assuming anything about, which one is
    "first"."""
    db = _FakeSession(scalar_results=["some-organization-id"])
    organization_service.ensure_owner_bootstrapped(db)
    assert db.added == []
    assert db.committed == 0
