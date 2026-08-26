"""Authority Graph -> RuntimePolicy Compilation Gate (GitHub issue #6):
real-infrastructure tests (real SQLite-backed models, real ephemeral OPA
only where a scenario actually needs live decision evaluation), matching
the established discipline in test_decision_explanation.py /
test_enterprise_facts.py -- deliberately duplicates those files' setup
helpers rather than sharing a conftest.
"""

import ast
import inspect
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import (
    Agent,
    AuthorityConflict,
    AuthorityCorpus,
    AuthorityPrincipal,
    AuthorityRelationship,
    Base,
    Organization,
    PolicyExtractionCandidate,
    Principal,
    RuntimePolicyRecord,
)
from app.domain.authority_graph.compilation_gate import (
    NO_APPROVED_GRAPH,
    UNRESOLVED_CONFLICTS_IN_APPROVED_GRAPH,
    UNRESOLVED_OR_INACTIVE_RELATIONSHIP,
    UNRESOLVED_PRINCIPAL,
    check_graph_readiness,
)
from app.domain.decision import engine as decision_engine
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import (
    ai_authority_builder_service as authority_svc,
    ai_policy_builder_service as policy_svc,
    decision_explanation_service,
    intent_service,
    runtime_policy_service as rp_svc,
)
from app.services.ai_policy_builder_service import GraphNotReadyError

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
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _point_settings_at_ephemeral_opa(request):
    if "opa_url" not in request.fixturenames:
        yield
        return
    opa_url = request.getfixturevalue("opa_url")
    original = settings.opa_url
    settings.opa_url = opa_url
    try:
        yield
    finally:
        settings.opa_url = original


@pytest.fixture()
def org(db):
    o = Organization(id=uuid.uuid4(), name="Meridian Industrial")
    db.add(o)
    db.commit()
    return o


@pytest.fixture()
def corpus(db, org):
    c = AuthorityCorpus(id=uuid.uuid4(), name="Delegation of Authority Policy", status="extracted", organization_id=org.id)
    db.add(c)
    db.commit()
    return c


def _discover_principal(db, corpus_id, name, role=None) -> AuthorityPrincipal:
    row = AuthorityPrincipal(id=uuid.uuid4(), corpus_id=corpus_id, name=name, role=role, confidence=0.95)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _resolve_principal(db, discovery: AuthorityPrincipal) -> Principal:
    return authority_svc.resolve_principal(db, discovery.id, action="create", name=discovery.name, role=discovery.role)


def _discover_and_resolve_principal(db, corpus_id, name) -> Principal:
    return _resolve_principal(db, _discover_principal(db, corpus_id, name))


def _discover_relationship(db, corpus_id, kind, from_name, to_name) -> AuthorityRelationship:
    row = AuthorityRelationship(
        id=uuid.uuid4(), corpus_id=corpus_id, kind=kind, from_principal=from_name, to_principal=to_name,
        confidence=0.9,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _resolve_and_activate_relationship(db, relationship: AuthorityRelationship) -> AuthorityRelationship:
    authority_svc.resolve_relationship(db, relationship.id)
    return authority_svc.activate_relationship(db, relationship.id)


def _candidate(
    db, corpus_id, name, principal, action, delegated_by=None, effect="allow", conditions=None, resource=None,
) -> PolicyExtractionCandidate:
    row = PolicyExtractionCandidate(
        id=uuid.uuid4(),
        corpus_id=corpus_id,
        content={
            "name": name,
            "description": None,
            "scope": {"principal": principal, "action": action, "agent": None, "resource": resource},
            "conditions": conditions or [],
            "effect": effect,
            "constraints": {"delegated_by": delegated_by, "expires": None, "evidence_required": True, "risk_level": None},
            "metadata": {"owner": None, "created_by": "ai_policy_builder", "tags": ["ai-extracted"]},
        },
        confidence=0.9,
        missing_fields=[],
        status="pending_review",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _approve(db, corpus_id, reviewer="test-reviewer", reason=None):
    return authority_svc.approve_graph(db, corpus_id, reviewer=reviewer, approval_reason=reason)


def _activate_promoted_policy(db, org_id, policy_key, opa_url):
    """Drives an already-created (via promote_candidate) draft the rest
    of the way through the existing, unmodified lifecycle: submit ->
    approve -> compile -> deploy. Real transient OPA failures are
    retried with backoff, the same discipline established elsewhere."""
    import time

    rp_svc.submit_for_review(db, policy_key, org_id)
    rp_svc.approve(db, policy_key, org_id, approver="test-suite")
    for _attempt in range(6):
        outcome = rp_svc.compile_policy(db, policy_key, org_id)
        assert outcome.ok, f"compile failed: {outcome.diagnostics.errors}"
        try:
            rp_svc.deploy_policy(db, policy_key, org_id, opa_url=opa_url)
            return
        except Exception:
            time.sleep(0.5)
    raise AssertionError("deploy_policy did not succeed after retries")


def _submit(db, agent, action, amount=None, currency=None, resource=None, counterparty=None):
    import time

    intent = decision = evidence = None
    for _attempt in range(6):
        intent, decision, evidence = intent_service.submit_intent(
            db, agent=agent, action=action, amount=amount, currency=currency, counterparty=counterparty,
            context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex,
            correlation_id=None, resource=resource,
        )
        transient = decision.reason == "opa_timeout" or (decision.reason or "").startswith("opa_error:")
        if not transient:
            return intent, decision, evidence
        time.sleep(0.5)
    return intent, decision, evidence


# --- 1/2. Approved vs. unapproved graph ------------------------------------


def test_approved_graph_compiles_a_valid_runtime_policy(db, corpus):
    _discover_and_resolve_principal(db, corpus.id, "Priya Chandrasekaran")
    approval = _approve(db, corpus.id)
    candidate = _candidate(db, corpus.id, "CFO payment authority", "Priya Chandrasekaran", "vendor_payment",
                            conditions=[{"field": "amount", "operator": "<=", "value": 80000}])

    created, _ = policy_svc.promote_candidate(db, candidate.id, corpus.organization_id)
    assert created.status == "draft"
    assert created.content["scope"]["principal"] == "Priya Chandrasekaran"


def test_unapproved_graph_cannot_compile(db, corpus):
    _discover_and_resolve_principal(db, corpus.id, "Priya Chandrasekaran")
    candidate = _candidate(db, corpus.id, "CFO payment authority", "Priya Chandrasekaran", "vendor_payment")

    with pytest.raises(GraphNotReadyError) as exc_info:
        policy_svc.promote_candidate(db, candidate.id, corpus.organization_id)
    assert exc_info.value.errors[0].code == NO_APPROVED_GRAPH
    db.refresh(candidate)
    assert candidate.status == "pending_review"


# --- 3/4. Unresolved / unknown principal ------------------------------------


def test_unresolved_principal_blocks_compilation(db, corpus):
    _discover_principal(db, corpus.id, "Priya Chandrasekaran")  # discovered, never resolved
    _approve(db, corpus.id)
    candidate = _candidate(db, corpus.id, "CFO payment authority", "Priya Chandrasekaran", "vendor_payment")

    with pytest.raises(GraphNotReadyError) as exc_info:
        policy_svc.promote_candidate(db, candidate.id, corpus.organization_id)
    assert exc_info.value.errors[0].code == UNRESOLVED_PRINCIPAL


def test_principal_absent_from_approved_graph_blocks_compilation(db, corpus):
    """A candidate naming a principal the graph never discovered at all
    -- not merely unresolved, genuinely unknown to this approval."""
    _approve(db, corpus.id)
    candidate = _candidate(db, corpus.id, "Someone's authority", "A Person Nobody Discovered", "vendor_payment")

    with pytest.raises(GraphNotReadyError) as exc_info:
        policy_svc.promote_candidate(db, candidate.id, corpus.organization_id)
    assert exc_info.value.errors[0].code == UNRESOLVED_PRINCIPAL


# --- 5. Graph conflict blocks compilation -----------------------------------


def test_open_conflict_blocks_compilation(db, corpus):
    _discover_and_resolve_principal(db, corpus.id, "Priya Chandrasekaran")
    db.add(AuthorityConflict(id=uuid.uuid4(), corpus_id=corpus.id, description="Two conflicting spend limits found.", confidence=0.8))
    db.commit()
    _approve(db, corpus.id)
    candidate = _candidate(db, corpus.id, "CFO payment authority", "Priya Chandrasekaran", "vendor_payment")

    with pytest.raises(GraphNotReadyError) as exc_info:
        policy_svc.promote_candidate(db, candidate.id, corpus.organization_id)
    assert exc_info.value.errors[0].code == UNRESOLVED_CONFLICTS_IN_APPROVED_GRAPH


def test_resolving_conflict_then_reapproving_unblocks_compilation(db, corpus):
    """The conflict-block is against a specific approval's snapshot --
    approving a new, conflict-free version unblocks promotion, proving
    this isn't a permanent corpus-level lock."""
    _discover_and_resolve_principal(db, corpus.id, "Priya Chandrasekaran")
    conflict = AuthorityConflict(id=uuid.uuid4(), corpus_id=corpus.id, description="Stale finding.", confidence=0.5)
    db.add(conflict)
    db.commit()
    _approve(db, corpus.id)  # v1, has the conflict

    db.delete(conflict)
    db.commit()
    _approve(db, corpus.id)  # v2, conflict-free

    candidate = _candidate(db, corpus.id, "CFO payment authority", "Priya Chandrasekaran", "vendor_payment")
    created, _ = policy_svc.promote_candidate(db, candidate.id, corpus.organization_id)
    assert created.content["metadata"]["source_graph_version"] == 2


# --- 6-11. Content fidelity --------------------------------------------------


def test_graph_derived_policy_preserves_principal_action_resource_and_conditions(db, corpus):
    _discover_and_resolve_principal(db, corpus.id, "Elena Ruiz")
    _approve(db, corpus.id)
    candidate = _candidate(
        db, corpus.id, "PO approval authority", "Elena Ruiz", "approve_purchase_order",
        resource="po:*",
        conditions=[
            {"field": "amount", "operator": "<=", "value": 50000},
            {"field": "enterprise_knowledge.budget_available", "operator": "==", "value": True},
        ],
    )
    created, _ = policy_svc.promote_candidate(db, candidate.id, corpus.organization_id)

    assert created.content["scope"]["principal"] == "Elena Ruiz"
    assert created.content["scope"]["action"] == "approve_purchase_order"
    assert created.content["scope"]["resource"] == "po:*"
    fields = {c["field"]: c["value"] for c in created.content["conditions"]["all"]}
    assert fields["amount"] == 50000
    assert fields["enterprise_knowledge.budget_available"] is True


def test_human_review_effect_compiles_correctly(db, corpus):
    _discover_and_resolve_principal(db, corpus.id, "David Okonkwo")
    _approve(db, corpus.id)
    candidate = _candidate(
        db, corpus.id, "Large payment escalation", "David Okonkwo", "vendor_payment",
        effect="require_human_review",
        conditions=[{"field": "amount", "operator": ">", "value": 100000}],
    )
    created, _ = policy_svc.promote_candidate(db, candidate.id, corpus.organization_id)
    assert created.content["effect"] == "require_human_review"


# --- 13/14. Non-active by default, explicit activation still required ------


def test_compiled_policy_starts_as_draft_never_active(db, corpus):
    _discover_and_resolve_principal(db, corpus.id, "David Okonkwo")
    _approve(db, corpus.id)
    candidate = _candidate(db, corpus.id, "Treasury payment authority", "David Okonkwo", "vendor_payment")
    created, _ = policy_svc.promote_candidate(db, candidate.id, corpus.organization_id)
    assert created.status == "draft"
    # No Policy (compiled OPA bundle) row exists yet -- nothing was deployed.
    from app.db.models import Policy
    assert db.query(Policy).count() == 0


def test_explicit_lifecycle_still_required_before_activation(db, corpus, opa_url):
    _discover_and_resolve_principal(db, corpus.id, "David Okonkwo")
    _approve(db, corpus.id)
    candidate = _candidate(
        db, corpus.id, "Treasury payment authority", "David Okonkwo", "vendor_payment",
        conditions=[{"field": "amount", "operator": "<=", "value": 50000}],
    )
    created, _ = policy_svc.promote_candidate(db, candidate.id, corpus.organization_id)
    assert created.status == "draft"

    _activate_promoted_policy(db, corpus.organization_id, created.policy_key, opa_url)
    latest = rp_svc.get_latest(db, created.policy_key, corpus.organization_id)
    assert latest.status == "active"


# --- 15/16. Manual authoring and standalone candidates unaffected ----------


def test_manually_authored_policy_carries_no_graph_provenance(db, org):
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="Manually authored policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal="alice", action="vendor_payment"),
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.LTE, value=1000),)),
        effect=Effect.ALLOW, audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = rp_svc.create_policy(db, policy, org.id)
    assert row.source_graph_approval_id is None
    assert row.content["metadata"]["source_type"] is None


def test_standalone_non_corpus_candidate_promotion_is_unaffected_by_the_gate(db, org):
    """A single-document AI Policy Builder candidate (no corpus_id) has
    no Authority Graph to gate against -- promotion works exactly as it
    always has, with no approval required."""
    candidate = PolicyExtractionCandidate(
        id=uuid.uuid4(), corpus_id=None,
        content={
            "name": "Standalone candidate", "description": None,
            "scope": {"principal": "bob", "action": "vendor_payment", "agent": None, "resource": None},
            "conditions": [{"field": "amount", "operator": "<=", "value": 1000}],
            "effect": "allow",
            "constraints": {"delegated_by": None, "expires": None, "evidence_required": True, "risk_level": None},
            "metadata": {"owner": None, "created_by": "ai_policy_builder", "tags": []},
        },
        confidence=0.9, missing_fields=[], status="pending_review",
    )
    # Standalone candidates are upload-owned in the real schema; a bare
    # corpus_id=None with no upload_id would violate this table's own
    # "exactly one owner" CHECK constraint outside SQLite's relaxed
    # enforcement -- set upload_id via the real upload path instead.
    from app.db.models import PolicyExtractionUpload
    upload = PolicyExtractionUpload(id=uuid.uuid4(), filename="doa.pdf", format="pdf", content=b"", status="extracted", organization_id=org.id)
    db.add(upload)
    db.flush()
    candidate.upload_id = upload.id
    candidate.corpus_id = None
    db.add(candidate)
    db.commit()

    created, _ = policy_svc.promote_candidate(db, candidate.id, org.id)
    assert created.status == "draft"
    assert created.source_graph_approval_id is None


# --- 17. Non-financial graph-derived policy ---------------------------------


def test_non_financial_graph_derived_policy_compiles(db, corpus):
    _discover_and_resolve_principal(db, corpus.id, "Marcus Webb")
    _approve(db, corpus.id)
    candidate = _candidate(
        db, corpus.id, "Access de-provisioning authority", "Marcus Webb", "disable_user",
        resource="user:*",
        conditions=[{"field": "enterprise_knowledge.incident_approved", "operator": "==", "value": True}],
    )
    created, _ = policy_svc.promote_candidate(db, candidate.id, corpus.organization_id)
    assert created.content["scope"]["action"] == "disable_user"
    assert created.content["scope"].get("resource") == "user:*"
    # No amount/currency condition anywhere -- a genuinely non-financial policy.
    assert "amount" not in {c["field"] for c in created.content["conditions"]["all"]}


# --- 18. Unknown action still fails closed (at compile, unchanged) --------


def test_unrecognized_action_still_rejected_at_compile_time_for_a_graph_derived_policy(db, corpus):
    _discover_and_resolve_principal(db, corpus.id, "David Okonkwo")
    _approve(db, corpus.id)
    candidate = _candidate(db, corpus.id, "Bogus authority", "David Okonkwo", "totally_unrecognized_action")
    created, _ = policy_svc.promote_candidate(db, candidate.id, corpus.organization_id)

    rp_svc.submit_for_review(db, created.policy_key, corpus.organization_id)
    rp_svc.approve(db, created.policy_key, corpus.organization_id, approver="test-suite")
    outcome = rp_svc.compile_policy(db, created.policy_key, corpus.organization_id)
    assert not outcome.ok
    assert any(e.code == "INVALID_ACTION" for e in outcome.diagnostics.errors)


# --- 19. Cross-tenant isolation ---------------------------------------------


def test_cross_tenant_candidate_cannot_be_promoted_into_another_organization(db):
    org_a = Organization(id=uuid.uuid4(), name="Org A")
    org_b = Organization(id=uuid.uuid4(), name="Org B")
    db.add_all([org_a, org_b])
    db.commit()
    corpus_a = AuthorityCorpus(id=uuid.uuid4(), name="Org A corpus", status="extracted", organization_id=org_a.id)
    db.add(corpus_a)
    db.commit()
    _discover_and_resolve_principal(db, corpus_a.id, "Alice")
    _approve(db, corpus_a.id)
    candidate = _candidate(db, corpus_a.id, "Org A authority", "Alice", "vendor_payment")

    with pytest.raises(policy_svc.CandidateNotFoundError):
        policy_svc.promote_candidate(db, candidate.id, org_b.id)


# --- 20-22. Provenance and reverse traceability -----------------------------


def test_source_graph_provenance_is_stored_on_the_record(db, corpus):
    _discover_and_resolve_principal(db, corpus.id, "David Okonkwo")
    approval = _approve(db, corpus.id)
    candidate = _candidate(db, corpus.id, "Treasury payment authority", "David Okonkwo", "vendor_payment")
    created, _ = policy_svc.promote_candidate(db, candidate.id, corpus.organization_id)

    assert created.source_graph_approval_id == approval.id


def test_runtime_policy_can_trace_back_to_its_source_approval(db, corpus):
    _discover_and_resolve_principal(db, corpus.id, "David Okonkwo")
    approval = _approve(db, corpus.id)
    candidate = _candidate(db, corpus.id, "Treasury payment authority", "David Okonkwo", "vendor_payment")
    created, _ = policy_svc.promote_candidate(db, candidate.id, corpus.organization_id)

    metadata = created.content["metadata"]
    assert metadata["source_type"] == "authority_graph"
    assert metadata["source_graph_approval_id"] == str(approval.id)
    assert metadata["source_graph_version"] == approval.version
    assert metadata["source_corpus_id"] == str(corpus.id)
    assert metadata["source_candidate_id"] == str(candidate.id)


def test_approval_can_trace_forward_to_the_policies_it_produced(db, corpus):
    _discover_and_resolve_principal(db, corpus.id, "David Okonkwo")
    approval = _approve(db, corpus.id)
    candidate_a = _candidate(db, corpus.id, "Authority A", "David Okonkwo", "vendor_payment")
    candidate_b = _candidate(db, corpus.id, "Authority B", "David Okonkwo", "approve_purchase_order")
    created_a, _ = policy_svc.promote_candidate(db, candidate_a.id, corpus.organization_id)
    created_b, _ = policy_svc.promote_candidate(db, candidate_b.id, corpus.organization_id)

    traced = rp_svc.list_policies_compiled_from_approval(db, approval.id)
    assert {p.id for p in traced} == {created_a.id, created_b.id}


# --- 23/24. Historical correctness across a graph version change -----------


def test_old_decision_and_receipt_stay_bound_to_graph_v1_after_v2_supersedes_it(db, org, opa_url):
    corpus_ = AuthorityCorpus(id=uuid.uuid4(), name="DoA Policy", status="extracted", organization_id=org.id)
    db.add(corpus_)
    db.commit()
    principal = _discover_and_resolve_principal(db, corpus_.id, "David Okonkwo")
    agent = Agent(id=uuid.uuid4(), name="AP-Invoice-Agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()

    approval_v1 = _approve(db, corpus_.id)
    candidate_v1 = _candidate(
        db, corpus_.id, "Treasury payment authority v1", "David Okonkwo", "vendor_payment",
        conditions=[{"field": "amount", "operator": "<=", "value": 80000}],
    )
    created_v1, _ = policy_svc.promote_candidate(db, candidate_v1.id, org.id)
    _activate_promoted_policy(db, org.id, created_v1.policy_key, opa_url)

    _, decision, _ = _submit(db, agent, "vendor_payment", amount=50000.0, currency="USD")
    assert decision.outcome == "ALLOW"

    from app.services import authorization_receipt_service
    receipt_v1 = authorization_receipt_service.get_authorization_receipt(db, decision.id, org.id)
    assert receipt_v1.authority.policies[0].source.graph_approval_id == str(approval_v1.id)
    assert receipt_v1.authority.policies[0].source.graph_version == 1

    # A new graph version is approved and a new policy compiled from it.
    # The old policy is explicitly retired first -- a real operator's
    # own act, not something this milestone automates -- so the new,
    # same-scope policy doesn't conflict with a still-active predecessor.
    from app.services import runtime_policy_lifecycle_service
    runtime_policy_lifecycle_service.retire_policy(
        db, created_v1.policy_key, org.id, opa_url=opa_url, actor="test-suite", reason="Superseded by graph v2."
    )

    approval_v2 = _approve(db, corpus_.id, reason="Threshold raised.")
    candidate_v2 = _candidate(
        db, corpus_.id, "Treasury payment authority v2", "David Okonkwo", "vendor_payment",
        conditions=[{"field": "amount", "operator": "<=", "value": 150000}],
    )
    created_v2, _ = policy_svc.promote_candidate(db, candidate_v2.id, org.id)
    _activate_promoted_policy(db, org.id, created_v2.policy_key, opa_url)

    # The OLD decision's own receipt/explanation must still show v1.
    receipt_v1_again = authorization_receipt_service.get_authorization_receipt(db, decision.id, org.id)
    assert receipt_v1_again.authority.policies[0].source.graph_version == 1, "must still reflect graph v1, not v2"
    assert receipt_v1_again.authority.bundle_hash == receipt_v1.authority.bundle_hash

    explanation = decision_explanation_service.get_decision_explanation(db, decision.id, org.id)
    assert explanation.bundle_hash == receipt_v1.authority.bundle_hash

    # A new decision made now is governed by v2.
    _, decision2, _ = _submit(db, agent, "vendor_payment", amount=120000.0, currency="USD")
    assert decision2.outcome == "ALLOW"
    receipt_v2 = authorization_receipt_service.get_authorization_receipt(db, decision2.id, org.id)
    assert receipt_v2.authority.policies[0].source.graph_version == 2
    assert receipt_v2.authority.bundle_hash != receipt_v1.authority.bundle_hash


# --- 25. TEF stays a runtime concern, not a compile-time one ---------------


def test_enterprise_knowledge_condition_survives_compilation_unresolved(db, corpus):
    """The compiler links the condition reference; it never resolves or
    embeds a current fact value -- that stays Trusted Enterprise Facts'
    job, entirely at decision time."""
    _discover_and_resolve_principal(db, corpus.id, "Elena Ruiz")
    _approve(db, corpus.id)
    candidate = _candidate(
        db, corpus.id, "Supplier payment authority", "Elena Ruiz", "vendor_payment",
        conditions=[{"field": "enterprise_knowledge.supplier_approved", "operator": "==", "value": True}],
    )
    created, _ = policy_svc.promote_candidate(db, candidate.id, corpus.organization_id)
    condition = created.content["conditions"]["all"][0]
    assert condition["field"] == "enterprise_knowledge.supplier_approved"
    assert condition["value"] is True  # the CONDITION's target value, not a resolved runtime fact


# --- 26/27. Determinism ------------------------------------------------------


def test_graph_readiness_check_is_deterministic(db, corpus):
    _discover_and_resolve_principal(db, corpus.id, "David Okonkwo")
    approval = _approve(db, corpus.id)
    content = {"scope": {"principal": "David Okonkwo"}, "constraints": {}}

    first = check_graph_readiness(content, approval.evidence_snapshot)
    second = check_graph_readiness(content, approval.evidence_snapshot)
    assert first == second


def test_same_approval_and_same_candidate_content_produce_equivalent_policies(db, corpus):
    _discover_and_resolve_principal(db, corpus.id, "David Okonkwo")
    _approve(db, corpus.id)
    shared_conditions = [{"field": "amount", "operator": "<=", "value": 80000}]
    candidate_1 = _candidate(db, corpus.id, "Authority (copy 1)", "David Okonkwo", "vendor_payment", conditions=shared_conditions)
    candidate_2 = _candidate(db, corpus.id, "Authority (copy 1)", "David Okonkwo", "vendor_payment", conditions=shared_conditions)

    created_1, _ = policy_svc.promote_candidate(db, candidate_1.id, corpus.organization_id)
    created_2, _ = policy_svc.promote_candidate(db, candidate_2.id, corpus.organization_id)

    assert created_1.content["scope"] == created_2.content["scope"]
    assert created_1.content["conditions"] == created_2.content["conditions"]
    assert created_1.content["effect"] == created_2.content["effect"]


# --- 28. No LLM dependency in the compilation gate --------------------------


def test_compilation_gate_module_has_no_ai_provider_dependency():
    """Structural guarantee, not just a naming convention: the gate's
    own source imports nothing that could reach an LLM or the network."""
    gate_module = __import__("app.domain.authority_graph.compilation_gate", fromlist=["x"])
    tree = ast.parse(inspect.getsource(gate_module))
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)
    forbidden = ("httpx", "requests", "anthropic", "openai", "azure", "boto3")
    assert not any(any(f in name for f in forbidden) for name in imported_names), imported_names


# --- 29. Compile failure never creates an active (or any) policy -----------


def test_blocked_promotion_creates_no_runtime_policy_record(db, corpus):
    _discover_principal(db, corpus.id, "Priya Chandrasekaran")  # unresolved
    _approve(db, corpus.id)
    candidate = _candidate(db, corpus.id, "CFO payment authority", "Priya Chandrasekaran", "vendor_payment")

    before = db.query(RuntimePolicyRecord).count()
    with pytest.raises(GraphNotReadyError):
        policy_svc.promote_candidate(db, candidate.id, corpus.organization_id)
    after = db.query(RuntimePolicyRecord).count()
    assert after == before


# --- 4-continued. Relationship-implied authority ----------------------------


def test_unresolved_relationship_blocks_a_delegated_candidate(db, corpus):
    _discover_and_resolve_principal(db, corpus.id, "Priya Chandrasekaran")  # CFO
    _discover_and_resolve_principal(db, corpus.id, "David Okonkwo")  # Treasury Head
    # Relationship discovered but never resolved/activated.
    _discover_relationship(db, corpus.id, "delegation", "Priya Chandrasekaran", "David Okonkwo")
    _approve(db, corpus.id)
    candidate = _candidate(
        db, corpus.id, "Delegated Treasury authority", "David Okonkwo", "vendor_payment",
        delegated_by="Priya Chandrasekaran",
    )

    with pytest.raises(GraphNotReadyError) as exc_info:
        policy_svc.promote_candidate(db, candidate.id, corpus.organization_id)
    assert exc_info.value.errors[0].code == UNRESOLVED_OR_INACTIVE_RELATIONSHIP


def test_active_delegation_relationship_grounds_a_delegated_candidate(db, corpus):
    _discover_and_resolve_principal(db, corpus.id, "Priya Chandrasekaran")
    _discover_and_resolve_principal(db, corpus.id, "David Okonkwo")
    relationship = _discover_relationship(db, corpus.id, "delegation", "Priya Chandrasekaran", "David Okonkwo")
    _resolve_and_activate_relationship(db, relationship)
    _approve(db, corpus.id)
    candidate = _candidate(
        db, corpus.id, "Delegated Treasury authority", "David Okonkwo", "vendor_payment",
        delegated_by="Priya Chandrasekaran",
    )

    created, _ = policy_svc.promote_candidate(db, candidate.id, corpus.organization_id)
    assert created.status == "draft"
    assert created.content["scope"]["principal"] == "David Okonkwo"
    assert created.content["constraints"]["delegated_by"] == "Priya Chandrasekaran"
