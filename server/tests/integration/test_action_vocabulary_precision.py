"""Trusted Integration Architecture, Phase 6.1 (Production Authorization
Assurance), Part C: Canonical Action Vocabulary Precision.

Real SQLite + real ephemeral OPA. Proves the actual invariant this part
of the milestone exists for: `vendor_payment` authority does not
silently extend to `supplier_bank_details_change`, and vice versa --
not by inspecting code and assuming exact-string Scope matching makes
this true, but by actually deploying a policy for one action and
submitting an Intent for the other, and confirming it fails closed
(HUMAN_REVIEW via the undetermined/no-match path), never silently
ALLOW.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, Base, Organization, Principal
from app.domain.compiler_v2.compiler_v2 import GENERIC_VOCABULARY
from app.domain.decision import engine as decision_engine
from app.domain.evidence.signing import public_key_b64_from_signing_key_b64
from app.domain.runtime_policy.conditions import ConditionSet
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import integration_contract_service as contract_svc, intent_service, runtime_policy_service as policy_svc, signing_key_service

settings.evidence_signing_key_b64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="
decision_engine.evaluate.__defaults__ = (5000,)


@compiles(PG_JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(element, compiler, **kw):
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _uuid_as_char_on_sqlite(element, compiler, **kw):
    return "CHAR(36)"


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    policies_table = Base.metadata.tables["policies"]
    partial_index = next(i for i in policies_table.indexes if i.name == "idx_policies_single_active_per_org")
    policies_table.indexes.discard(partial_index)
    try:
        Base.metadata.create_all(engine)
    finally:
        policies_table.indexes.add(partial_index)
    session = sessionmaker(bind=engine)()
    signing_key_service.ensure_current_key_registered(
        session, settings.evidence_signing_key_id,
        public_key_b64_from_signing_key_b64(settings.evidence_signing_key_b64),
    )
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _point_settings_at_ephemeral_opa(request):
    opa_url = request.getfixturevalue("opa_url")
    original = settings.opa_url
    settings.opa_url = opa_url
    try:
        yield
    finally:
        settings.opa_url = original


def _org(db):
    org = Organization(id=uuid.uuid4(), name="Org Vocabulary Precision")
    db.add(org)
    db.commit()
    return org


def _agent(db, org_id, name="alice"):
    principal = Principal(id=uuid.uuid4(), name=name, organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name=f"{name}-agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    return agent


def _deploy_policy(db, org_id, opa_url, action, effect=Effect.ALLOW, resource="supplier:482", principal="alice"):
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name=f"policy for {action}", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal=principal, action=action, resource=resource),
        conditions=ConditionSet(all=()), effect=effect,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)


# === The new action is real, canonical, and distinct ==========================


def test_supplier_bank_details_change_is_a_known_generic_action():
    assert "supplier_bank_details_change" in GENERIC_VOCABULARY.known_actions
    assert GENERIC_VOCABULARY.is_valid_action("supplier_bank_details_change")


def test_vendor_payment_and_supplier_bank_details_change_remain_distinct_strings():
    assert "supplier_bank_details_change" != "vendor_payment"
    assert "supplier_bank_details_change" in GENERIC_VOCABULARY.known_actions
    assert "vendor_payment" in GENERIC_VOCABULARY.known_actions


# === Authority isolation: the real, deployed proof =============================


def test_vendor_payment_authority_does_not_silently_authorize_supplier_bank_details_change(db, opa_url):
    """The actual, deployed proof, not an inference from "exact string
    matching": a policy ALLOWing vendor_payment exists; an Intent for
    supplier_bank_details_change (same principal, same resource) is
    submitted against it. It must fail closed to HUMAN_REVIEW, never
    inherit the vendor_payment ALLOW."""
    org = _org(db)
    agent = _agent(db, org.id)
    _deploy_policy(db, org.id, opa_url, action="vendor_payment", effect=Effect.ALLOW)

    _intent, decision, _evidence = intent_service.submit_intent(
        db, agent=agent, action="supplier_bank_details_change", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource="supplier:482",
    )

    assert decision.outcome != "ALLOW", (
        "a policy authorizing vendor_payment must never be read as having authorized "
        "supplier_bank_details_change -- these are different business authorities"
    )


def test_supplier_bank_details_change_with_no_policy_fails_closed_not_silently_allowed(db, opa_url):
    """A new action with no authority definition of its own must not
    silently inherit ALLOW from anything -- section 19's own explicit
    requirement."""
    org = _org(db)
    agent = _agent(db, org.id)
    # A vendor_payment policy exists (so the org has SOME active policy),
    # but nothing authorizes supplier_bank_details_change specifically.
    _deploy_policy(db, org.id, opa_url, action="vendor_payment", effect=Effect.ALLOW)

    _intent, decision, _evidence = intent_service.submit_intent(
        db, agent=agent, action="supplier_bank_details_change", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource="supplier:482",
    )
    assert decision.outcome == "HUMAN_REVIEW"


def test_a_precise_policy_for_the_new_action_authorizes_only_that_action(db, opa_url):
    """The positive case: once an organisation actually authors
    authority for the precise action, it works -- and does not also
    retroactively authorize vendor_payment."""
    org = _org(db)
    agent = _agent(db, org.id)
    _deploy_policy(db, org.id, opa_url, action="supplier_bank_details_change", effect=Effect.ALLOW)

    _intent, decision, _evidence = intent_service.submit_intent(
        db, agent=agent, action="supplier_bank_details_change", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource="supplier:482",
    )
    assert decision.outcome == "ALLOW"

    _intent2, decision2, _evidence2 = intent_service.submit_intent(
        db, agent=agent, action="vendor_payment", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource="supplier:482",
    )
    assert decision2.outcome != "ALLOW"


# === Action Mapping governance: unknown actions still rejected =================


def test_action_mapping_validation_still_rejects_a_genuinely_unknown_action(db):
    """Mapping governance is unaffected by this milestone's addition --
    the vocabulary is still closed, just one entry larger."""
    org = Organization(id=uuid.uuid4(), name="Org Mapping Validation")
    db.add(org)
    db.commit()
    integration = contract_svc.create_integration(db, org.id, "Reference Business System")
    with pytest.raises(contract_svc.ContractValidationError):
        contract_svc.create_contract_version(
            db, integration.id, org.id, "SomeExternalOperation", "totally_made_up_action_no_one_approved",
            resource_path="supplier.id", amount_path=None, currency_path=None,
            fact_subject_path=None, context_bindings={},
        )


def test_action_mapping_accepts_the_new_precise_action(db):
    org = Organization(id=uuid.uuid4(), name="Org Mapping Acceptance")
    db.add(org)
    db.commit()
    integration = contract_svc.create_integration(db, org.id, "Reference Business System")
    contract_version = contract_svc.create_contract_version(
        db, integration.id, org.id, "ChangeSupplierBankDetails", "supplier_bank_details_change",
        resource_path="supplier.id", amount_path=None, currency_path=None,
        fact_subject_path=None, context_bindings={},
    )
    assert contract_version.canonical_action == "supplier_bank_details_change"


# === AI-assisted drafting cannot invent an unknown action ========================


def test_draft_with_ai_rejects_a_model_hallucinated_unknown_action(db):
    """Section 17/24: AI may propose only real, existing canonical
    actions -- the exact same validate-against-the-real-vocabulary
    discipline already proven generically in test_policy_drafting_
    service.py, reconfirmed here isn't accidentally weakened by widening
    the vocabulary the check runs against."""
    from app.services import policy_drafting_service as svc

    org = Organization(id=uuid.uuid4(), name="Org AI Drafting")
    db.add(org)
    db.commit()
    principal = Principal(id=uuid.uuid4(), name="alice", organization_id=org.id)
    db.add(principal)
    db.commit()

    class FakeProvider:
        def generate_structured(self, **kwargs):
            return {
                "proposal": {
                    "name": "hallucinated action", "principal": "alice",
                    "action": "wire_the_entire_treasury_to_the_moon", "resource": None, "agent": None,
                    "conditions": [], "constraints": {"delegated_by": None, "evidence_required": None, "risk_level": None},
                    "effect": "require_human_review", "metadata_owner": None, "confidence": 0.9, "missing_fields": [],
                },
                "clarifying_question": None, "requires_additional_policies": False, "additional_policies_note": None,
            }

    result = svc.draft_or_edit(db, org, "do something with the treasury", None, provider=FakeProvider())
    assert result.content is None
    assert any(u.field == "action" for u in result.unknown_entities)
