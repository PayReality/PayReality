"""Milestone 3 (Enterprise Surface Isolation): verify_chain called its
own module's verify_evidence with a missing required organization_id
argument -- a guaranteed TypeError for any organization with at least
one Evidence record, confirmed in MULTI_TENANT_ARCHITECTURE_
VERIFICATION.md, with zero pre-existing test coverage for this
endpoint. This proves the fix directly: the internal call now passes
organization_id through, and never diverges from the organization_id
the surrounding query already scoped `records` to.

Follows this codebase's established convention (test_organization_
isolation.py) for testing DB-touching functions without a real
database: a minimal fake Session answering scalar/scalars with
pre-wired results. verify_evidence itself is monkeypatched rather than
exercised for real, since its own real behavior (signature
cryptography, signing-key registry lookups) is a separate concern
already covered by its own tests -- this file's only job is to prove
the call site passes the right arguments.
"""

import uuid
from datetime import datetime, timezone

from app.services import evidence_service


class _FakeEvidenceRecord:
    def __init__(self, id, organization_id, payload, created_at):
        self.id = id
        self.organization_id = organization_id
        self.payload = payload
        self.created_at = created_at


class _FakeSession:
    def __init__(self, scalars_results=None, scalar_results=None):
        self._scalars_results = list(scalars_results or [])
        self._scalar_results = list(scalar_results or [])

    def scalars(self, stmt):
        return self._scalars_results.pop(0) if self._scalars_results else []

    def scalar(self, stmt):
        return self._scalar_results.pop(0) if self._scalar_results else None


def test_verify_chain_passes_organization_id_into_verify_evidence(monkeypatch):
    organization_id = uuid.uuid4()
    record = _FakeEvidenceRecord(
        uuid.uuid4(), organization_id, {"payload_version": 2}, datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    db = _FakeSession(scalars_results=[[record]], scalar_results=[None])

    calls = []

    def _fake_verify_evidence(db, evidence_id, organization_id):
        calls.append((evidence_id, organization_id))
        return True, "k1"

    monkeypatch.setattr(evidence_service, "verify_evidence", _fake_verify_evidence)

    result = evidence_service.verify_chain(db, organization_id)

    assert calls == [(record.id, organization_id)]
    assert result.total == 1
    assert result.intact


def test_verify_chain_never_raises_for_a_populated_organization(monkeypatch):
    """The actual crash this fix closes: before it, this call raised
    TypeError for any organization with >=1 Evidence record. No
    exception escaping verify_chain is the whole point of this test."""
    organization_id = uuid.uuid4()
    record = _FakeEvidenceRecord(
        uuid.uuid4(), organization_id, {"payload_version": 2}, datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    db = _FakeSession(scalars_results=[[record]], scalar_results=[None])
    monkeypatch.setattr(evidence_service, "verify_evidence", lambda db, evidence_id, organization_id: (True, "k1"))

    evidence_service.verify_chain(db, organization_id)  # must not raise
