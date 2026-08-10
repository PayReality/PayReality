import uuid

from app.services.runtime_policy_service import resolve_enterprise_system


class _FakeRuntimePolicyRow:
    def __init__(self, enterprise_system_id=None):
        self.content = {"constraints": {"enterprise_system_id": enterprise_system_id}}


class _FakeSystem:
    def __init__(self, id):
        self.id = id


class _FakeSession:
    """Records nothing; just answers db.scalar(...) and db.get(...) with
    whatever this test wired up. resolve_enterprise_system never inspects
    the statement passed to db.scalar beyond letting SQLAlchemy build it,
    so a fixed return value per call is enough -- the same minimal-fake
    style as FakePolicyStore/FakeOpaClient in test_decision_engine.py."""

    def __init__(self, scalar_results=None, get_results=None):
        self._scalar_results = list(scalar_results or [])
        self._get_results = dict(get_results or {})

    def scalar(self, stmt):
        return self._scalar_results.pop(0) if self._scalar_results else None

    def get(self, model, id):
        return self._get_results.get(str(id))


def test_no_policy_keys_returns_none():
    db = _FakeSession()
    assert resolve_enterprise_system(db, []) is None


def test_non_uuid_policy_key_is_skipped():
    db = _FakeSession()
    assert resolve_enterprise_system(db, ["not-a-uuid"]) is None


def test_policy_key_with_no_matching_active_row_is_skipped():
    db = _FakeSession(scalar_results=[None])
    assert resolve_enterprise_system(db, [str(uuid.uuid4())]) is None


def test_matched_policy_with_no_configured_enterprise_system_is_skipped():
    db = _FakeSession(scalar_results=[_FakeRuntimePolicyRow(enterprise_system_id=None)])
    assert resolve_enterprise_system(db, [str(uuid.uuid4())]) is None


def test_configured_enterprise_system_that_no_longer_exists_is_skipped():
    configured_id = str(uuid.uuid4())
    db = _FakeSession(
        scalar_results=[_FakeRuntimePolicyRow(enterprise_system_id=configured_id)],
        get_results={},
    )
    assert resolve_enterprise_system(db, [str(uuid.uuid4())]) is None


def test_matched_policy_with_real_enterprise_system_is_returned():
    system_id = uuid.uuid4()
    system = _FakeSystem(id=system_id)
    db = _FakeSession(
        scalar_results=[_FakeRuntimePolicyRow(enterprise_system_id=str(system_id))],
        get_results={str(system_id): system},
    )
    result = resolve_enterprise_system(db, [str(uuid.uuid4())])
    assert result is system


def test_first_matching_policy_key_wins_deterministically():
    """Mirrors resolve_mandate_ids' own tie-break convention: policy_keys
    is evaluate()'s own evaluated_mandates order, and the first key that
    both matches an active row AND resolves to a real EnterpriseSystem
    wins -- not the last, and not every match collected."""
    system_id = uuid.uuid4()
    system = _FakeSystem(id=system_id)
    db = _FakeSession(
        scalar_results=[
            _FakeRuntimePolicyRow(enterprise_system_id=None),
            _FakeRuntimePolicyRow(enterprise_system_id=str(system_id)),
        ],
        get_results={str(system_id): system},
    )
    result = resolve_enterprise_system(db, [str(uuid.uuid4()), str(uuid.uuid4())])
    assert result is system
