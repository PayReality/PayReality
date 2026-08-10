"""Runtime Governance Architecture, Phase 4
(36_PHASE_4_CONTEXT_INTELLIGENCE_SPEC.md): _build_evidence_payload is a
pure function (no DB), so its conditional-field behavior is directly
unit-testable without any fixture -- the same reasoning already applied
to decision_engine.evaluate() and runtime_truth_service.ResolvedFacts."""

from uuid import uuid4

from app.services.intent_service import _build_evidence_payload


def _base_kwargs():
    return dict(
        decision_id=uuid4(),
        agent_id=uuid4(),
        action="wire_transfer",
        amount=1000.0,
        matched_mandates=[],
        outcome="ALLOW",
        approval_outcome=None,
        risk_classification="LOW",
        approver=None,
        previous_hash=None,
    )


def test_principal_name_present_when_given():
    payload = _build_evidence_payload(**_base_kwargs(), principal_name="David Okonkwo")
    assert payload["principal_name"] == "David Okonkwo"


def test_principal_name_absent_when_not_resolved():
    """Mirrors principal_id's own omission for the two intent_service
    branches (suspended agent, unrecognized action) where OPA is never
    queried and no Principal is ever resolved."""
    payload = _build_evidence_payload(**_base_kwargs())
    assert "principal_name" not in payload
