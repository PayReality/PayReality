"""Post-audit implementation, Priority 4: the executable contract every
conforming `EnforcementAdapter` (payreality.enforcement.EnforcementAdapter)
must satisfy. Parametrized over `_ADAPTER_FACTORIES` so a future adapter
(Microsoft's toolkit, Envoy, a customer gateway) proves conformance by
adding one factory entry here, not by re-deriving these assertions from
scratch. Today there is exactly one real, shipping implementation --
`CapabilityEnforcer` -- so that is exactly what runs against this
contract; the list is written to grow, not to pretend a second
implementation already exists.

Uses the same real `HttpClient` + `FakeSession` convention as
test_enforcement_middleware.py (this repository's own established way of
exercising the real status/detail -> typed-exception translation without
touching the network), so a rejection here goes through the real
translation path, not a re-implementation of it.
"""

import pytest

from payreality import Agent
from payreality.client import HttpClient
from payreality.configuration import Configuration
from payreality.enforcement import CapabilityEnforcer, EnforcementAdapter
from payreality.exceptions import CapabilityAlreadyConsumedError


def _capability_enforcer_factory(credentials_path, fake_session):
    agent = Agent(bearer_token="scoped-api-key", credentials_path=credentials_path)
    agent._client = HttpClient(Configuration(bearer_token="scoped-api-key"), session=fake_session)
    return CapabilityEnforcer(agent=agent, audience="reference-pep")


# Every entry here is an (name, factory) pair. `factory(credentials_path,
# fake_session)` must return a fresh adapter wired to that fake_session.
_ADAPTER_FACTORIES = [
    ("CapabilityEnforcer", _capability_enforcer_factory),
]


@pytest.fixture(params=_ADAPTER_FACTORIES, ids=[name for name, _ in _ADAPTER_FACTORIES])
def adapter_factory(request):
    return request.param[1]


def test_adapter_is_a_structural_match_for_the_protocol(credentials_path, fake_session, adapter_factory):
    adapter = adapter_factory(credentials_path, fake_session)
    assert isinstance(adapter, EnforcementAdapter), (
        "a conforming adapter must structurally match verify()/enforce() -- Protocol, not inheritance"
    )


def test_1_valid_capability_succeeds_once(credentials_path, fake_session, adapter_factory):
    fake_session.queue_response(
        200, {"capability_id": "cap-1", "decision_id": "dec-1", "resource": "supplier:1", "constraints": {}}
    )
    adapter = adapter_factory(credentials_path, fake_session)
    calls = []

    result = adapter.enforce(
        "tok-abc", action="a", resource="supplier:1", constraints={},
        downstream=lambda consumed: calls.append(consumed) or "ok",
    )

    assert result == "ok"
    assert len(calls) == 1
    assert calls[0].capability_id == "cap-1"


def test_2_replay_fails(credentials_path, fake_session, adapter_factory):
    fake_session.queue_response(409, {"detail": "capability_token_already_consumed"})
    adapter = adapter_factory(credentials_path, fake_session)

    with pytest.raises(CapabilityAlreadyConsumedError):
        adapter.verify("tok-already-consumed", action="a", resource="r", constraints={})


def test_3_expired_capability_fails(credentials_path, fake_session, adapter_factory):
    from payreality.exceptions import CapabilityTokenExpiredError

    fake_session.queue_response(401, {"detail": "capability_token_expired"})
    adapter = adapter_factory(credentials_path, fake_session)

    with pytest.raises(CapabilityTokenExpiredError):
        adapter.verify("tok-expired", action="a", resource="r", constraints={})


def test_4_wrong_audience_fails(credentials_path, fake_session, adapter_factory):
    from payreality.exceptions import CapabilityAudienceMismatchError

    fake_session.queue_response(403, {"detail": "capability_audience_mismatch"})
    adapter = adapter_factory(credentials_path, fake_session)

    with pytest.raises(CapabilityAudienceMismatchError):
        adapter.verify("tok-wrong-audience", action="a", resource="r", constraints={})


def test_5_wrong_tenant_fails(credentials_path, fake_session, adapter_factory):
    from payreality.exceptions import CapabilityTenantMismatchError

    fake_session.queue_response(403, {"detail": "capability_tenant_mismatch"})
    adapter = adapter_factory(credentials_path, fake_session)

    with pytest.raises(CapabilityTenantMismatchError):
        adapter.verify("tok-wrong-tenant", action="a", resource="r", constraints={})


def test_6_wrong_action_fails(credentials_path, fake_session, adapter_factory):
    """The server's own capability_constraint_mismatch covers a wrong
    action OR resource generically -- both are "the exact-action binding
    doesn't match", the same real HTTP outcome, not two separate codes."""
    from payreality.exceptions import CapabilityConstraintMismatchError

    fake_session.queue_response(409, {"detail": "capability_constraint_mismatch"})
    adapter = adapter_factory(credentials_path, fake_session)

    with pytest.raises(CapabilityConstraintMismatchError):
        adapter.verify("tok-abc", action="a_different_action", resource="r", constraints={})


def test_7_modified_material_parameter_fails(credentials_path, fake_session, adapter_factory):
    from payreality.exceptions import CapabilityConstraintMismatchError

    fake_session.queue_response(409, {"detail": "capability_constraint_mismatch"})
    adapter = adapter_factory(credentials_path, fake_session)

    with pytest.raises(CapabilityConstraintMismatchError):
        adapter.verify("tok-abc", action="a", resource="r", constraints={"amount": "999999"})


def test_8_downstream_is_never_called_after_verification_failure(credentials_path, fake_session, adapter_factory):
    fake_session.queue_response(409, {"detail": "capability_token_already_consumed"})
    adapter = adapter_factory(credentials_path, fake_session)
    calls = []

    with pytest.raises(CapabilityAlreadyConsumedError):
        adapter.enforce(
            "tok-abc", action="a", resource="r", constraints={},
            downstream=lambda consumed: calls.append(consumed),
        )

    assert calls == [], "downstream must never run when verification failed"


def test_9_downstream_exception_propagates_and_does_not_get_swallowed(credentials_path, fake_session, adapter_factory):
    """Post-audit implementation, Priority 4: verification/consumption
    already succeeded by the time downstream runs -- if downstream then
    raises, that exception must propagate unchanged, exactly as if the
    caller had called downstream() directly. enforce() does not catch it,
    wrap it, or convert it into a different signal; the Capability's own
    consumed state (server-side) is unaffected either way, since
    consumption already completed before downstream was ever invoked --
    see this module's own "Atomicity" docstring note."""
    fake_session.queue_response(
        200, {"capability_id": "cap-1", "decision_id": "dec-1", "resource": "r", "constraints": {}}
    )
    adapter = adapter_factory(credentials_path, fake_session)

    class DownstreamFailure(RuntimeError):
        pass

    def failing_downstream(consumed):
        raise DownstreamFailure("the destination system rejected the operation")

    with pytest.raises(DownstreamFailure):
        adapter.enforce("tok-abc", action="a", resource="r", constraints={}, downstream=failing_downstream)


def test_correlation_identifier_threading_is_the_callers_responsibility(credentials_path, fake_session, adapter_factory):
    """Requirement 9 of the contract (preserve an external operation/
    correlation identifier) is satisfied by the caller's own downstream
    closure, not by a second identifier scheme this contract invents --
    proved here by threading one through and confirming it survives
    unmodified into the downstream call."""
    fake_session.queue_response(
        200, {"capability_id": "cap-1", "decision_id": "dec-1", "resource": "r", "constraints": {}}
    )
    adapter = adapter_factory(credentials_path, fake_session)
    correlation_id = "corr-12345"
    received = []

    adapter.enforce(
        "tok-abc", action="a", resource="r", constraints={},
        downstream=lambda consumed: received.append((correlation_id, consumed.capability_id)),
    )

    assert received == [(correlation_id, "cap-1")]
