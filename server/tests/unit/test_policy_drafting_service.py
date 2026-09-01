"""Product Experience V3.2, Part C ("Draft with AI"): the central
invariant under test throughout this file is section 31's own -- AI
interprets and proposes, humans establish authority. Every test either
confirms a valid proposal is correctly validated against real
organisation entities, or confirms an invalid/ambiguous/unverifiable one
is refused rather than silently accepted.

A fake AIProvider (matching this codebase's own FakeAuthorityGraphExtractionProvider/
FakeRuntimePolicyExtractionProvider precedent) stands in for the real
model -- these tests are about this module's own validation logic, not
about model quality, so a deterministic, injectable fake is the correct
tool, never a real API call.
"""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.db.models import Agent, Base, Organization, Principal
from app.services import policy_drafting_service as svc


@compiles(PG_JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(element, compiler, **kw):
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _uuid_as_char_on_sqlite(element, compiler, **kw):
    return "CHAR(36)"


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def org_with_principal(db):
    org = Organization(id=uuid.uuid4(), name="Org A")
    db.add(org)
    db.flush()
    principal = Principal(id=uuid.uuid4(), name="CFO", organization_id=org.id)
    db.add(principal)
    agent = Agent(id=uuid.uuid4(), name="AP-Invoice-Agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    return org, principal, agent


class FakeProvider:
    """Implements the same AIProvider.generate_structured() shape a real
    provider does, returning a fixed, injectable dict per call."""

    def __init__(self, response: dict):
        self._response = response

    def generate_structured(self, **kwargs):
        return self._response


def _valid_proposal(principal="CFO", action="vendor_payment", agent=None):
    return {
        "proposal": {
            "name": "CFO vendor payment limit",
            "principal": principal,
            "action": action,
            "resource": None,
            "agent": agent,
            "conditions": [{"field": "amount", "operator": "<=", "value": 250000}],
            "constraints": {"delegated_by": None, "evidence_required": None, "risk_level": None},
            "effect": "require_human_review",
            "metadata_owner": None,
            "confidence": 0.9,
            "missing_fields": [],
        },
        "clarifying_question": None,
        "requires_additional_policies": False,
        "additional_policies_note": None,
    }


# --- Happy path ---------------------------------------------------------


def test_valid_instruction_produces_a_validated_proposal(db, org_with_principal):
    org, _principal, _agent = org_with_principal
    provider = FakeProvider(_valid_proposal())

    result = svc.draft_or_edit(db, org, "Only allow the CFO to create vendor payments up to R250,000.", None, provider=provider)

    assert result.content is not None
    assert result.content["scope"]["principal"] == "CFO"
    assert result.content["scope"]["action"] == "vendor_payment"
    assert result.content["effect"] == "require_human_review"
    assert result.content["metadata"]["created_by"] == "draft_with_ai"
    assert result.unknown_entities == ()
    assert result.clarifying_question is None


def test_valid_agent_restriction_is_validated_and_included(db, org_with_principal):
    org, _principal, agent = org_with_principal
    provider = FakeProvider(_valid_proposal(agent=agent.name))

    result = svc.draft_or_edit(db, org, "Only AP-Invoice-Agent, acting for the CFO...", None, provider=provider)

    assert result.content is not None
    assert result.content["scope"]["agent"] == agent.name


# --- Ambiguity (section 36) ----------------------------------------------


def test_ambiguous_instruction_returns_clarifying_question_not_a_guess(db, org_with_principal):
    org, _principal, _agent = org_with_principal
    ambiguous_response = {
        "proposal": None,
        "clarifying_question": "Which principal(s) count as senior?",
        "requires_additional_policies": False,
        "additional_policies_note": None,
    }
    provider = FakeProvider(ambiguous_response)

    result = svc.draft_or_edit(db, org, "Let senior people approve large transactions.", None, provider=provider)

    assert result.content is None
    assert result.clarifying_question == "Which principal(s) count as senior?"


# --- Existing entities only (section 37) ---------------------------------


def test_unknown_principal_is_rejected_not_silently_created(db, org_with_principal):
    org, _principal, _agent = org_with_principal
    provider = FakeProvider(_valid_proposal(principal="Regional VP Sales"))

    result = svc.draft_or_edit(db, org, "Let the Regional VP Sales approve...", None, provider=provider)

    assert result.content is None
    assert any(u.field == "principal" and u.value == "Regional VP Sales" for u in result.unknown_entities)


def test_unknown_action_is_rejected(db, org_with_principal):
    org, _principal, _agent = org_with_principal
    provider = FakeProvider(_valid_proposal(action="delete_production_database"))

    result = svc.draft_or_edit(db, org, "Let the CFO delete the production database.", None, provider=provider)

    assert result.content is None
    assert any(u.field == "action" for u in result.unknown_entities)


def test_unknown_agent_is_rejected(db, org_with_principal):
    org, _principal, _agent = org_with_principal
    provider = FakeProvider(_valid_proposal(agent="Some-Nonexistent-Agent"))

    result = svc.draft_or_edit(db, org, "Restrict this to Some-Nonexistent-Agent.", None, provider=provider)

    assert result.content is None
    assert any(u.field == "agent" and u.value == "Some-Nonexistent-Agent" for u in result.unknown_entities)


def test_cross_tenant_principal_is_treated_as_unknown(db, org_with_principal):
    """A principal that genuinely exists, but in a DIFFERENT organisation,
    must be rejected exactly like one that doesn't exist anywhere --
    section 37/48 (never leak or honour another tenant's data)."""
    org, _principal, _agent = org_with_principal
    other_org = Organization(id=uuid.uuid4(), name="Org B")
    db.add(other_org)
    other_principal = Principal(id=uuid.uuid4(), name="Other Org CFO", organization_id=other_org.id)
    db.add(other_principal)
    db.commit()

    provider = FakeProvider(_valid_proposal(principal="Other Org CFO"))
    result = svc.draft_or_edit(db, org, "Let Other Org CFO approve...", None, provider=provider)

    assert result.content is None
    assert any(u.field == "principal" for u in result.unknown_entities)


# --- Multi-policy honesty (section 35) -----------------------------------


def test_flags_when_the_instruction_needs_more_than_one_policy(db, org_with_principal):
    org, _principal, _agent = org_with_principal
    response = _valid_proposal()
    response["requires_additional_policies"] = True
    response["additional_policies_note"] = "A second policy is needed for amounts above R250,000."
    provider = FakeProvider(response)

    result = svc.draft_or_edit(
        db, org,
        "Only allow the CFO to create vendor payments up to R250,000. Anything above needs human approval.",
        None, provider=provider,
    )

    assert result.requires_additional_policies is True
    assert "second policy" in result.additional_policies_note


# --- Not configured (section 46) -----------------------------------------


def test_raises_a_clear_error_when_no_ai_provider_is_configured(db, org_with_principal, monkeypatch):
    org, _principal, _agent = org_with_principal
    monkeypatch.setattr("app.services.policy_drafting_service.settings.azure_ai_foundry_endpoint", None)

    with pytest.raises(svc.AIDraftingNotConfiguredError):
        svc.draft_or_edit(db, org, "anything", None)


# --- Explain (section 49) -------------------------------------------------


def test_explain_is_anchored_in_the_deterministic_summary_passed_in(db, org_with_principal):
    org, _principal, _agent = org_with_principal
    provider = FakeProvider({"explanation": "This rule requires human approval above R250,000 for the CFO."})

    explanation = svc.explain(
        db, org,
        current_draft={"scope": {"principal": "CFO", "action": "vendor_payment"}, "effect": "require_human_review"},
        deterministic_summary="When CFO tries to vendor_payment, and amount is at most 250000, -> Needs human approval.",
        question="Why does this require human approval?",
        provider=provider,
    )

    assert "human approval" in explanation.lower()
