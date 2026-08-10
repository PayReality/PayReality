import pytest

from app.domain.decision.engine import (
    DECISION_ENGINE_VERSION,
    ActivePolicy,
    NoActivePolicyError,
    OPAEvaluationError,
    OPATimeoutError,
    evaluate,
)


class FakePolicyStore:
    def __init__(self, active: ActivePolicy | None):
        self._active = active

    def get_active(self) -> ActivePolicy:
        if self._active is None:
            raise NoActivePolicyError()
        return self._active


class FakeOpaClient:
    def __init__(self, result=None, raises=None):
        self._result = result
        self._raises = raises

    def query(self, input_doc, timeout_ms):
        if self._raises:
            raise self._raises
        return self._result


ACTIVE = ActivePolicy(id="pol_1", version=3, bundle_hash="sha256:abc123")
INTENT = {"action": "vendor_payment", "amount": 42000}
CONTEXT = {"environment": "production"}


def test_no_active_policy_resolves_to_human_review():
    decision = evaluate(
        INTENT, CONTEXT, "prin_1", FakePolicyStore(None), FakeOpaClient()
    )
    assert decision.outcome == "HUMAN_REVIEW"
    assert decision.reason == "no_active_policy"


def test_opa_timeout_resolves_to_human_review():
    client = FakeOpaClient(raises=OPATimeoutError())
    decision = evaluate(INTENT, CONTEXT, "prin_1", FakePolicyStore(ACTIVE), client)
    assert decision.outcome == "HUMAN_REVIEW"
    assert decision.reason == "opa_timeout"
    assert decision.policy_id == "pol_1"


def test_opa_evaluation_error_resolves_to_human_review_with_code():
    client = FakeOpaClient(raises=OPAEvaluationError(code="connection_error"))
    decision = evaluate(INTENT, CONTEXT, "prin_1", FakePolicyStore(ACTIVE), client)
    assert decision.outcome == "HUMAN_REVIEW"
    assert decision.reason == "opa_error:connection_error"


def test_requires_review_true_resolves_to_human_review():
    client = FakeOpaClient(
        result={
            "requires_review": True,
            "review_reason": "dual_control_band",
            "evaluated_mandates": ["mand_1"],
        }
    )
    decision = evaluate(INTENT, CONTEXT, "prin_1", FakePolicyStore(ACTIVE), client)
    assert decision.outcome == "HUMAN_REVIEW"
    assert decision.reason == "dual_control_band"
    assert decision.evaluated_mandates == ["mand_1"]


def test_allow_true_and_deny_not_true_resolves_to_allow():
    client = FakeOpaClient(result={"allow": True, "deny": False, "evaluated_mandates": ["mand_1"]})
    decision = evaluate(INTENT, CONTEXT, "prin_1", FakePolicyStore(ACTIVE), client)
    assert decision.outcome == "ALLOW"
    assert decision.evaluated_mandates == ["mand_1"]


def test_deny_true_resolves_to_deny():
    client = FakeOpaClient(result={"deny": True, "deny_reason": "over_limit"})
    decision = evaluate(INTENT, CONTEXT, "prin_1", FakePolicyStore(ACTIVE), client)
    assert decision.outcome == "DENY"
    assert decision.reason == "over_limit"


def test_allow_and_deny_both_true_resolves_to_deny_not_allow():
    """Precedence check: a contradictory bundle (a regression Static Policy
    Validation, spec 12.4 Stage 7, is meant to catch before activation) must
    never resolve to ALLOW just because allow happens to be true."""
    client = FakeOpaClient(result={"allow": True, "deny": True, "deny_reason": "conflict"})
    decision = evaluate(INTENT, CONTEXT, "prin_1", FakePolicyStore(ACTIVE), client)
    assert decision.outcome == "DENY"


def test_ambiguous_result_resolves_to_human_review():
    """Neither allow nor deny nor requires_review set; fail closed."""
    client = FakeOpaClient(result={})
    decision = evaluate(INTENT, CONTEXT, "prin_1", FakePolicyStore(ACTIVE), client)
    assert decision.outcome == "HUMAN_REVIEW"
    assert decision.reason == "undetermined"


@pytest.mark.parametrize("bad_result", [{"allow": False}, {"deny": False}, {"allow": None}])
def test_various_non_committal_results_resolve_to_human_review(bad_result):
    client = FakeOpaClient(result=bad_result)
    decision = evaluate(INTENT, CONTEXT, "prin_1", FakePolicyStore(ACTIVE), client)
    assert decision.outcome == "HUMAN_REVIEW"


# Runtime Governance Architecture, Phase 1 (24_PHASE_1_RUNTIME_CORE_PLAN.md):
# every Decision that actually consulted a policy pins policy_version and
# policy_bundle_hash explicitly, and every Decision carries the evaluating
# engine's own authority_version, regardless of outcome.


def test_no_active_policy_leaves_policy_version_and_hash_unset():
    """The one branch that never reads a policy at all -- no active_policy
    exists to pin a version or hash from, so both stay honestly None
    rather than a fabricated value. authority_version is still set: the
    engine itself still evaluated (and decided there was nothing to
    evaluate against), regardless of whether a policy was found."""
    decision = evaluate(INTENT, CONTEXT, "prin_1", FakePolicyStore(None), FakeOpaClient())
    assert decision.policy_version is None
    assert decision.policy_bundle_hash is None
    assert decision.authority_version == DECISION_ENGINE_VERSION


def test_allow_pins_policy_version_hash_and_authority_version():
    client = FakeOpaClient(result={"allow": True, "deny": False, "evaluated_mandates": []})
    decision = evaluate(INTENT, CONTEXT, "prin_1", FakePolicyStore(ACTIVE), client)
    assert decision.outcome == "ALLOW"
    assert decision.policy_version == 3
    assert decision.policy_bundle_hash == "sha256:abc123"
    assert decision.authority_version == DECISION_ENGINE_VERSION


def test_deny_pins_policy_version_hash_and_authority_version():
    client = FakeOpaClient(result={"deny": True, "deny_reason": "over_limit"})
    decision = evaluate(INTENT, CONTEXT, "prin_1", FakePolicyStore(ACTIVE), client)
    assert decision.outcome == "DENY"
    assert decision.policy_version == 3
    assert decision.policy_bundle_hash == "sha256:abc123"
    assert decision.authority_version == DECISION_ENGINE_VERSION


def test_human_review_pins_policy_version_hash_and_authority_version():
    client = FakeOpaClient(
        result={"requires_review": True, "review_reason": "dual_control_band"}
    )
    decision = evaluate(INTENT, CONTEXT, "prin_1", FakePolicyStore(ACTIVE), client)
    assert decision.outcome == "HUMAN_REVIEW"
    assert decision.policy_version == 3
    assert decision.policy_bundle_hash == "sha256:abc123"
    assert decision.authority_version == DECISION_ENGINE_VERSION


def test_opa_timeout_still_pins_policy_version_and_hash():
    """The policy was successfully resolved before OPA timed out -- the
    version/hash of what *would have been* evaluated is still known and
    still worth recording, distinct from the no_active_policy case where
    nothing was ever resolved at all."""
    client = FakeOpaClient(raises=OPATimeoutError())
    decision = evaluate(INTENT, CONTEXT, "prin_1", FakePolicyStore(ACTIVE), client)
    assert decision.policy_version == 3
    assert decision.policy_bundle_hash == "sha256:abc123"
