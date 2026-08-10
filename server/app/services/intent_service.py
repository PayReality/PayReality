import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Agent, Certificate, Decision, Evidence, Intent, Mandate, Policy, Principal
from app.domain.time_utils import to_utc_iso
from app.domain.decision import engine as decision_engine
from app.domain.decision.scope_vocabulary import is_recognized_scope
from app.domain.evidence.signing import payload_hash, sign_payload
from app.opa_client import HttpOpaClient
from app.services import runtime_policy_service
from app.services.authority_context_service import classify_risk, resolve_runtime_authority_context


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


class _DbPolicyStore:
    """Adapts the `policies` table to decision_engine.PolicyStore."""

    def __init__(self, db: Session):
        self.db = db

    def get_active(self) -> decision_engine.ActivePolicy:
        policy = self.db.scalar(select(Policy).where(Policy.status == "active"))
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
    already raises the exact exception types the engine expects."""

    def __init__(self, client: HttpOpaClient):
        self._client = client

    def query(self, input_doc, timeout_ms):
        return self._client.query(input_doc, timeout_ms=timeout_ms)


def _build_evidence_payload(
    decision_id: uuid.UUID,
    agent_id: uuid.UUID,
    action: str,
    amount: float,
    matched_mandates: list[str],
    outcome: str,
    approval_outcome: str | None,
    risk_classification: str,
    approver: str | None,
    previous_hash: str | None,
    principal_id: uuid.UUID | None = None,
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
    reviewed"."""
    payload = {
        "payload_version": 2,
        "decision_id": str(decision_id),
        "agent_id": str(agent_id),
        "action": action,
        "amount": str(amount),
        "matched_mandate_ids": sorted(matched_mandates),
        "authority_outcome": outcome,
        "approval_outcome": approval_outcome,
        "risk_classification": risk_classification,
        "approver": approver,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "previous_hash": previous_hash,
    }
    if principal_id is not None:
        payload["principal_id"] = str(principal_id)
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


def _previous_chain_hash(db: Session, organization_id: uuid.UUID | None) -> str | None:
    stmt = select(Evidence).where(Evidence.organization_id == organization_id)
    stmt = stmt.order_by(Evidence.created_at.desc(), Evidence.id.desc()).limit(1)
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
    amount: float,
    matched_mandates: list[str],
    outcome: str,
    approval_outcome: str | None = None,
    approver: str | None = None,
    status: str = "PENDING",
    principal_id: uuid.UUID | None = None,
    authority_context: dict | None = None,
    mandate_ids: list[str] | None = None,
    authority_version: str | None = None,
    policy_version: int | None = None,
    policy_bundle_hash: str | None = None,
    reviewer: str | None = None,
    review_outcome: str | None = None,
) -> Evidence:
    organization_id = _resolve_chain_scope(db, agent_id)
    previous_hash = _previous_chain_hash(db, organization_id)
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
    payload = _build_evidence_payload(
        decision_id,
        agent_id,
        action,
        amount,
        matched_mandates,
        outcome,
        approval_outcome,
        classify_risk(amount),
        approver,
        previous_hash,
        principal_id=principal_id,
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
    )
    db.add(evidence)
    db.flush()
    return evidence


def submit_intent(
    db: Session,
    agent: Agent,
    action: str,
    amount: float,
    currency: str,
    counterparty: str | None,
    context: dict,
    requested_at: datetime,
    nonce: str,
    correlation_id: str | None,
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
        )
        db.commit()
        db.refresh(intent)
        db.refresh(decision)
        return intent, decision, evidence

    # spec 9.3/12.6: an unrecognized action is ambiguous, not explicitly
    # disallowed: HUMAN_REVIEW, never DENY, and OPA is never queried.
    if not is_recognized_scope(action):
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
        )
        db.commit()
        db.refresh(intent)
        db.refresh(decision)
        return intent, decision, evidence

    # RuntimePolicy.scope.principal is authored as the Principal's free-form
    # *name* (AUTHORING_ARCHITECTURE.md: "a reviewer references it by name
    # directly ... which is already a free-form string"), never a foreign
    # key -- but Agent.acting_for_principal_id is a UUID FK into
    # `principals`. The compiled Rego's scope match compares
    # input.agent.acting_for_principal_id against that name string, so the
    # raw FK must be resolved to the Principal's name before it ever
    # reaches OPA; passing the UUID straight through (as this used to)
    # means the scope check can never match any real Agent, for any
    # RuntimePolicy, ever -- every real Intent silently falls through to
    # the "no_policy_covers_scope" fallback regardless of amount.
    principal = db.get(Principal, agent.acting_for_principal_id)
    principal_name = principal.name if principal else str(agent.acting_for_principal_id)

    # Runtime Authority Context (PHASE_2_RUNTIME_CONTEXT.md): an ephemeral,
    # request-scoped enrichment, never stored, merged under "authority" so
    # it can never collide with whatever a caller already put in
    # Intent.context themselves. A policy's Condition can reference e.g.
    # context.authority.department the moment it's authored to -- zero
    # change to rego_generator.py, compile_bundle(), or OPA, since
    # dot-path access into context already works for any field.
    authority_context = resolve_runtime_authority_context(db, principal, amount)

    engine_decision = decision_engine.evaluate(
        intent={"action": action, "amount": amount, "currency": currency},
        context={**context, "timestamp": to_utc_iso(requested_at), "authority": authority_context},
        acting_for_principal_id=principal_name,
        policy_store=_DbPolicyStore(db),
        opa_client=_EngineOpaClient(HttpOpaClient()),
    )

    policy_id = uuid.UUID(engine_decision.policy_id) if engine_decision.policy_id else None
    # Authority-as-a-continuous-object, Stage H: `evaluated_mandates`
    # (legacy) keeps storing the matched RuntimePolicy policy_key
    # strings exactly as before -- `evaluated_mandate_ids` is the new,
    # additive column resolving those same keys to real Mandate row ids
    # wherever Stage G has actually created one.
    mandate_ids = runtime_policy_service.resolve_mandate_ids(db, engine_decision.evaluated_mandates)
    decision = Decision(
        intent_id=intent.id,
        policy_id=policy_id,
        outcome=engine_decision.outcome,
        reason=engine_decision.reason,
        evaluated_mandates=engine_decision.evaluated_mandates,
        evaluated_mandate_ids=mandate_ids,
    )
    db.add(decision)
    db.flush()

    evidence = append_evidence(
        db,
        decision.id,
        agent.id,
        action,
        amount,
        engine_decision.evaluated_mandates,
        decision.outcome,
        status=_evidence_status_for_outcome(decision.outcome),
        # Authority-as-a-continuous-object, Stage C: the exact Principal
        # and authority_context already resolved above for the OPA query
        # itself, carried into Evidence instead of being discarded once
        # the decision is made. Nothing here is recomputed.
        principal_id=principal.id if principal else None,
        authority_context=authority_context,
        mandate_ids=mandate_ids,
        # Runtime Governance Architecture, Phase 1: the exact values
        # decision_engine.evaluate() already resolved and pinned onto its
        # own Decision object -- carried into Evidence, never recomputed,
        # the same discipline this module already applies to
        # authority_context and principal_id above.
        authority_version=engine_decision.authority_version,
        policy_version=engine_decision.policy_version,
        policy_bundle_hash=engine_decision.policy_bundle_hash,
    )
    db.commit()
    db.refresh(intent)
    db.refresh(decision)
    return intent, decision, evidence


def get_decision(db: Session, decision_id: uuid.UUID) -> Decision | None:
    return db.get(Decision, decision_id)


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
