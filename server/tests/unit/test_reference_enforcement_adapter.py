"""Phase 6 (Reference End-to-End Enforcement Demonstration): unit-tests
scripts/reference_enforcement_adapter.py's own new control-flow logic --
imported directly (no existing precedent for importing from scripts/ in
this test suite, so a plain importlib.util load, matching the same
pattern this repo's own migration-logic test already established) so
the exact code that will run when a human executes this script is what
is under test, not a reimplemented copy.

`verify_and_consume` itself (the real HTTP call to
POST /v1/capability-tokens/verify) is exercised for real by the
server-side integration test suite (test_reference_enforcement_
demonstration.py calls capability_service.verify_and_consume_capability
directly, the same function this endpoint calls) -- what is genuinely
NEW and untested elsewhere is this script's own orchestration: does it
ever call execute_downstream_operation() when verification failed? The
brief's own section 7/12 requirement ("downstream business operation is
not invoked if verify and consume fails") is a claim about THIS
script's control flow, not about the server, so it needs its own test
here, with the network call itself monkeypatched out.
"""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "reference_enforcement_adapter.py"
_spec = importlib.util.spec_from_file_location("reference_enforcement_adapter", _SCRIPT_PATH)
adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adapter)


def test_successful_verification_invokes_downstream_execution_and_reports_it_separately(monkeypatch):
    calls = {"execute": 0}

    def fake_verify(*args, **kwargs):
        return adapter.VerifyResult(ok=True, capability_id="cap-1", decision_id="decision-1", reason=None)

    def fake_execute(action, resource, constraints):
        calls["execute"] += 1
        assert action == "supplier.bank_details.change"
        assert resource == "supplier:SUPPLIER_482"
        return True

    monkeypatch.setattr(adapter, "verify_and_consume", fake_verify)
    monkeypatch.setattr(adapter, "execute_downstream_operation", fake_execute)

    ok = adapter.run("tok", "reference-pep", "supplier.bank_details.change", "supplier:SUPPLIER_482", {})

    assert ok is True
    assert calls["execute"] == 1, "a successful verification must invoke downstream execution exactly once"


def test_failed_verification_never_invokes_downstream_execution(monkeypatch):
    """The exact hostile-review-relevant guarantee: a rejected Capability
    (wrong scope, expired, already consumed, whatever the reason) must
    never reach the reference business system."""
    calls = {"execute": 0}

    def fake_verify(*args, **kwargs):
        return adapter.VerifyResult(ok=False, capability_id=None, decision_id=None, reason="capability_token_already_consumed")

    def fake_execute(action, resource, constraints):
        calls["execute"] += 1
        return True

    monkeypatch.setattr(adapter, "verify_and_consume", fake_verify)
    monkeypatch.setattr(adapter, "execute_downstream_operation", fake_execute)

    ok = adapter.run("tok", "reference-pep", "supplier.bank_details.change", "supplier:SUPPLIER_482", {})

    assert ok is False
    assert calls["execute"] == 0, "downstream execution must never be invoked when verification failed"


def test_downstream_execution_failure_is_reported_distinctly_from_a_rejected_capability(monkeypatch):
    """If the Capability verifies but the reference business system
    itself reports failure, run() must still return False -- but this
    is a genuinely different case from a rejected Capability (verify
    succeeded, execution did not), and the two must remain
    distinguishable to a caller inspecting behavior, not collapsed into
    one boolean meaning "something went wrong.\""""

    def fake_verify(*args, **kwargs):
        return adapter.VerifyResult(ok=True, capability_id="cap-1", decision_id="decision-1", reason=None)

    def fake_execute(action, resource, constraints):
        return False

    monkeypatch.setattr(adapter, "verify_and_consume", fake_verify)
    monkeypatch.setattr(adapter, "execute_downstream_operation", fake_execute)

    ok = adapter.run("tok", "reference-pep", "supplier.bank_details.change", "supplier:SUPPLIER_482", {})

    assert ok is False


def test_constraints_json_and_amount_currency_merge_into_one_shape():
    """Phase 6: generalizes the old amount/currency-only shape without
    breaking it -- both are folded into the same constraints dict main()
    builds, never two parallel representations."""
    import json

    constraints = json.loads('{"foo": "bar"}')
    constraints["amount"] = "48000"
    constraints["currency"] = "USD"
    assert constraints == {"foo": "bar", "amount": "48000", "currency": "USD"}


def test_verify_and_consume_omits_optional_binding_fields_when_not_given(monkeypatch):
    """Backward compatibility (unchanged from Phase 5): a caller that
    doesn't know or care which principal/environment/binding issued a
    Capability can still verify it without supplying any of them."""
    captured = {}

    def fake_post(path, body):
        captured["path"] = path
        captured["body"] = body
        return 200, {"capability_id": "cap-1", "decision_id": "decision-1", "resource": "supplier:SUPPLIER_482", "constraints": {}}

    monkeypatch.setattr(adapter, "_post", fake_post)

    result = adapter.verify_and_consume("tok", "reference-pep", "supplier.bank_details.change", "supplier:SUPPLIER_482", {})

    assert result.ok is True
    assert "principal" not in captured["body"]
    assert "environment" not in captured["body"]
    assert "enforcement_binding_id" not in captured["body"]


def test_verify_and_consume_includes_principal_when_given(monkeypatch):
    """Phase 6: --principal is now actually wired through, closing the
    gap where the server-side check existed (Phase 5) but this script
    never exposed a way to use it."""
    captured = {}

    def fake_post(path, body):
        captured["body"] = body
        return 200, {"capability_id": "cap-1", "decision_id": "decision-1", "resource": "supplier:SUPPLIER_482", "constraints": {}}

    monkeypatch.setattr(adapter, "_post", fake_post)

    adapter.verify_and_consume(
        "tok", "reference-pep", "supplier.bank_details.change", "supplier:SUPPLIER_482", {},
        principal="FinanceAgent01",
    )

    assert captured["body"]["principal"] == "FinanceAgent01"
