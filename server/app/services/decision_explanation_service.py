"""Phase 2B (PHASE_2B_LIVE_PER_CONDITION_EXPLAINABILITY_SUMMARY.md): the
explanatory path, kept entirely separate from the authoritative one.

This module answers "exactly which policy conditions caused this
decision?" by reconstructing the historical policy state Historical
Policy Binding (Policy.bundle_manifest) already made durable, then
running the existing, unmodified Runtime Policy Simulator explainer
(domain/policy_simulation/explainer.build_rule_evaluations) against it.
It does not call an LLM, does not re-run OPA, does not create a second
decision, and never writes anything: every function here only reads
Decision/Evidence/Policy/RuntimePolicyRecord rows that already exist.
The OPA-computed Decision (domain/decision/engine.py, untouched) remains
the sole source of truth for allow/deny/review; this only explains it.

Deliberately conservative about what counts as reconstructable: if any
step below can't be done from durably persisted data, this returns an
explicit `ExplanationUnavailable` with a real reason code rather than
guessing or silently substituting today's active policy for the one
that actually governed the decision.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import Evidence, Intent, Policy, RuntimePolicyRecord
from app.domain.policy_simulation.explainer import RuleEvaluation, build_rule_evaluations
from app.services import intent_service
from app.services.runtime_policy_service import _row_to_policy

# Decision.reason values meaning OPA itself never produced a real
# answer (domain/decision/engine.py's own OPATimeoutError/
# OPAEvaluationError branches). Reconstructing per-condition results
# for one of these would show what the compiled policy *would* have
# said, not what actually happened -- the actual event was a system
# failure to evaluate at all, so this is marked unavailable rather
# than presented as if it were the real explanation.
_NO_REAL_EVALUATION_REASONS = {"opa_timeout"}


def _is_unevaluated_reason(reason: str | None) -> bool:
    if reason is None:
        return False
    return reason in _NO_REAL_EVALUATION_REASONS or reason.startswith("opa_error:")


class DecisionNotFoundError(Exception):
    pass


class CrossOrganizationAccessError(Exception):
    """Raised when the bound Policy belongs to a different organization
    than the caller's. The router turns this into the same 404 as
    decision_not_found (never a 403), matching
    get_decision_policy_binding's existing discipline: a cross-org
    caller can't distinguish "wrong organization" from "doesn't
    exist."""


@dataclass(frozen=True)
class ExplanationUnavailable:
    decision_id: uuid.UUID
    reason: str


@dataclass(frozen=True)
class DecisionExplanation:
    decision_id: uuid.UUID
    outcome: str
    reason: str | None
    policy_id: uuid.UUID
    bundle_hash: str
    bundle_version: int
    compiled_at: datetime | None
    activated_at: datetime | None
    retired_at: datetime | None
    evaluated_at: datetime
    rules: tuple[RuleEvaluation, ...]
    # The one rule (if any) whose match actually determined the
    # outcome: policy.id in Decision.evaluated_mandates already tells
    # us this without recomputing anything (see build_rule_evaluations'
    # `matched`, itself read straight from evaluated_mandates).
    causal_policy_id: str | None


def get_decision_explanation(
    db: Session, decision_id: uuid.UUID, organization_id: uuid.UUID | None
) -> DecisionExplanation | ExplanationUnavailable:
    decision = intent_service.get_decision(db, decision_id)
    if decision is None:
        raise DecisionNotFoundError(str(decision_id))

    if decision.policy_id is None:
        # No active policy existed at all when this decision was made
        # (domain/decision/engine.py's NoActivePolicyError branch) --
        # there is no bundle, no manifest, nothing to reconstruct.
        return ExplanationUnavailable(decision_id=decision.id, reason="no_policy_evaluated")

    if _is_unevaluated_reason(decision.reason):
        return ExplanationUnavailable(decision_id=decision.id, reason="evaluation_did_not_complete")

    policy = db.get(Policy, decision.policy_id)
    if policy is None:
        # Decision.policy_id is a real FK to an immutable, never-deleted
        # row; reaching here would mean that invariant broke somewhere
        # else in the system, not something to paper over here.
        return ExplanationUnavailable(decision_id=decision.id, reason="bundle_not_found")
    if policy.organization_id != organization_id:
        raise CrossOrganizationAccessError(str(decision_id))

    manifest_policies = (policy.bundle_manifest or {}).get("policies") or []
    if not manifest_policies:
        # A real bundle exists, but it predates Policy.bundle_manifest
        # (Historical Policy Binding) -- no backfill is possible for
        # these (HISTORICAL_POLICY_BINDING_IMPLEMENTATION.md), so this
        # is a real, permanent limitation for old decisions, not a bug.
        return ExplanationUnavailable(decision_id=decision.id, reason="bundle_manifest_not_available")

    earliest_evidence = (
        db.query(Evidence)
        .filter(Evidence.decision_id == decision.id)
        .order_by(Evidence.created_at.asc(), Evidence.id.asc())
        .first()
    )
    if earliest_evidence is None:
        return ExplanationUnavailable(decision_id=decision.id, reason="evidence_not_available")

    payload = earliest_evidence.payload
    principal_name = payload.get("principal_name")
    if not principal_name:
        return ExplanationUnavailable(decision_id=decision.id, reason="principal_not_resolved")

    intent = db.get(Intent, decision.intent_id)

    reconstructed_policies = []
    for entry in manifest_policies:
        record = (
            db.query(RuntimePolicyRecord)
            .filter_by(policy_key=uuid.UUID(entry["id"]), version=entry["version"])
            .one_or_none()
        )
        if record is None:
            # RuntimePolicyRecord rows are never deleted; reaching here
            # would mean the manifest names a row that doesn't exist,
            # an integrity problem worth surfacing honestly rather than
            # silently reconstructing a partial, misleading rule list.
            return ExplanationUnavailable(decision_id=decision.id, reason="historical_policy_record_missing")
        reconstructed_policies.append(_row_to_policy(record))

    # Domain Generalization Milestone: amount/currency/resource are all
    # genuinely nullable on Intent -- included only when actually
    # present, rather than an unconditional float(intent.amount) that
    # raised TypeError the moment a non-financial decision (no amount
    # at all) was reconstructed here.
    reconstructed_intent: dict = {"action": intent.action}
    if intent.amount is not None:
        reconstructed_intent["amount"] = float(intent.amount)
    if intent.currency is not None:
        reconstructed_intent["currency"] = intent.currency
    if intent.resource is not None:
        reconstructed_intent["resource"] = intent.resource
    reconstructed_context = {**(intent.context or {}), "authority": payload.get("authority_context")}

    rules = build_rule_evaluations(
        policies=reconstructed_policies,
        intent=reconstructed_intent,
        context=reconstructed_context,
        acting_for_principal_id=principal_name,
        evaluated_mandates=decision.evaluated_mandates or [],
    )

    causal_rule = next((r for r in rules if r.matched), None)

    return DecisionExplanation(
        decision_id=decision.id,
        outcome=decision.outcome,
        reason=decision.reason,
        policy_id=policy.id,
        bundle_hash=policy.bundle_hash,
        bundle_version=policy.version,
        compiled_at=policy.compiled_at,
        activated_at=policy.activated_at,
        retired_at=policy.retired_at,
        evaluated_at=decision.created_at,
        rules=tuple(rules),
        causal_policy_id=causal_rule.policy_id if causal_rule else None,
    )
