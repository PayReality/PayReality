"""Integration Kit v1: `verify_capability()` translates the server's
exact `detail` string into a specific typed exception rather than a bare
`ApiError`/`AuthenticationError`. These tests go through the REAL
`HttpClient` (via `fake_session`, exactly like test_client.py's own
convention) rather than `FakeHttpClient`, so the real
`_raise_for_response` mapping runs first and this module's translation
layer is proven against genuine `ApiError`/`AuthenticationError`
instances, not hand-constructed ones.
"""

import pytest

from payreality import Agent
from payreality.client import HttpClient
from payreality.configuration import Configuration
from payreality.exceptions import (
    CapabilityAlreadyConsumedError,
    CapabilityAudienceMismatchError,
    CapabilityBindingMismatchError,
    CapabilityConstraintMismatchError,
    CapabilityNotFoundError,
    CapabilityTenantMismatchError,
    CapabilityTokenExpiredError,
    CapabilityTrustNotActiveError,
    InvalidCapabilityTokenError,
)


def _agent_with_fake_session(credentials_path, fake_session):
    agent = Agent(bearer_token="scoped-api-key", credentials_path=credentials_path)
    agent._client = HttpClient(Configuration(bearer_token="scoped-api-key"), session=fake_session)
    return agent


def _verify(agent):
    return agent.verify_capability("tok-abc", "reference-adapter", "vendor_payment", "supplier:123", {})


@pytest.mark.parametrize(
    "status_code,detail,expected_exc",
    [
        (401, "capability_token_expired", CapabilityTokenExpiredError),
        (401, "invalid_capability_token", InvalidCapabilityTokenError),
        (403, "capability_tenant_mismatch", CapabilityTenantMismatchError),
        (403, "capability_audience_mismatch", CapabilityAudienceMismatchError),
        (404, "capability_token_not_found", CapabilityNotFoundError),
        (409, "capability_constraint_mismatch", CapabilityConstraintMismatchError),
        (409, "capability_binding_mismatch", CapabilityBindingMismatchError),
        (409, "capability_token_already_consumed", CapabilityAlreadyConsumedError),
        (409, "origin_agent_not_active: agent agt_1 is not active", CapabilityTrustNotActiveError),
        (409, "integration_identity_not_active: identity ii_1 is not active", CapabilityTrustNotActiveError),
        (409, "enforcement_binding_not_active: binding eb_1 is not active", CapabilityTrustNotActiveError),
        (409, "tenant_not_active: organization org_1 is not active", CapabilityTrustNotActiveError),
    ],
)
def test_verify_capability_translates_each_known_detail(credentials_path, fake_session, status_code, detail, expected_exc):
    fake_session.queue_response(status_code, {"detail": detail})
    agent = _agent_with_fake_session(credentials_path, fake_session)

    with pytest.raises(expected_exc):
        _verify(agent)


def test_translated_exception_preserves_status_code(credentials_path, fake_session):
    fake_session.queue_response(409, {"detail": "capability_token_already_consumed"})
    agent = _agent_with_fake_session(credentials_path, fake_session)

    with pytest.raises(CapabilityAlreadyConsumedError) as excinfo:
        _verify(agent)
    assert excinfo.value.status_code == 409


def test_unrecognized_detail_falls_back_to_the_original_generic_exception(credentials_path, fake_session):
    """A detail string this table doesn't know about must never be
    silently swallowed or miscategorized -- it re-raises the original,
    generic exception unchanged, exactly as verify_capability always
    behaved before Integration Kit v1."""
    from payreality.exceptions import ApiError

    fake_session.queue_response(400, {"detail": "malformed_request"})
    agent = _agent_with_fake_session(credentials_path, fake_session)

    with pytest.raises(ApiError) as excinfo:
        _verify(agent)
    assert not isinstance(excinfo.value, CapabilityAlreadyConsumedError)
    assert excinfo.value.status_code == 400


def test_backward_compatible_generic_catch_still_works(credentials_path, fake_session):
    """Existing calling code that only ever caught the generic bases
    (AuthenticationError/ApiError) must keep working unchanged -- every
    new typed exception subclasses one of them."""
    from payreality.exceptions import AuthenticationError

    fake_session.queue_response(403, {"detail": "capability_audience_mismatch"})
    agent = _agent_with_fake_session(credentials_path, fake_session)

    with pytest.raises(AuthenticationError):
        _verify(agent)
