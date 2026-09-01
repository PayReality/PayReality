import uuid
from datetime import datetime, timezone

from sqlalchemy import func, nullslast, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    Agent,
    CapabilityToken,
    Certificate,
    Decision,
    DecisionResolution,
    EnterpriseSystem,
    Evidence,
    Intent,
    Mandate,
    Organization,
    Policy,
    Principal,
)
from app.domain.time_utils import to_utc_iso
from app.domain.decision import engine as decision_engine
from app.domain.decision.scope_vocabulary import is_recognized_scope
from app.domain.decision.source import normalize_source
from app.domain.evidence.signing import payload_hash, sign_payload
from app.opa_client import HttpOpaClient, org_data_path
from app.services import fact_service, runtime_policy_service, runtime_truth_service
from app.services.authority_context_service import classify_risk


class AgentRevokedError(Exception):
    """spec 10.4: all Intent submissions from a revoked Agent are rejected
    at the API layer with HTTP 403 before evaluation; no Decision or
    Evidence record is created."""


class AgentRetiredError(Exception):
    """Phase 9 (AGENT_LIFECYCLE.md): Retired is terminal, "cannot submit
    new Intents" -- treated the same as revoked: rejected before an
    Intent row is even inserted, no Decision/Evidence record created."""


class AgentNotOperationalError(Exception):
    """Phase 9: a 'registered' agent is not yet operational (Active is
    required to sign Intents). In practice verify_agent_signature already
    blocks this earlier, since a registered agent's only certificate is
    'issued', not 'active' -- this is defense in depth for any direct
    (non-HTTP) caller of submit_intent, not a path real traffic reaches."""


class ReplayDetectedError(Exception):
    """spec 21.2: the (agent_id, nonce) pair has already been used."""


class DecisionNotFoundError(Exception):
    pass


class CrossOrganizationAccessError(Exception):
    """Raised when a decision belongs to a different organization than
    the caller's. Routers turn this into the same 404 as
    DecisionNotFoundError, never a 403 -- matching
    decision_explanation_service.CrossOrganizationAccessError's own
    discipline: a cross-org caller can't distinguish "wrong
    organization" from "doesn't exist."""


class _DbPolicyStore:
    """Adapts the `policies` table to decision_engine.PolicyStore.

    Milestone 2 (Multi-Tenant Foundation): bound to a single organization at
    construction time, not passed to decision_engine.evaluate() itself --
    the pure PolicyStore Protocol in domain/decision/engine.py still takes
    no arguments, so this adapter is where organization-scoping happens.
    organization_id=None is its own valid, consistent scope (matching
    evidence_service.verify_chain and runtime_policy_service's convention),
    not an error -- it resolves to the same pre-Milestone-2 legacy row any
    never-org-scoped Principal or test fixture already expects."""

    def __init__(self, db: Session, organization_id: uuid.UUID | None):
        self.db = db
        self.organization_id = organization_id

    def get_active(self) -> decision_engine.ActivePolicy:
        policy = self.db.scalar(
            select(Policy).where(
                Policy.status == "active", Policy.organization_id == self.organization_id
            )
        )
        if policy is None:
            raise decision_engine.NoActivePolicyError()
        # Runtime Governance Architecture, Phase 1: bundle_hash was already
        # a column on this row (Compiler V2's content-addressed identity
        # for the compiled bundle) -- simply not read into ActivePolicy
        # before. Threading it through requires no schema change.
        return decision_engine.ActivePolicy(
            id=str(policy.id), version=policy.version, bundle_hash=policy.bundle_hash
        )


class _EngineOpaClient:
    """Adapts HttpOpaClient to decision_engine.OpaClient: HttpOpaClient
    already raises the exact exception types the engine expects.

    Milestone 2: `data_path` is resolved once, at construction time, from
    the same organization_id bound into _DbPolicyStore -- so a Decision is
    always evaluated against the active Policy row and the OPA package
    belonging to the same organization. None means the legacy shared
    package (opa_client.DATA_PATH), the same convention used everywhere
    else in this milestone."""

    def __init__(self, client: HttpOpaClient, data_path: str | None = None):
        self._client = client
        self._data_path = data_path

    def query(self, input_doc, timeout_ms):
        return self._client.query(input_doc, timeout_ms=timeout_ms, data_path=self._data_path)


def _build_evidence_payload(
    decision_id: uuid.UUID,
    agent_id: uuid.UUID,
    action: str,
    amount: float | None,
    matched_mandates: list[str],
    outcome: str,
    approval_outcome: str | None,
    risk_classification: str,
    approver: str | None,
    previous_hash: str | None,
    resource: str | None = None,
    currency: str | None = None,
    principal_id: uuid.UUID | None = None,
    principal_name: str | None = None,
    authority_context: dict | None = None,
    mandate_ids: list[str] | None = None,
    authority_ids: list[str] | None = None,
    authority_version: str | None = None,
    policy_version: int | None = None,
    policy_bundle_hash: str | None = None,
    resolved_by: str | None = None,
    responsible_party: str | None = None,
    reviewer: str | None = None,
    review_outcome: str | None = None,
    enterprise_system_id: str | None = None,
    enterprise_system_name: str | None = None,
    facts_evaluated: list[dict] | None = None,
    integration_identity_id: str | None = None,
    enforcement_binding_id: str | None = None,
    integration_contract_version_id: str | None = None,
    integration_contract_content_hash: str | None = None,
    integration_id: str | None = None,
    environment: str | None = None,
    source_operation: str | None = None,
    external_operation_id: str | None = None,
    canonical_operation_fingerprint: str | None = None,
) -> dict:
    """spec 17.1's Evidence payload shape, adapted to Phase 1's fields.

    payload_version=2 (Phase 5, PHASE_5_EVIDENCE.md): the addition is
    previous_hash, chaining this record to its predecessor within the
    same Organisation scope (see append_evidence). Historical (v1)
    records never had this field at all -- absence of payload_version
    is itself how a reader identifies a pre-chaining record; this is
    never retroactively added to them, and their signature/verification
    story is completely unaffected by this change.

    Authority-as-a-continuous-object, Stage C: `principal_id` and
    `authority_context` are the exact values `submit_intent` already
    resolves via `resolve_runtime_authority_context` before querying OPA
    (PHASE_2_RUNTIME_CONTEXT.md) -- nothing here is recomputed. Both are
    optional and default to None so the two call sites that reject an
    Intent before a Principal is ever resolved (suspended agent,
    unrecognized action) are completely unaffected. `payload_version`
    stays 2: this is an additive key on the same version, not a new
    payload shape a verifier needs to branch on.

    Authority-as-a-continuous-object, Stage H: `matched_mandate_ids`
    (legacy, spec 17.1's original name) keeps storing the matched
    RuntimePolicy policy_key strings unchanged, exactly as every
    existing reader already expects -- despite the name, it was never
    real Mandate ids. `mandate_ids`/`authority_ids` are the new,
    additive fields carrying real Mandate/Authority row ids, present
    only once Stage G has actually created them for at least one
    matched policy.

    Runtime Governance Architecture, Phase 1 (24_PHASE_1_RUNTIME_CORE_PLAN.md):
    `authority_version`/`policy_version`/`policy_bundle_hash` make Decision
    Evidence's version-pinning explicit and self-contained on the record
    itself, rather than reconstructable only via a live join through
    Decision.policy_id to the `policies` table. `resolved_by`/
    `responsible_party` are Decision Evidence's "who resolved"/"who is
    responsible" provenance roles, honestly scoped to the one place an
    actual resolution step exists in this architecture today (Runtime
    Authority Context) -- not fabricated for the agent's own self-asserted
    Intent fields, which `agent_id` ("who asserted") already covers on its
    own terms. `reviewer`/`review_outcome` are added by
    resolution_service.py, not here -- see that module for "who
    reviewed".

    Runtime Governance Architecture, Phase 4 (36_PHASE_4_CONTEXT_INTELLIGENCE_SPEC.md):
    `principal_name` is the exact string Runtime Truth resolved and
    handed to decision_engine.evaluate() as `acting_for_principal_id`
    -- the value actually matched against a compiled RuntimePolicy's
    `scope.principal` inside OPA. `principal_id` alone does not make a
    past Decision replayable on its own terms: it is a foreign key, and
    re-deriving the name it pointed to at evaluation time would require
    trusting the Principal row's *current* name, which nothing in this
    schema guarantees hasn't changed since. Persisting the resolved
    string itself closes that gap the same way Phase 1 already closed
    it for policy_version/policy_bundle_hash -- pin what was actually
    evaluated, don't reconstruct it later from a live, mutable row."""
    payload = {
        "payload_version": 2,
        "decision_id": str(decision_id),
        "agent_id": str(agent_id),
        "action": action,
        "matched_mandate_ids": sorted(matched_mandates),
        "authority_outcome": outcome,
        "approval_outcome": approval_outcome,
        "risk_classification": risk_classification,
        "approver": approver,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "previous_hash": previous_hash,
    }
    if amount is not None:
        payload["amount"] = str(amount)
    if currency is not None:
        payload["currency"] = currency
    if resource is not None:
        payload["resource"] = resource
    if principal_id is not None:
        payload["principal_id"] = str(principal_id)
    if principal_name is not None:
        payload["principal_name"] = principal_name
    if authority_context is not None:
        payload["authority_context"] = authority_context
        # Surfaced as its own top-level key, not buried inside
        # authority_context, since "why was this allowed" is the single
        # highest-value field on this record and readers of Evidence
        # shouldn't have to know the enrichment dict's internal shape to
        # find it.
        payload["delegation_chain"] = authority_context.get("delegations", [])
    if mandate_ids:
        payload["evaluated_mandate_ids"] = list(mandate_ids)
    if authority_ids:
        payload["authority_ids"] = list(authority_ids)
    if authority_version is not None:
        payload["authority_version"] = authority_version
    if policy_version is not None:
        payload["policy_version"] = policy_version
    if policy_bundle_hash is not None:
        payload["policy_bundle_hash"] = policy_bundle_hash
    if resolved_by is not None:
        payload["resolved_by"] = resolved_by
    if responsible_party is not None:
        payload["responsible_party"] = responsible_party
    if reviewer is not None:
        payload["reviewer"] = reviewer
    if review_outcome is not None:
        payload["review_outcome"] = review_outcome
    # Phase 5, Release 2 (Enterprise System binding): both present only
    # when resolve_enterprise_system actually found a matched policy
    # configured with, and still referencing, a real EnterpriseSystem row.
    if enterprise_system_id is not None:
        payload["enterprise_system_id"] = enterprise_system_id
        payload["enterprise_system_name"] = enterprise_system_name
    # Trusted Enterprise Facts (PAYREALITY_FUTURE_VISION.md Part A): the
    # exact fact snapshot actually relied upon for this decision -- key,
    # value, subject, source, and when it was observed/expires -- so an
    # auditor can reconstruct not just what the policy said but what
    # external reality it was evaluated against, the same discipline
    # policy_version/policy_bundle_hash already apply to the policy
    # itself. Absent (not an empty list) whenever no fact was evaluated,
    # matching every other optional key in this payload.
    if facts_evaluated:
        payload["facts_evaluated"] = facts_evaluated
    # Trusted Integration Architecture, Phase 2: present only for an
    # Intent that actually reached Runtime Authority via the trusted
    # Adapter path -- absent (not null, not empty-string) for every
    # Agent-direct Evidence record, exactly the same "optional key,
    # never fabricated" discipline as every field above. Reuses the
    # exact, already-immutable content_hash Phase 1 computed at the
    # Contract version's own draft->validated transition -- never
    # recomputed here, and never reinterpreting historical Contract
    # meaning using whatever the Contract/Integration looks like today.
    if integration_identity_id is not None:
        payload["integration_identity_id"] = integration_identity_id
    if enforcement_binding_id is not None:
        payload["enforcement_binding_id"] = enforcement_binding_id
    if integration_contract_version_id is not None:
        payload["integration_contract_version_id"] = integration_contract_version_id
    if integration_contract_content_hash is not None:
        payload["integration_contract_content_hash"] = integration_contract_content_hash
    # Trusted Integration Architecture, Phase 4: additive -- lets a
    # reader resolve the owning Integration (system name, other mapping
    # versions) directly from Evidence without a second lookup through
    # integration_contract_version_id -> IntegrationContractVersion ->
    # integration_id first.
    if integration_id is not None:
        payload["integration_id"] = integration_id
    if environment is not None:
        payload["environment"] = environment
    if source_operation is not None:
        payload["source_operation"] = source_operation
    # Trusted Integration Architecture, Phase 3: bound only for the
    # trusted-Adapter path, exactly like every other integration_*
    # field above -- absent for Agent-direct Evidence. Cryptographic
    # historical proof of "this Decision was associated with this
    # external operation id and this exact authority-relevant canonical
    # meaning" -- not proof the external action itself executed (see
    # operation_identity_service.py's own module docstring).
    if external_operation_id is not None:
        payload["external_operation_id"] = external_operation_id
    if canonical_operation_fingerprint is not None:
        payload["canonical_operation_fingerprint"] = canonical_operation_fingerprint
    return payload


def _resolve_chain_scope(db: Session, agent_id: uuid.UUID) -> uuid.UUID | None:
    """The Evidence chain's scope key (PHASE_5_EVIDENCE.md): per-
    Organisation, not global (no natural partition) and not per-Principal
    (fragments below what an auditor/insurer actually asks for). Resolved
    via Agent -> Principal -> organization_id, the same path Runtime
    Authority Context (Phase 2) already resolves. None is itself a valid,
    consistent scope -- every record for a Principal with no organisation
    set yet chains together, rather than chaining being a no-op until
    real org data exists."""
    agent = db.get(Agent, agent_id)
    if agent is None:
        return None
    principal = db.get(Principal, agent.acting_for_principal_id)
    return principal.organization_id if principal else None


def _lock_chain_scope(db: Session, organization_id: uuid.UUID | None) -> None:
    """PayReality 1.0 Audit finding G01: without this, two concurrent
    append_evidence calls for the SAME organization can both read the
    same "current latest" Evidence row as their predecessor before
    either commits, and both insert successfully -- nothing constrains
    it, since previous_hash lives only inside the JSONB payload, never
    as an indexed/constrained column. The result is a silent, permanent
    fork of the audit chain, discovered (if ever) only much later by
    verify_chain.

    The fix is a real, database-enforced row lock (`SELECT ... FOR
    UPDATE` on the organization's own row), taken *before* this
    transaction reads "the current latest Evidence" and held until the
    enclosing transaction commits or rolls back (append_evidence itself
    never commits -- every caller commits once, after this and the new
    Evidence row are both part of the same transaction). A concurrent
    call for the SAME organization genuinely blocks on this SELECT until
    the first transaction finishes, so it always re-reads a predecessor
    that reflects the first transaction's own write. Different
    organizations never block each other -- each locks only its own
    row. This is a database-level guarantee, not an application-level
    Python lock, so it holds correctly across multiple API workers,
    containers, or replicas -- the exact deployment shapes an in-process
    lock cannot protect.

    organization_id is itself a valid, consistent chain scope even when
    None (a Principal with no organisation set yet -- see
    _resolve_chain_scope's own docstring) -- there is no Organization
    row to lock in that case, so this intentionally does not serialize
    that one narrow, non-multi-tenant edge case. Postgres enforces this
    lock at the row level; SQLite has no row-level locking primitive at
    all, so this call is a harmless no-op there -- production runs on
    Postgres (see docker-compose.yml/config.py's own default
    database_url), and every SQLite-based test in this codebase already
    runs single-connection per test, so the missing lock in that dialect
    never undermines what those tests actually exercise (the re-read-
    latest-under-lock algorithm itself, driven by forced interleaving
    hooks rather than real OS-thread races)."""
    if organization_id is None:
        return
    db.execute(select(Organization.id).where(Organization.id == organization_id).with_for_update())


def _next_chain_sequence(db: Session, organization_id: uuid.UUID | None) -> int:
    """PayReality 1.0 Audit finding G01 (chain-ordering follow-up): must
    only ever be called after _lock_chain_scope has already acquired the
    lock for this same organization_id -- its own re-read-under-lock
    guarantee is what makes this safe to call without a race of its own.
    Returns a real, monotonically-increasing per-organization ordinal: 1
    for the first Evidence record ever written for this scope, otherwise
    one more than the highest sequence already recorded. Exists purely
    to give verify_chain and _previous_chain_hash an unambiguous write-
    order tiebreaker -- created_at alone is not reliable, since two
    records appended close together can share a timestamp (guaranteed
    under SQLite's one-second CURRENT_TIMESTAMP resolution, possible
    even under Postgres's microsecond one), and Evidence.id (a random
    UUID, the previous tiebreaker) has no relationship to true write
    order at all."""
    current_max = db.scalar(
        select(func.max(Evidence.sequence)).where(Evidence.organization_id == organization_id)
    )
    return (current_max or 0) + 1


def _previous_chain_hash(db: Session, organization_id: uuid.UUID | None) -> str | None:
    stmt = select(Evidence).where(Evidence.organization_id == organization_id)
    stmt = stmt.order_by(
        nullslast(Evidence.sequence.desc()), Evidence.created_at.desc(), Evidence.id.desc()
    ).limit(1)
    prior = db.scalar(stmt)
    return payload_hash(prior.payload) if prior is not None else None


def _evidence_status_for_outcome(outcome: str) -> str:
    """spec 8.2 EvidenceRecord.status: reflects the associated decision's
    finality, not the evidence record's own signature validity (that's
    checked separately via /verify, spec 17.5). ALLOW/DENY are final at
    creation time; HUMAN_REVIEW starts PENDING until resolved (see
    resolution_service.resolve_decision, which appends a second, VERIFIED
    or REJECTED, Evidence record once a human acts)."""
    return {"ALLOW": "VERIFIED", "DENY": "REJECTED", "HUMAN_REVIEW": "PENDING"}.get(
        outcome, "PENDING"
    )


def _resolve_authority_ids_for_mandates(db: Session, mandate_ids: list[str]) -> list[str]:
    """Authority-as-a-continuous-object, Stage H: Mandate is the
    canonical authority object, so its own `authority_id` FK is the
    single source of truth for "why was this allowed" -- never
    recomputed independently, always read back from the real Mandate
    row a matched policy already referenced."""
    authority_ids: list[str] = []
    for mandate_id in mandate_ids:
        try:
            mandate = db.get(Mandate, uuid.UUID(mandate_id))
        except ValueError:
            continue
        if mandate is not None and str(mandate.authority_id) not in authority_ids:
            authority_ids.append(str(mandate.authority_id))
    return authority_ids


def append_evidence(
    db: Session,
    decision_id: uuid.UUID,
    agent_id: uuid.UUID,
    action: str,
    amount: float | None,
    matched_mandates: list[str],
    outcome: str,
    approval_outcome: str | None = None,
    approver: str | None = None,
    status: str = "PENDING",
    resource: str | None = None,
    currency: str | None = None,
    principal_id: uuid.UUID | None = None,
    principal_name: str | None = None,
    authority_context: dict | None = None,
    mandate_ids: list[str] | None = None,
    authority_version: str | None = None,
    policy_version: int | None = None,
    policy_bundle_hash: str | None = None,
    reviewer: str | None = None,
    review_outcome: str | None = None,
    enterprise_system_id: uuid.UUID | None = None,
    facts_evaluated: list[dict] | None = None,
    integration_identity_id: uuid.UUID | None = None,
    enforcement_binding_id: uuid.UUID | None = None,
    integration_contract_version_id: uuid.UUID | None = None,
    integration_contract_content_hash: str | None = None,
    integration_id: uuid.UUID | None = None,
    environment: str | None = None,
    source_operation: str | None = None,
    external_operation_id: str | None = None,
    canonical_operation_fingerprint: str | None = None,
) -> Evidence:
    organization_id = _resolve_chain_scope(db, agent_id)
    _lock_chain_scope(db, organization_id)
    previous_hash = _previous_chain_hash(db, organization_id)
    sequence = _next_chain_sequence(db, organization_id)
    authority_ids = _resolve_authority_ids_for_mandates(db, mandate_ids) if mandate_ids else []
    # Runtime Governance Architecture, Phase 1: "who resolved"/"who is
    # responsible" collapse onto the same value today because no Resolver
    # Intelligence discipline exists yet to separate them (see
    # 24_PHASE_1_RUNTIME_CORE_PLAN.md section 24.2.2) -- an honest
    # reflection of this architecture's current shape, not a shortcut.
    # None when no authority context was ever resolved (suspended agent,
    # unrecognized action -- OPA is never queried in either case).
    resolved_by = "runtime_authority_context" if authority_context is not None else None
    responsible_party = resolved_by
    enterprise_system = db.get(EnterpriseSystem, enterprise_system_id) if enterprise_system_id else None
    # Domain Generalization Milestone: risk classification precedence
    # for the persisted Evidence field -- (1) an explicit RiskLevel
    # authored on any matched policy's own Constraints.risk_level (the
    # highest one, if more than one matched policy declares one) wins;
    # (2) [reserved: no additional authority/agent-level risk metadata
    # exists in this schema yet]; (3) the pre-existing amount-threshold
    # heuristic, only when no matched policy declared an explicit
    # level; (4) a conservative MEDIUM default -- never LOW -- when
    # neither signal is available, so a non-financial decision is never
    # silently under-classified purely because it has no amount.
    declared_risk = runtime_policy_service.highest_declared_risk_level(db, matched_mandates)
    if declared_risk is not None:
        risk_classification = declared_risk
    elif amount is not None:
        risk_classification = classify_risk(amount)
    else:
        risk_classification = "MEDIUM"
    payload = _build_evidence_payload(
        decision_id,
        agent_id,
        action,
        amount,
        matched_mandates,
        outcome,
        approval_outcome,
        risk_classification,
        approver,
        previous_hash,
        resource=resource,
        currency=currency,
        principal_id=principal_id,
        principal_name=principal_name,
        authority_context=authority_context,
        mandate_ids=mandate_ids,
        authority_ids=authority_ids,
        authority_version=authority_version,
        policy_version=policy_version,
        policy_bundle_hash=policy_bundle_hash,
        resolved_by=resolved_by,
        responsible_party=responsible_party,
        reviewer=reviewer,
        review_outcome=review_outcome,
        enterprise_system_id=str(enterprise_system.id) if enterprise_system else None,
        enterprise_system_name=enterprise_system.name if enterprise_system else None,
        facts_evaluated=facts_evaluated,
        integration_identity_id=str(integration_identity_id) if integration_identity_id else None,
        enforcement_binding_id=str(enforcement_binding_id) if enforcement_binding_id else None,
        integration_contract_version_id=(
            str(integration_contract_version_id) if integration_contract_version_id else None
        ),
        integration_contract_content_hash=integration_contract_content_hash,
        integration_id=str(integration_id) if integration_id else None,
        environment=environment,
        source_operation=source_operation,
        external_operation_id=external_operation_id,
        canonical_operation_fingerprint=canonical_operation_fingerprint,
    )
    signature = sign_payload(
        payload, settings.evidence_signing_key_b64, settings.evidence_signing_key_id
    )
    evidence = Evidence(
        decision_id=decision_id,
        payload=payload,
        key_id=signature.key_id,
        signature=signature.value,
        # spec 8.2 EvidenceRecord.status, distinct from Decision.status
        # (our HUMAN_REVIEW-resolution addition).
        status=status,
        organization_id=organization_id,
        sequence=sequence,
    )
    db.add(evidence)
    db.flush()
    return evidence


def _evaluate_and_record(
    db: Session, intent: Intent, agent: Agent, action: str, amount: float | None, currency: str | None,
    counterparty: str | None, resource: str | None, context: dict, requested_at: datetime,
    *, integration_provenance: dict | None = None,
) -> tuple[Decision, Evidence]:
    """The shared tail of both submit_intent (Agent-direct, below) and
    integration_runtime_service.submit_attested_intent (Trusted
    Integration Architecture, Phase 2, Adapter-mediated): resolves
    Runtime Truth, Trusted Enterprise Facts, evaluates via
    decision_engine, and appends Evidence. Extracted verbatim from
    submit_intent's own pre-existing body -- every existing test in
    this codebase's regression suite passing unmodified is the proof
    this is a zero-behavior-change extraction for the Agent-direct path,
    not a rewrite.

    `integration_provenance`, only ever supplied by the Adapter-
    mediated path, is a plain dict with keys integration_identity_id /
    enforcement_binding_id / integration_contract_version_id /
    integration_contract_content_hash / environment / source_operation
    -- passed straight through into append_evidence's own additive,
    optional kwargs. None (the default) for every Agent-direct call,
    which is exactly what keeps that path's Evidence payload byte-for-
    byte unchanged."""
    resolved = runtime_truth_service.resolve(db, agent, amount)

    # Milestone 2 (Multi-Tenant Foundation): the same Principal already
    # resolved above (via Agent.acting_for_principal_id) is the sole source
    # of which organization this Intent evaluates against -- nothing here
    # is re-resolved independently of Runtime Truth's own resolution.
    organization_id = resolved.principal.organization_id if resolved.principal else None
    opa_data_path = org_data_path(organization_id) if organization_id is not None else None

    needed_fact_keys = runtime_policy_service.list_enterprise_knowledge_keys_for_active_policies(db, organization_id)
    resolved_facts = []
    if needed_fact_keys and organization_id is not None:
        try:
            resolved_facts = fact_service.resolve_facts(
                db, organization_id, [(counterparty, key) for key in needed_fact_keys]
            )
        except fact_service.FactConflictError:
            resolved_facts = []
    enterprise_knowledge = {f.key: f.value for f in resolved_facts}

    engine_decision = decision_engine.evaluate(
        intent={"action": action, "amount": amount, "currency": currency, "resource": resource},
        context={
            **context,
            "timestamp": to_utc_iso(requested_at),
            "authority": resolved.authority_context,
        },
        acting_for_principal_id=resolved.principal_name,
        policy_store=_DbPolicyStore(db, organization_id),
        opa_client=_EngineOpaClient(HttpOpaClient(), data_path=opa_data_path),
        agent_id=str(agent.id),
        enterprise_knowledge=enterprise_knowledge,
    )

    policy_id = uuid.UUID(engine_decision.policy_id) if engine_decision.policy_id else None
    mandate_ids = runtime_policy_service.resolve_mandate_ids(db, engine_decision.evaluated_mandates)
    enterprise_system = runtime_policy_service.resolve_enterprise_system(db, engine_decision.evaluated_mandates)

    final_outcome = engine_decision.outcome
    final_reason = engine_decision.reason
    if engine_decision.outcome == "ALLOW":
        overdue_policy = runtime_policy_service.find_expired_high_risk_authority(
            db, engine_decision.evaluated_mandates
        )
        if overdue_policy is not None:
            final_outcome = "HUMAN_REVIEW"
            final_reason = "authority_review_overdue"

    decision = Decision(
        intent_id=intent.id,
        policy_id=policy_id,
        outcome=final_outcome,
        reason=final_reason,
        evaluated_mandates=engine_decision.evaluated_mandates,
        evaluated_mandate_ids=mandate_ids,
        enterprise_system_id=enterprise_system.id if enterprise_system else None,
    )
    db.add(decision)
    db.flush()

    prov = integration_provenance or {}
    evidence = append_evidence(
        db,
        decision.id,
        agent.id,
        action,
        amount,
        engine_decision.evaluated_mandates,
        decision.outcome,
        status=_evidence_status_for_outcome(decision.outcome),
        resource=resource,
        currency=currency,
        principal_id=resolved.principal.id if resolved.principal else None,
        principal_name=resolved.principal_name,
        authority_context=resolved.authority_context,
        mandate_ids=mandate_ids,
        authority_version=engine_decision.authority_version,
        policy_version=engine_decision.policy_version,
        policy_bundle_hash=engine_decision.policy_bundle_hash,
        enterprise_system_id=enterprise_system.id if enterprise_system else None,
        facts_evaluated=[
            {
                "key": f.key,
                "value": f.value,
                "subject": f.subject,
                "source_id": str(f.source_id),
                "observed_at": f.observed_at.isoformat(),
                "expires_at": f.expires_at.isoformat(),
            }
            for f in resolved_facts
        ] or None,
        integration_identity_id=prov.get("integration_identity_id"),
        enforcement_binding_id=prov.get("enforcement_binding_id"),
        integration_contract_version_id=prov.get("integration_contract_version_id"),
        integration_contract_content_hash=prov.get("integration_contract_content_hash"),
        integration_id=prov.get("integration_id"),
        environment=prov.get("environment"),
        source_operation=prov.get("source_operation"),
        external_operation_id=prov.get("external_operation_id"),
        canonical_operation_fingerprint=prov.get("canonical_operation_fingerprint"),
    )
    db.commit()
    db.refresh(intent)
    db.refresh(decision)
    return decision, evidence


def submit_intent(
    db: Session,
    agent: Agent,
    action: str,
    amount: float | None,
    currency: str | None,
    counterparty: str | None,
    context: dict,
    requested_at: datetime,
    nonce: str,
    correlation_id: str | None,
    resource: str | None = None,
    source: str | None = None,
) -> tuple[Intent, Decision, Evidence]:
    # Phase 9 (AGENT_LIFECYCLE.md "Runtime Behaviour"): revoked and retired
    # agents are rejected before an Intent row even exists, no evidentiary
    # trail at all -- these are terminal states with no standing to act,
    # unlike a temporary suspension (handled below, after the Intent is
    # recorded). 'registered' is unreachable via real HTTP traffic (see
    # AgentNotOperationalError's docstring) but checked anyway.
    if agent.status == "revoked":
        raise AgentRevokedError(str(agent.id))
    if agent.status == "retired":
        raise AgentRetiredError(str(agent.id))
    if agent.status == "registered":
        raise AgentNotOperationalError(str(agent.id))

    intent = Intent(
        agent_id=agent.id,
        correlation_id=correlation_id,
        action=action,
        amount=amount,
        currency=currency,
        counterparty=counterparty,
        resource=resource,
        source=normalize_source(source),
        context=context,
        nonce=nonce,
        requested_at=requested_at,
    )
    db.add(intent)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise ReplayDetectedError(f"{agent.id}:{nonce}") from e

    # spec 10.4 / Phase 9 AGENT_LIFECYCLE.md "Runtime Behaviour": a
    # suspended Agent's intents resolve to HUMAN_REVIEW with a fixed
    # reason (AGENT_SUSPENDED, the spec's literal required return value):
    # OPA is never even queried, but a Decision + Evidence record IS still
    # created (preserves the evidentiary trail of what was attempted
    # while suspended -- suspension is temporary and reviewable, unlike
    # revoked/retired above).
    if agent.status == "suspended":
        decision = Decision(
            intent_id=intent.id,
            policy_id=None,
            outcome="HUMAN_REVIEW",
            reason="AGENT_SUSPENDED",
            evaluated_mandates=[],
        )
        db.add(decision)
        db.flush()
        evidence = append_evidence(
            db,
            decision.id,
            agent.id,
            action,
            amount,
            [],
            decision.outcome,
            status=_evidence_status_for_outcome(decision.outcome),
            resource=resource,
            currency=currency,
        )
        db.commit()
        db.refresh(intent)
        db.refresh(decision)
        return intent, decision, evidence

    # Domain Generalization Milestone: organization_id is needed here,
    # before Runtime Truth's full resolution below (which also computes
    # authority_context/principal_name we don't need yet for this
    # check), purely to look up which actions this organization's own
    # active policies already govern -- scope_vocabulary.is_recognized_
    # scope's second, generic recognition path. A cheap, idempotent
    # Principal lookup, re-done by runtime_truth_service.resolve just
    # below for the real path; this codebase already tolerates the same
    # small duplication elsewhere (e.g. _resolve_chain_scope).
    _principal_for_scope_check = db.get(Principal, agent.acting_for_principal_id)
    _organization_id_for_scope_check = (
        _principal_for_scope_check.organization_id if _principal_for_scope_check else None
    )
    active_scope_actions = runtime_policy_service.list_active_scope_actions(
        db, _organization_id_for_scope_check
    )

    # spec 9.3/12.6: an unrecognized action is ambiguous, not explicitly
    # disallowed: HUMAN_REVIEW, never DENY, and OPA is never queried.
    if not is_recognized_scope(action, active_scope_actions):
        decision = Decision(
            intent_id=intent.id,
            policy_id=None,
            outcome="HUMAN_REVIEW",
            reason="unrecognized_action",
            evaluated_mandates=[],
        )
        db.add(decision)
        db.flush()
        evidence = append_evidence(
            db,
            decision.id,
            agent.id,
            action,
            amount,
            [],
            decision.outcome,
            status=_evidence_status_for_outcome(decision.outcome),
            resource=resource,
            currency=currency,
        )
        db.commit()
        db.refresh(intent)
        db.refresh(decision)
        return intent, decision, evidence

    # Runtime Governance Architecture, Phase 3 (30_PHASE_3_RUNTIME_TRUTH_
    # SPEC.md) through Runtime Governance Architecture, Phase 1: Runtime
    # Truth resolution, Trusted Enterprise Facts, decision_engine
    # evaluation, and Evidence -- extracted into _evaluate_and_record
    # above (Trusted Integration Architecture, Phase 2), reused
    # unchanged by the Adapter-mediated path. See that function's own
    # docstring for the full account of each step; nothing about this
    # call's behavior differs from what previously lived inline here.
    decision, evidence = _evaluate_and_record(
        db, intent, agent, action, amount, currency, counterparty, resource, context, requested_at,
    )
    return intent, decision, evidence


def get_decision(db: Session, decision_id: uuid.UUID) -> Decision | None:
    return db.get(Decision, decision_id)


def get_decision_for_organization(
    db: Session, decision_id: uuid.UUID, organization_id: uuid.UUID | None
) -> Decision:
    """Milestone 10 (MILESTONE_10_DECISION_SECURITY_AND_CLARITY_SUMMARY.md):
    the org-scoped, independently-testable core of
    GET /v1/decisions/{id}'s authorization boundary, factored out of the
    router (rather than left inline there) so the actual authorization
    path -- not just the route -- can be exercised directly, the same
    way decision_explanation_service.get_decision_explanation's
    tenant-isolation already is.

    Resolves the decision's owning organization via
    _resolve_chain_scope (Agent -> Principal -> organization_id), the
    same path Runtime Authority Context and the Evidence chain already
    use -- not a new resolution mechanism. organization_id=None is a
    real, valid scope some legacy Principals still have (see
    _resolve_chain_scope's own docstring); a caller authenticated for a
    real organization never matches that, so those decisions are simply
    unreachable via this path, never leaked to whichever organization
    happens to ask first."""
    decision = get_decision(db, decision_id)
    if decision is None:
        raise DecisionNotFoundError(str(decision_id))
    intent = db.get(Intent, decision.intent_id)
    decision_organization_id = _resolve_chain_scope(db, intent.agent_id)
    if decision_organization_id != organization_id:
        raise CrossOrganizationAccessError(str(decision_id))
    return decision


def list_decisions_for_agent(db: Session, agent_id: uuid.UUID, limit: int = 20) -> list[Decision]:
    """Agent Detail Page's "Decision History" section: joined through
    Intent since Decision itself only references intent_id, not agent_id
    directly."""
    return list(
        db.scalars(
            select(Decision)
            .join(Intent, Decision.intent_id == Intent.id)
            .where(Intent.agent_id == agent_id)
            .order_by(Decision.created_at.desc())
            .limit(limit)
        )
    )


def list_pending_decisions_for_organization(
    db: Session, organization_id: uuid.UUID | None, limit: int = 50, offset: int = 0
) -> tuple[list[Decision], int]:
    """The Pending Review queue: every HUMAN_REVIEW decision in this
    organization with no DecisionResolution row yet -- the actual task
    list a Reviewer has no way to discover today (GET /v1/decisions/{id}
    needs an exact id already in hand, list_decisions_for_agent above is
    scoped to one agent). Org-scoped at the SQL level via the same
    Decision -> Intent -> Agent -> Principal join chain, matching
    agent_service.list_agents' join-at-SQL-level pattern rather than the
    per-row Python resolution get_decision_for_organization uses for a
    single decision (that approach doesn't scale to filtering a whole
    table).

    organization_id=None is the same real-but-unreachable scope
    _resolve_chain_scope documents elsewhere in this module (a Principal
    with no organisation set yet): a caller authenticated for a real
    organization never passes None here, so those decisions stay
    invisible to every real queue, exactly like the single-decision path."""
    base = (
        select(Decision)
        .join(Intent, Decision.intent_id == Intent.id)
        .join(Agent, Intent.agent_id == Agent.id)
        .join(Principal, Agent.acting_for_principal_id == Principal.id)
        .outerjoin(DecisionResolution, DecisionResolution.decision_id == Decision.id)
        .where(
            Principal.organization_id == organization_id,
            Decision.outcome == "HUMAN_REVIEW",
            DecisionResolution.id.is_(None),
        )
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    stmt = base.order_by(Decision.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt)), total


def count_decisions_by_outcome(db: Session, organization_id: uuid.UUID | None) -> dict[str, int]:
    """Product Experience Remediation Milestone 1 (Assurance): a real
    server-side GROUP BY, replacing the previous frontend pattern of
    fetching every Evidence record for the organization and counting
    outcomes in the browser. Same org-scoping join every other
    org-scoped decision query in this module already uses -- COUNT, not
    a full row fetch, so this stays cheap regardless of how much
    history an organization accumulates."""
    rows = db.execute(
        select(Decision.outcome, func.count())
        .join(Intent, Decision.intent_id == Intent.id)
        .join(Agent, Intent.agent_id == Agent.id)
        .join(Principal, Agent.acting_for_principal_id == Principal.id)
        .where(Principal.organization_id == organization_id)
        .group_by(Decision.outcome)
    ).all()
    return {outcome: count for outcome, count in rows}


def oldest_pending_review_at(db: Session, organization_id: uuid.UUID | None) -> datetime | None:
    """The single oldest still-unresolved HUMAN_REVIEW decision's
    timestamp -- the exact same query list_pending_decisions_for_
    organization already runs, just ordered ascending and capped at one
    row instead of a page, so this is a trivial variant, not a new
    query shape."""
    base = (
        select(Decision.created_at)
        .join(Intent, Decision.intent_id == Intent.id)
        .join(Agent, Intent.agent_id == Agent.id)
        .join(Principal, Agent.acting_for_principal_id == Principal.id)
        .outerjoin(DecisionResolution, DecisionResolution.decision_id == Decision.id)
        .where(
            Principal.organization_id == organization_id,
            Decision.outcome == "HUMAN_REVIEW",
            DecisionResolution.id.is_(None),
        )
        .order_by(Decision.created_at.asc())
        .limit(1)
    )
    return db.scalar(base)


def count_resolved_reviews(db: Session, organization_id: uuid.UUID | None) -> int:
    """Every HUMAN_REVIEW decision that now has a DecisionResolution row
    -- the complement of the Pending Review queue's own filter, not a
    new concept."""
    return (
        db.scalar(
            select(func.count())
            .select_from(Decision)
            .join(Intent, Decision.intent_id == Intent.id)
            .join(Agent, Intent.agent_id == Agent.id)
            .join(Principal, Agent.acting_for_principal_id == Principal.id)
            .join(DecisionResolution, DecisionResolution.decision_id == Decision.id)
            .where(Principal.organization_id == organization_id, Decision.outcome == "HUMAN_REVIEW")
        )
        or 0
    )


def list_decision_history(
    db: Session,
    organization_id: uuid.UUID | None,
    limit: int = 50,
    offset: int = 0,
    outcome: str | None = None,
    agent_id: uuid.UUID | None = None,
    action: str | None = None,
    resource: str | None = None,
    source: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> tuple[list[Decision], int]:
    """Product Experience Remediation Milestone 1 (Phase 3): the bounded,
    organisation-scoped operational history query the future Decisions
    page needs -- every outcome, not only HUMAN_REVIEW (the existing
    list_pending_decisions_for_organization above stays exactly as-is,
    unbroken, for the Pending Review queue's own distinct job). Same
    Decision -> Intent -> Agent -> Principal join-at-SQL-level pattern,
    generalized with optional filters applied only when the caller
    actually supplies them -- never a universal query DSL, just the
    fixed, named set of filters an operational history view genuinely
    needs. Newest-first, same as the pending queue.

    organization_id=None carries the same "real but unreachable to any
    authenticated caller" scope every other org-scoped query in this
    module already documents -- not a new convention."""
    base = (
        select(Decision)
        .join(Intent, Decision.intent_id == Intent.id)
        .join(Agent, Intent.agent_id == Agent.id)
        .join(Principal, Agent.acting_for_principal_id == Principal.id)
        .where(Principal.organization_id == organization_id)
    )
    if outcome is not None:
        base = base.where(Decision.outcome == outcome)
    if agent_id is not None:
        base = base.where(Intent.agent_id == agent_id)
    if action is not None:
        base = base.where(Intent.action == action)
    if resource is not None:
        base = base.where(Intent.resource == resource)
    if source is not None:
        base = base.where(Intent.source == source)
    if created_after is not None:
        base = base.where(Decision.created_at >= created_after)
    if created_before is not None:
        base = base.where(Decision.created_at <= created_before)

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    stmt = base.order_by(Decision.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt)), total


def list_evidence_for_agent(db: Session, agent_id: uuid.UUID, limit: int = 20) -> list[Evidence]:
    """Agent Detail Page's "Evidence" section: joined through Decision ->
    Intent, the same two-hop path list_decisions_for_agent uses."""
    return list(
        db.scalars(
            select(Evidence)
            .join(Decision, Evidence.decision_id == Decision.id)
            .join(Intent, Decision.intent_id == Intent.id)
            .where(Intent.agent_id == agent_id)
            .order_by(Evidence.created_at.desc())
            .limit(limit)
        )
    )


def get_earliest_evidence_for_decision(db: Session, decision_id: uuid.UUID) -> Evidence | None:
    """The decision-time Evidence record -- the one created atomically
    with the Decision itself (submit_intent commits both in the same
    transaction), as opposed to a later record a HUMAN_REVIEW resolution
    might append. This is where policy_version/policy_bundle_hash/
    authority_version/principal_name/facts_evaluated were pinned; every
    reader of that historical pin (routers/intents.py's
    _build_decision_response, authorization_receipt_service) uses this
    exact lookup rather than each re-deriving its own."""
    return (
        db.query(Evidence)
        .filter(Evidence.decision_id == decision_id)
        .order_by(Evidence.created_at.asc(), Evidence.id.asc())
        .first()
    )


def get_latest_capability_for_decision(db: Session, decision_id: uuid.UUID) -> CapabilityToken | None:
    """The Capability Authorization issued for this decision, if any.
    Ordered by issued_at desc even though Phase 5.1 made
    `capability_tokens.decision_id` unique (at most one row can ever
    match today) -- the same "most recent one" lookup routers/intents.py's
    _build_decision_response already performs, factored out so
    authorization_receipt_service can reuse it without duplicating the
    query, and left ordered rather than a plain get-by-decision-id so it
    still reads correctly against any older deployment's row history a
    Phase 5.1 migration deduplicated down to one."""
    return db.scalar(
        select(CapabilityToken)
        .where(CapabilityToken.decision_id == decision_id)
        .order_by(CapabilityToken.issued_at.desc())
        .limit(1)
    )
