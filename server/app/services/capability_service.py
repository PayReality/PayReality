"""Capability Authorization Protocol (PAYREALITY_FUTURE_VISION.md Part
C): issues and verifies short-lived, signed capabilities bound to one
ALLOW decision, or (Phase 5.1) to one approved HUMAN_REVIEW resolution.
Reuses this platform's existing Ed25519 signing-key registry
(signing_key_service.py) unchanged -- a capability token is signed with
the exact same active evidence-signing key as any other signed record
here, verified via the exact same historical key lookup Evidence
verification already relies on, so key rotation never breaks an
already-issued (but not yet expired) token any more than it breaks old
Evidence.

Explicitly a demonstration protocol, not enforcement infrastructure --
see domain/capability/token.py's own module docstring for the full,
deliberately unsoftened statement of what this does and does not prove.

Trusted Integration Architecture, Phase 5.1 (Capability Issuance
Idempotency): the governing invariant added this phase, applying
identically to every issuance path in this module --

    One authority authorization lifecycle -> at most one CURRENTLY
    USABLE execution permission.

`capability_tokens.decision_id` is now UNIQUE (migration
d4e8b1a6f2c9): a Decision may have at most one Capability row, ever,
issued through either `issue_capability_for_decision` (ALLOW) or
`issue_capability_for_reviewed_decision` (approved HUMAN_REVIEW).
Repeated or concurrent issuance requests against the same Decision
resolve to exactly one of three outcomes, each with its own distinct,
deliberately-chosen exception -- see each one's own docstring below for
the reasoning:

- an unexpired, unconsumed Capability already exists -> `CapabilityAlreadyIssuedError`
- the Decision's one-and-only Capability was already consumed -> `CapabilityAlreadyConsumedForDecisionError`
- the Decision's one-and-only Capability expired, unconsumed -> `CapabilityExpiredNotRenewedError`

None of the three silently mints a second Capability. The DB-level
UNIQUE constraint, not this module's own pre-check, is what actually
makes this safe under concurrency (`_issue_and_persist` below always
attempts the INSERT and handles the constraint violation, never trusts
its own prior SELECT alone -- exactly the same discipline
resolution_service.resolve_decision's own docstring already documents
for `decision_resolutions.decision_id`'s identical UNIQUE constraint)."""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Agent, CapabilityToken, Decision, DecisionResolution, EnforcementBinding, Evidence, Intent, IntegrationIdentity, Organization
from app.domain.capability import token as capability_token
from app.services import intent_service, signing_key_service
from app.services.intent_service import CrossOrganizationAccessError, DecisionNotFoundError
from app.services.resolution_service import DecisionNotHumanReviewError

logger = logging.getLogger("payreality.capability")


class DecisionNotAllowError(Exception):
    """Raised by issue_capability_for_decision only: that function may
    issue a capability for a Decision whose outcome is literally ALLOW
    and nothing else -- issuing one for DENY or HUMAN_REVIEW would mint
    an executable authorization for an action Runtime Authority itself
    never actually permitted. A Decision's `outcome` is immutable
    (resolve_decision never mutates it, by design -- see Decision's own
    docstring), so a HUMAN_REVIEW decision that a human later approves
    still has outcome == HUMAN_REVIEW forever, and this check still
    correctly rejects it here.

    Trusted Integration Architecture, Phase 5.1: a HUMAN_REVIEW decision
    an authorized reviewer has approved is NOT permanently ineligible
    for a capability -- see issue_capability_for_reviewed_decision
    below, a deliberately separate function with its own distinct
    preconditions (DecisionNotHumanReviewError / ReviewNotResolvedError
    / ReviewNotApprovedError), not an extension of this one."""


class IntegrationIdentityNotActiveError(Exception):
    """Trusted Integration Architecture, Phase 5 (fail-closed re-check at
    issuance time): the IntegrationIdentity that produced this Decision's
    Intent is no longer active. An Intent's provenance is immutable, but
    trust is not -- an identity can be suspended/revoked/retired at any
    point after the Intent that used it was accepted, and a Capability
    must never be mintable on behalf of trust that no longer holds *at
    the moment of issuance*, even for an already-decided Decision."""


class EnforcementBindingNotActiveError(Exception):
    """Trusted Integration Architecture, Phase 5 (fail-closed re-check at
    issuance time): the EnforcementBinding (Runtime Connection) this
    Decision's Intent was evaluated under is no longer active. Mirrors
    IntegrationIdentityNotActiveError's own reasoning exactly -- a
    Binding retired after the Intent was accepted must not silently keep
    minting Capabilities under its name."""


class OriginAgentNotActiveError(Exception):
    """Trusted Integration Architecture, Phase 5 (fail-closed re-check at
    issuance time, section 6/40's "wrong Agent"/"Agent removed from
    allowed list" coverage): a real gap this milestone's own hostile
    review found and closed, applying identically to the Agent-direct
    path as well, not only the Trusted-Adapter one -- neither path
    previously re-checked the origin Agent's own live status before
    minting a Capability from an already-decided ALLOW decision. An
    Agent can be suspended/revoked/retired at any point after its
    Intent was accepted (Phase 9, AGENT_LIFECYCLE.md); an EnforcementBinding's
    own allow-list membership is immutable once ACTIVE, so removing an
    Agent from it is not possible without retiring the whole Binding
    (already covered by EnforcementBindingNotActiveError above) -- this
    is the other, equally real half: the Agent's OWN eligibility,
    independent of any Binding.

    Phase 6.1 (Production Authorization Assurance, Part A): this same
    exception is now also raised at CONSUMPTION time, by
    verify_and_consume_capability -- not only at issuance. See
    _check_consumption_freshness's own docstring for the full reasoning
    on why consumption needs this too, and for exactly what is (and is
    deliberately not) re-checked there."""


class TenantNotActiveError(Exception):
    """Phase 6.1, Part A: the Organization that owns this Decision/
    Capability is no longer 'active' (Milestone 3's own Organization
    Lifecycle: active -> deactivated -> archived). Not checked before
    this phase, at either issuance or consumption -- a real, small,
    obviously-correct consistency gap this milestone closes on both
    paths at once, using the exact same live-status-recheck discipline
    already established for Agent/IntegrationIdentity/EnforcementBinding,
    rather than leaving Organization as the one authoritative object
    nothing here ever re-checked."""


class CapabilityTokenNotFoundError(Exception):
    pass


class CapabilityTokenAlreadyConsumedError(Exception):
    """Raised by verify_and_consume_capability when a token presented for
    VERIFICATION was already consumed -- a different moment, and a
    different caller (the PEP, not the issuer), from the three
    ISSUANCE-time errors below. Kept as its own exception, unchanged, so
    the reference adapter and any existing PEP integration's exception
    handling is unaffected by this phase."""


class CapabilityAlreadyIssuedError(Exception):
    """Phase 5.1, section 4: issuance was requested again while the
    Decision's one-and-only Capability is still unexpired and
    unconsumed. The raw token material is never returned a second time
    -- CapabilityToken deliberately stores only a hash of it (see the
    model's own docstring), so there is nothing to hand back even if
    doing so were desirable. `capability_id`/`expires_at` are exposed so
    the caller can see that one is already outstanding and when it
    expires, without exposing the bearer artifact itself."""

    def __init__(self, capability_id: uuid.UUID, expires_at: datetime):
        self.capability_id = capability_id
        self.expires_at = expires_at
        super().__init__(f"capability {capability_id} already issued for this decision, expires {expires_at}")


class CapabilityAlreadyConsumedForDecisionError(Exception):
    """Phase 5.1, section 5: the Decision's one-and-only Capability was
    already consumed. Fail closed by default -- a second Capability for
    an already-consumed authorization could permit duplicate execution
    of the same business operation, exactly the risk this whole phase
    exists to close. No retry/renewal path is built here; one would be a
    deliberate, separately-authorized product decision, not an inferred
    default."""

    def __init__(self, capability_id: uuid.UUID):
        self.capability_id = capability_id
        super().__init__(f"capability {capability_id} for this decision was already consumed")


class CapabilityExpiredNotRenewedError(Exception):
    """Phase 5.1, section 6: the Decision's one-and-only Capability
    expired without being consumed. Deliberately does NOT auto-issue a
    fresh one: authority conditions may have changed since the original
    Decision, and silently treating a historical ALLOW (or an approved
    review) as indefinitely renewable authority is exactly what section
    6 warns against. A genuine operational need to retry a lapsed
    authorization is a real, disclosed gap this phase leaves closed
    rather than papering over with an invented renewal model (section 5's
    own instruction, applied here too)."""

    def __init__(self, capability_id: uuid.UUID, expired_at: datetime):
        self.capability_id = capability_id
        self.expired_at = expired_at
        super().__init__(f"capability {capability_id} for this decision expired at {expired_at} without being consumed")


class ReviewNotResolvedError(Exception):
    """Phase 5.1, section 12: no DecisionResolution exists yet for this
    HUMAN_REVIEW decision -- "Unresolved review: no Capability.\""""


class ReviewNotApprovedError(Exception):
    """Phase 5.1, section 12: a DecisionResolution exists but its
    `resolution` is "denied" -- "Rejected review: no Capability." Only
    the two resolution values this codebase's own domain model actually
    has (decision_resolutions.resolution's CHECK constraint:
    'approved'/'denied') are handled; no "cancelled"/"expired" review
    state exists anywhere in this schema to check, so none is invented
    here (section 12's own instruction)."""

    def __init__(self, resolution: str):
        self.resolution = resolution
        super().__init__(f"review resolution={resolution!r}, not approved")


DEFAULT_CAPABILITY_TOKEN_TTL_SECONDS = 300


@dataclass(frozen=True)
class IssuedCapability:
    token: str
    capability_id: uuid.UUID
    expires_at: datetime


def issue_capability_for_decision(
    db: Session,
    organization_id: uuid.UUID,
    decision_id: uuid.UUID,
    audience: str,
    issued_by: str | None = None,
    ttl_seconds: int = DEFAULT_CAPABILITY_TOKEN_TTL_SECONDS,
) -> IssuedCapability:
    """Issues a Capability for a Decision Runtime Authority itself
    already, directly, decided ALLOW. See issue_capability_for_reviewed_decision
    below for the separate, HUMAN_REVIEW-approved path; the two are
    intentionally distinct functions with distinct preconditions
    (section 11: a resolution is never treated as an unrelated new ALLOW
    decision), converging only on the shared, idempotency-safe
    _issue_and_persist tail."""
    # Reuses intent_service's own org-scoped decision lookup unchanged
    # (the exact function GET /v1/decisions/{id} is built on) rather
    # than re-deriving organization scoping here a second way.
    decision = intent_service.get_decision_for_organization(db, decision_id, organization_id)
    if decision.outcome != "ALLOW":
        raise DecisionNotAllowError(f"decision {decision_id} outcome={decision.outcome!r}")

    intent = db.get(Intent, decision.intent_id)
    return _issue_and_persist(db, organization_id, decision, intent, audience, issued_by, ttl_seconds)


def issue_capability_for_reviewed_decision(
    db: Session,
    organization_id: uuid.UUID,
    decision_id: uuid.UUID,
    audience: str,
    issued_by: str | None = None,
    ttl_seconds: int = DEFAULT_CAPABILITY_TOKEN_TTL_SECONDS,
) -> IssuedCapability:
    """Trusted Integration Architecture, Phase 5.1, Part B: issues a
    Capability for a HUMAN_REVIEW decision an authorized reviewer has
    since approved -- without ever mutating the original Decision, which
    keeps reading outcome=='HUMAN_REVIEW' forever (section 9, and
    resolution_service.resolve_decision's own long-standing guarantee:
    "created once, immutable, never updated"). This is a genuinely
    separate authorization event bound to the resolution, not a
    reinterpretation of the original runtime evaluation.

    Section 13 (reviewer authorization): a DecisionResolution row can
    only ever be created by resolution_service.resolve_decision, which
    is itself gated on Permission.DECISIONS_RESOLVE and organisation-
    scoped (see that function's own docstring). Its mere existence with
    resolution=='approved', found via the same org-scoped decision_id
    lookup used everywhere else in this module, IS the legitimacy check
    -- there is no separate, forgeable "approved" signal to re-verify
    against, and building a second, parallel approval mechanism here
    would be exactly the "parallel approval system" section 13
    explicitly forbids."""
    decision = intent_service.get_decision_for_organization(db, decision_id, organization_id)
    if decision.outcome != "HUMAN_REVIEW":
        raise DecisionNotHumanReviewError(decision.outcome)

    resolution_row = db.query(DecisionResolution).filter_by(decision_id=decision_id).one_or_none()
    if resolution_row is None:
        raise ReviewNotResolvedError(str(decision_id))
    if resolution_row.resolution != "approved":
        raise ReviewNotApprovedError(resolution_row.resolution)

    intent = db.get(Intent, decision.intent_id)
    logger.info(
        "capability_issuance_basis=POST_REVIEW decision_id=%s resolved_by=%s resolved_by_user_id=%s",
        decision_id, resolution_row.resolved_by, resolution_row.resolved_by_user_id,
    )
    return _issue_and_persist(db, organization_id, decision, intent, audience, issued_by, ttl_seconds)


def _existing_capability_or_none(db: Session, decision_id: uuid.UUID) -> CapabilityToken | None:
    return db.scalar(select(CapabilityToken).where(CapabilityToken.decision_id == decision_id))


def _raise_for_existing_capability(row: CapabilityToken) -> None:
    """Phase 5.1, sections 4/5/6: classifies the Decision's one existing
    Capability row into exactly one of the three deliberately distinct
    outcomes and raises for it -- never falls through to minting a
    second one."""
    if row.consumed_at is not None:
        raise CapabilityAlreadyConsumedForDecisionError(row.id)
    now = datetime.now(timezone.utc)
    expires_at = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if now > expires_at:
        raise CapabilityExpiredNotRenewedError(row.id, expires_at)
    raise CapabilityAlreadyIssuedError(row.id, expires_at)


def _check_agent_active(db: Session, decision_id: uuid.UUID, agent_id: uuid.UUID, *, moment: str) -> Agent:
    """Shared by issuance AND (Phase 6.1) consumption -- see each
    caller's own docstring for why the SAME check applies at both
    moments. `moment` is only for the log line ("ISSUANCE"/
    "CONSUMPTION"), so an operator reading logs can tell which one
    rejected without needing two near-identical log statements."""
    agent = db.get(Agent, agent_id)
    if agent is None or agent.status != "active":
        logger.warning(
            "capability_%s_result=REJECTED_AGENT_NOT_ACTIVE decision_id=%s agent_id=%s status=%s",
            moment, decision_id, agent_id, agent.status if agent else "not_found",
        )
        raise OriginAgentNotActiveError(
            f"decision {decision_id}: agent_id={agent_id} status={agent.status if agent else 'not_found'!r}"
        )
    return agent


def _check_integration_identity_active(
    db: Session, decision_id: uuid.UUID, integration_identity_id: uuid.UUID, *, moment: str
) -> IntegrationIdentity:
    identity = db.get(IntegrationIdentity, integration_identity_id)
    if identity is None or identity.status != "active":
        logger.warning(
            "capability_%s_result=REJECTED_IDENTITY_NOT_ACTIVE decision_id=%s "
            "integration_identity_id=%s status=%s",
            moment, decision_id, integration_identity_id, identity.status if identity else "not_found",
        )
        raise IntegrationIdentityNotActiveError(
            f"decision {decision_id}: integration_identity_id={integration_identity_id} "
            f"status={identity.status if identity else 'not_found'!r}"
        )
    return identity


def _check_enforcement_binding_active(
    db: Session, decision_id: uuid.UUID, enforcement_binding_id: uuid.UUID, *, moment: str
) -> EnforcementBinding:
    binding = db.get(EnforcementBinding, enforcement_binding_id)
    if binding is None or binding.status != "active":
        logger.warning(
            "capability_%s_result=REJECTED_BINDING_NOT_ACTIVE decision_id=%s "
            "enforcement_binding_id=%s status=%s",
            moment, decision_id, enforcement_binding_id, binding.status if binding else "not_found",
        )
        raise EnforcementBindingNotActiveError(
            f"decision {decision_id}: enforcement_binding_id={enforcement_binding_id} "
            f"status={binding.status if binding else 'not_found'!r}"
        )
    return binding


def _check_organization_active(db: Session, decision_id: uuid.UUID, organization_id: uuid.UUID, *, moment: str) -> Organization:
    """Phase 6.1, Part A: added to both issuance and consumption at
    once -- Organization was the one authoritative object neither path
    ever re-checked before this milestone, an inconsistency once every
    other revocable identity already had this exact recheck."""
    org = db.get(Organization, organization_id)
    if org is None or org.status != "active":
        logger.warning(
            "capability_%s_result=REJECTED_TENANT_NOT_ACTIVE decision_id=%s organization_id=%s status=%s",
            moment, decision_id, organization_id, org.status if org else "not_found",
        )
        raise TenantNotActiveError(
            f"decision {decision_id}: organization_id={organization_id} status={org.status if org else 'not_found'!r}"
        )
    return org


def _issue_and_persist(
    db: Session,
    organization_id: uuid.UUID,
    decision,
    intent: Intent,
    audience: str,
    issued_by: str | None,
    ttl_seconds: int,
) -> IssuedCapability:
    """The shared tail every issuance path (ALLOW-direct, post-review)
    converges on: live fail-closed rechecks, then an idempotency-safe
    issue-and-persist. Sharing this one implementation, rather than a
    copy per path, is what section 8 (Agent-direct compatibility) and
    section 17 (post-review issuance reusing Part A's own invariant)
    actually mean structurally -- a fix made once here is a fix made
    everywhere this function is called from, not something that can be
    forgotten on a second, parallel path."""
    decision_id = decision.id

    # Fast pre-check: almost always correct, and avoids doing the live
    # status rechecks and signing work below for a request that's going
    # to be rejected anyway. NOT the actual safety guarantee -- see the
    # IntegrityError handling further down for that.
    existing = _existing_capability_or_none(db, decision_id)
    if existing is not None:
        _raise_for_existing_capability(existing)

    # Trusted Integration Architecture, Phase 5 (fail-closed re-check,
    # section 6/40): applies to BOTH runtime paths, not only the
    # Adapter-mediated one -- the origin Agent's own eligibility can
    # change at any point after its Intent was accepted, independent of
    # any Binding. Phase 6.1: Organization joins this same re-check.
    _check_organization_active(db, decision_id, organization_id, moment="ISSUANCE")
    agent = _check_agent_active(db, decision_id, intent.agent_id, moment="ISSUANCE")

    # Trusted Integration Architecture, Phase 5: the Phase-2 blanket
    # suppression (CapabilityNotAvailableForIntegrationIntentError) is
    # lifted here, but only after re-establishing, live, at the moment
    # of issuance -- never merely trusting the Intent's own historical
    # provenance -- that the trust chain this Capability would extend
    # still actually holds. An Intent's provenance columns are immutable
    # (section 6), but the IntegrationIdentity and EnforcementBinding
    # they name are not: either can be suspended/revoked/retired at any
    # point after the Intent was accepted, and this must fail closed on
    # that, not silently keep minting Capabilities under a trust
    # relationship that no longer exists (section 39).
    integration_identity_id: uuid.UUID | None = None
    enforcement_binding_id: uuid.UUID | None = None
    integration_contract_version_id: uuid.UUID | None = None
    environment: str | None = None
    external_operation_id: str | None = None

    if intent.integration_identity_id is not None:
        identity = _check_integration_identity_active(db, decision_id, intent.integration_identity_id, moment="ISSUANCE")
        binding = _check_enforcement_binding_active(db, decision_id, intent.enforcement_binding_id, moment="ISSUANCE")
        integration_identity_id = identity.id
        enforcement_binding_id = binding.id
        integration_contract_version_id = intent.integration_contract_version_id
        environment = intent.environment
        external_operation_id = intent.external_operation_id

    earliest_evidence = db.scalar(
        select(Evidence).where(Evidence.decision_id == decision.id).order_by(Evidence.created_at.asc()).limit(1)
    )
    payload = earliest_evidence.payload if earliest_evidence else {}
    principal_name = payload.get("principal_name") or ""
    # Domain Generalization Milestone: Intent.resource (db/models.py) is
    # now the real, generic identifier of "which real-world object this
    # action concerns" -- falling back to correlation_id, then the
    # Intent's own row id, only for an older/non-financial-unaware
    # caller that never supplied one, so the bound resource is always
    # concrete and specific either way, never a category.
    resource = intent.resource or intent.correlation_id or str(intent.id)
    # Domain Generalization Milestone: constraints bind whichever
    # execution parameters this decision actually carried, generically
    # -- amount/currency when the action was financial, plus the
    # Intent's own evaluated context (the exact parameters the decision
    # was checked against, so a replayed token can't be presented
    # against substituted parameters), rather than hardcoding amount/
    # currency onto every capability regardless of action. `metadata` is
    # excluded: it's the SDK's own free-form caller-supplied bag, not a
    # parameter Runtime Authority actually evaluated.
    constraints: dict[str, str] = {}
    if intent.amount is not None:
        constraints["amount"] = str(intent.amount)
    if intent.currency is not None:
        constraints["currency"] = intent.currency
    for key, value in (intent.context or {}).items():
        if key == "metadata":
            continue
        constraints[key] = str(value)
    fact_hashes = [
        capability_token.token_hash(str(f)) for f in payload.get("facts_evaluated", [])
    ]

    issued = capability_token.issue_capability_token(
        decision_id=decision.id,
        organization_id=organization_id,
        principal=principal_name,
        action=intent.action,
        resource=resource,
        constraints=constraints,
        policy_version=payload.get("policy_version"),
        fact_hashes=fact_hashes,
        audience=audience,
        ttl_seconds=ttl_seconds,
        signing_key_b64=settings.evidence_signing_key_b64,
        key_id=settings.evidence_signing_key_id,
        integration_identity_id=integration_identity_id,
        enforcement_binding_id=enforcement_binding_id,
        integration_contract_version_id=integration_contract_version_id,
        environment=environment,
        external_operation_id=external_operation_id,
    )

    expires_at = datetime.fromisoformat(issued.payload.expires_at)
    row = CapabilityToken(
        organization_id=organization_id,
        decision_id=decision.id,
        audience=audience,
        nonce=issued.payload.nonce,
        token_hash=issued.token_hash,
        expires_at=expires_at,
        issued_by=issued_by,
        integration_identity_id=integration_identity_id,
        enforcement_binding_id=enforcement_binding_id,
        integration_contract_version_id=integration_contract_version_id,
        environment=environment,
        external_operation_id=external_operation_id,
    )
    db.add(row)
    # Phase 5.1, section 7: the earlier pre-check above is a convenience,
    # not the guarantee -- two concurrent requests can both pass it
    # before either commits. `capability_tokens.decision_id`'s UNIQUE
    # constraint (migration d4e8b1a6f2c9) is what actually makes this
    # safe: the loser's INSERT fails atomically here, and is translated
    # into the same classified error the non-racing pre-check above
    # already raises, instead of escaping as an unhandled IntegrityError
    # -- the exact same discipline resolution_service.resolve_decision's
    # own docstring documents for decision_resolutions.decision_id's
    # identical UNIQUE constraint.
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raced = _existing_capability_or_none(db, decision_id)
        if raced is not None:
            _raise_for_existing_capability(raced)
        raise  # pragma: no cover -- a UNIQUE violation with no row to explain it is unexpected
    db.refresh(row)
    logger.info(
        "capability_issuance_result=ISSUED decision_id=%s capability_id=%s audience=%s "
        "enforcement_binding_id=%s expires_at=%s",
        decision.id, row.id, audience, enforcement_binding_id, expires_at,
    )
    return IssuedCapability(token=issued.token, capability_id=row.id, expires_at=expires_at)


@dataclass(frozen=True)
class ConsumedCapability:
    capability_id: uuid.UUID
    decision_id: uuid.UUID
    resource: str
    constraints: dict


def _check_consumption_freshness(db: Session, row: CapabilityToken) -> None:
    """Phase 6.1, Part A (Authorization Freshness at Capability
    Consumption): Phase 6's own hostile review reconfirmed a real,
    pre-existing gap -- an Agent could be issued a Capability while
    active, then be revoked, and the already-signed Capability remained
    consumable for the rest of its short TTL regardless (proven by
    test_revoked_integration_identity_after_issuance_but_before_
    verification_fails_closed, which documented this honestly rather
    than asserting a guarantee that didn't exist). This function is
    that guarantee, added deliberately, not assumed.

    The freshness boundary, drawn precisely (section 6 of this
    milestone's own brief): this re-checks whether the revocable
    identities and bindings a Capability depends on are STILL eligible
    right now, using the exact same "is a real, live authoritative
    object active" checks issuance already performs -- reusing
    _check_agent_active/_check_organization_active/
    _check_integration_identity_active/_check_enforcement_binding_active
    unchanged, not a copy. It deliberately does NOT re-run Runtime
    Authority evaluation, re-check the original RuntimePolicy, or
    re-verify Trusted Enterprise Facts: those determined whether the
    action was authorized under the authority state that existed at
    Decision time, a question this Capability's own signed payload
    already answers immutably. Turning verification into a second full
    policy evaluation would be a materially different, larger
    architecture this milestone's own brief explicitly warns against
    inventing without proof it's necessary -- no such proof exists here,
    and the smaller, precise freshness check below is what section 6
    calls "the smallest clear freshness boundary."

    The Capability's own signed claims (decision_id, organization_id,
    integration_identity_id, enforcement_binding_id, ...) are read
    verbatim and never mutated -- this is live validation against
    CURRENT state, not retroactive rewriting of what was true at
    issuance (section 5's own distinction).

    Ordering is the actual safety property here, not an implementation
    detail: this function is called (see verify_and_consume_capability)
    strictly BEFORE the atomic consume UPDATE, in the same, uncommitted
    transaction. A failed check here returns via a raised exception
    with no write to `consumed_at` having happened at all -- the token
    remains exactly as usable (or not) as it was before this call, so a
    caller who retries after the underlying state is restored (e.g. an
    Agent un-suspended within the Capability's remaining TTL) gets a
    fresh, correctly-current answer, not a token permanently burned by
    a transient failure. This is a deliberate choice, stated explicitly
    per this milestone's own instruction not to leave it ambiguous: a
    freshness failure is never itself a consumption event."""
    decision = db.get(Decision, row.decision_id)
    intent = db.get(Intent, decision.intent_id)

    _check_organization_active(db, row.decision_id, row.organization_id, moment="CONSUMPTION")
    _check_agent_active(db, row.decision_id, intent.agent_id, moment="CONSUMPTION")

    if row.integration_identity_id is not None:
        _check_integration_identity_active(db, row.decision_id, row.integration_identity_id, moment="CONSUMPTION")
    if row.enforcement_binding_id is not None:
        _check_enforcement_binding_active(db, row.decision_id, row.enforcement_binding_id, moment="CONSUMPTION")


def verify_and_consume_capability(
    db: Session,
    token: str,
    audience: str,
    action: str,
    resource: str,
    constraints: dict,
    environment: str | None = None,
    enforcement_binding_id: uuid.UUID | None = None,
    principal: str | None = None,
    expected_organization_id: uuid.UUID | None = None,
) -> ConsumedCapability:
    """Online verify-and-consume (PAYREALITY_FUTURE_VISION.md Part C's
    own explicit scoping: this milestone is online verify-and-consume,
    not offline verification -- a future offline-verification design is
    a distinct, NOT-built-here architecture). Signature/expiry/tenant/
    audience/parameter checks happen inside domain/capability/token.py
    first; this function's own job is looking up the persisted row by
    the token's own hash and atomically marking it consumed, so two
    concurrent presentations of the same token cannot both succeed.

    Trusted Integration Architecture, Phase 5: `environment`/
    `enforcement_binding_id`/`principal` are all optional (sections 6/9)
    -- a PEP that knows which Runtime Connection, environment, or Agent
    it expects may pin any of them; a PEP that supplies none skips those
    checks entirely, exactly as every pre-Phase-5 Agent-direct verifier
    already does.

    Phase 6.1, Part B: `expected_organization_id` is also optional here
    for the same backward-compatible reason, but routers/capability_
    tokens.py's own real, production-facing endpoint always supplies it
    now -- see that router's own docstring for why."""
    envelope_hash = capability_token.token_hash(token)
    row = db.scalar(select(CapabilityToken).where(CapabilityToken.token_hash == envelope_hash))
    if row is None:
        raise CapabilityTokenNotFoundError("no matching issued capability")

    key_id = _extract_key_id(token)
    public_key = signing_key_service.get_public_key_for_key_id(db, key_id)
    if public_key is None:
        raise capability_token.InvalidCapabilityTokenError(f"unknown signing key_id={key_id!r}")

    verified = capability_token.verify_capability_token(
        token, public_key_b64=public_key, expected_audience=audience, expected_action=action,
        expected_resource=resource, expected_constraints=constraints,
        expected_environment=environment, expected_enforcement_binding_id=enforcement_binding_id,
        expected_organization_id=expected_organization_id,
        expected_principal=principal,
    )

    # Phase 6.1, Part A (Authorization Freshness at Capability
    # Consumption): re-checks live status BEFORE the atomic consume
    # below, never after -- see _check_consumption_freshness's own
    # docstring for the full reasoning, the freshness boundary this
    # deliberately does and does not cover, and why the ordering here is
    # itself the safety property (a failed freshness check must never
    # mark this token consumed).
    _check_consumption_freshness(db, row)

    # Atomic single-use consumption: an UPDATE ... WHERE consumed_at IS
    # NULL affects exactly one row the first time and zero rows on any
    # concurrent or later attempt, so two simultaneous requests can never
    # both observe success -- the same guarantee Intent's own
    # UNIQUE(agent_id, nonce) constraint gives for replay, expressed as a
    # conditional update instead of an insert-conflict.
    from sqlalchemy import update

    result = db.execute(
        update(CapabilityToken)
        .where(CapabilityToken.id == row.id, CapabilityToken.consumed_at.is_(None))
        .values(consumed_at=datetime.now(timezone.utc))
    )
    db.commit()
    if result.rowcount == 0:
        # A second (or racing) presentation of an already-consumed
        # token -- exactly the replay/double-consumption signal
        # observability needs to distinguish from ordinary failed
        # verification. Never logs the token itself, only its
        # capability_id, which is not secret (the token_hash it's
        # looked up by is a one-way hash, never the bearer artifact).
        logger.warning("capability_consumption_result=ALREADY_CONSUMED capability_id=%s", row.id)
        raise CapabilityTokenAlreadyConsumedError(str(row.id))

    logger.info(
        "capability_consumption_result=CONSUMED capability_id=%s decision_id=%s audience=%s",
        row.id, verified.payload.decision_id, audience,
    )
    return ConsumedCapability(
        capability_id=row.id, decision_id=verified.payload.decision_id,
        resource=verified.payload.resource, constraints=verified.payload.constraints,
    )


def _extract_key_id(token: str) -> str:
    import base64
    import json

    envelope = json.loads(base64.b64decode(token))
    return envelope["key_id"]
