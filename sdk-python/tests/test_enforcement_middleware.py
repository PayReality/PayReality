"""Integration Kit v1, Part C: tests for `CapabilityEnforcer`. Uses the
real `HttpClient` + `fake_session` (like test_capability_error_translation.py)
so a rejected verification genuinely goes through the real status/detail
-> typed-exception translation this milestone added to
`Agent.verify_capability()`, proving `CapabilityEnforcer`'s OWN dispatch
logic (call downstream only on success, never otherwise) against real
exception types -- not a re-proof of server-side verification itself,
which Phase 6.1's own test suite already covers.
"""

import pytest

from payreality import Agent
from payreality.client import HttpClient
from payreality.configuration import Configuration
from payreality.enforcement import CapabilityEnforcer
from payreality.exceptions import (
    CapabilityAlreadyConsumedError,
    CapabilityAudienceMismatchError,
    CapabilityBindingMismatchError,
    CapabilityConstraintMismatchError,
    CapabilityTenantMismatchError,
    CapabilityTokenExpiredError,
)


def _enforcer(credentials_path, fake_session, **kwargs):
    agent = Agent(bearer_token="scoped-api-key", credentials_path=credentials_path)
    agent._client = HttpClient(Configuration(bearer_token="scoped-api-key"), session=fake_session)
    return CapabilityEnforcer(agent=agent, audience="reference-pep", **kwargs)


def test_enforce_calls_downstream_exactly_once_after_successful_verification(credentials_path, fake_session):
    fake_session.queue_response(
        200, {"capability_id": "cap-1", "decision_id": "dec-1", "resource": "supplier:1", "constraints": {}}
    )
    enforcer = _enforcer(credentials_path, fake_session)
    calls = []

    def downstream(consumed):
        calls.append(consumed)
        return "downstream-result"

    result = enforcer.enforce(
        "tok-abc", action="supplier_bank_details_change", resource="supplier:1", constraints={}, downstream=downstream,
    )

    assert result == "downstream-result"
    assert len(calls) == 1
    assert calls[0].capability_id == "cap-1"
    assert calls[0].decision_id == "dec-1"


def test_downstream_return_value_is_never_conflated_with_capability_state(credentials_path, fake_session):
    """A falsy or exception-raising downstream result must not be
    mistaken for a verification failure -- these are two separate facts,
    per this module's own docstring."""
    fake_session.queue_response(
        200, {"capability_id": "cap-1", "decision_id": "dec-1", "resource": "supplier:1", "constraints": {}}
    )
    enforcer = _enforcer(credentials_path, fake_session)

    result = enforcer.enforce(
        "tok-abc", action="a", resource="r", constraints={}, downstream=lambda consumed: False,
    )
    assert result is False  # downstream's own falsy result, not treated as a failure signal


@pytest.mark.parametrize(
    "status_code,detail,expected_exc",
    [
        (409, "capability_token_already_consumed", CapabilityAlreadyConsumedError),
        (403, "capability_tenant_mismatch", CapabilityTenantMismatchError),
        (403, "capability_audience_mismatch", CapabilityAudienceMismatchError),
        (409, "capability_constraint_mismatch", CapabilityConstraintMismatchError),  # wrong action or resource
        (409, "capability_binding_mismatch", CapabilityBindingMismatchError),  # wrong environment or binding
        (401, "capability_token_expired", CapabilityTokenExpiredError),
    ],
)
def test_enforce_never_calls_downstream_on_any_rejection(credentials_path, fake_session, status_code, detail, expected_exc):
    fake_session.queue_response(status_code, {"detail": detail})
    enforcer = _enforcer(credentials_path, fake_session)
    downstream_calls = []

    with pytest.raises(expected_exc):
        enforcer.enforce(
            "tok-abc", action="a", resource="r", constraints={},
            downstream=lambda consumed: downstream_calls.append(consumed),
        )

    assert downstream_calls == []


def test_enforce_passes_configured_environment_and_binding(credentials_path, fake_session):
    fake_session.queue_response(
        200, {"capability_id": "cap-1", "decision_id": "dec-1", "resource": "supplier:1", "constraints": {}}
    )
    enforcer = _enforcer(credentials_path, fake_session, environment="production", enforcement_binding_id="binding-1")

    enforcer.enforce("tok-abc", action="a", resource="r", constraints={}, downstream=lambda c: None)

    import json
    sent_body = json.loads(fake_session.calls[-1]["data"])
    assert sent_body["environment"] == "production"
    assert sent_body["enforcement_binding_id"] == "binding-1"


def test_verify_alone_does_not_call_any_downstream(credentials_path, fake_session):
    """`verify()` is the lower-level primitive `enforce()` is built on --
    it never calls anything downstream itself, for a caller who wants to
    decide separately."""
    fake_session.queue_response(
        200, {"capability_id": "cap-1", "decision_id": "dec-1", "resource": "supplier:1", "constraints": {}}
    )
    enforcer = _enforcer(credentials_path, fake_session)

    consumed = enforcer.verify("tok-abc", action="a", resource="r", constraints={})
    assert consumed.capability_id == "cap-1"


def test_wrap_decorator_form_behaves_identically_to_enforce(credentials_path, fake_session):
    fake_session.queue_response(
        200, {"capability_id": "cap-1", "decision_id": "dec-1", "resource": "supplier:1", "constraints": {}}
    )
    enforcer = _enforcer(credentials_path, fake_session)
    calls = []
    wrapped = enforcer.wrap(lambda consumed: calls.append(consumed) or "ok")

    result = wrapped("tok-abc", action="a", resource="r", constraints={})

    assert result == "ok"
    assert len(calls) == 1


def test_wrap_never_calls_the_wrapped_handler_on_rejection(credentials_path, fake_session):
    fake_session.queue_response(409, {"detail": "capability_token_already_consumed"})
    enforcer = _enforcer(credentials_path, fake_session)
    calls = []
    wrapped = enforcer.wrap(lambda consumed: calls.append(consumed))

    with pytest.raises(CapabilityAlreadyConsumedError):
        wrapped("tok-abc", action="a", resource="r", constraints={})

    assert calls == []
