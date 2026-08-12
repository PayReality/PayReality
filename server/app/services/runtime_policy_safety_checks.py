"""Runtime Authority Safety Checks (Phase 5, RUNTIME_POLICY_LIFECYCLE.md
section 6): the gate `activate_policy()` must pass before it is allowed
to call the existing, unmodified `runtime_policy_service.deploy_policy()`.

Explicit instruction from the Phase 5 prompt: "Reuse existing validation.
Never duplicate logic." Concretely:

 - Circular delegation detection reuses
   `ai_authority_builder_service.detect_circular_delegations()` completely
   unchanged, by constructing synthetic `CandidateRelationship` values
   from `Constraints.delegated_by` chains across the policy set that
   would be active immediately after this activation (the candidate plus
   every OTHER currently-active policy). That function has no idea these
   relationships came from RuntimePolicy constraints rather than an
   Authority Builder corpus, which is exactly the point: it operates on
   the same tiny (from, to, kind) shape either way.
 - Structural/threshold validation reuses
   `domain/runtime_policy/validators.validate()` completely unchanged.

Everything else here (duplicate authority, broken inheritance, missing
principal) is new, narrow, deterministic code -- there was no existing
equivalent to reuse for these three.

This module is read-only: it never writes to the database and never
raises for "the policy is unsafe to activate" (that is exactly what
SafetyCheckResult.violations is for, the same "always return a result,
never raise for a normal validation failure" discipline
`runtime_policy.validators` already holds itself to). An exception out of
`run_safety_checks` means a genuine programming error, not "this policy
failed a safety check."

Lives in `services/`, not `domain/`, because it takes a live `Session`
and queries `RuntimePolicyRecord`/`Principal` directly -- `domain/` is a
hard, test-enforced boundary in this codebase
(tests/unit/test_architectural_boundaries.py's
test_domain_package_never_imports_app_db) that nothing importing
`app.db` may cross, the same reason `detect_circular_delegations` itself
(DB-adjacent, though it takes a pure `AuthorityGraph` rather than a
`Session`) lives in `services/ai_authority_builder_service.py` and not
under `domain/ai_authority_builder/`.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Principal, RuntimePolicyRecord
from app.domain.ai_authority_builder.provider import AuthorityGraph, CandidateRelationship
from app.domain.runtime_policy import validators
from app.domain.runtime_policy.runtime_policy import RuntimePolicy
from app.domain.runtime_policy.schema import from_dict
from app.services.ai_authority_builder_service import detect_circular_delegations


@dataclass(frozen=True)
class SafetyViolation:
    check: str
    message: str
    details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SafetyCheckResult:
    violations: tuple[SafetyViolation, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return len(self.violations) == 0


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def _other_active_runtime_policies(db: Session, exclude_policy_key: uuid.UUID) -> list[RuntimePolicyRecord]:
    return list(
        db.scalars(
            select(RuntimePolicyRecord).where(
                RuntimePolicyRecord.status == "active",
                RuntimePolicyRecord.policy_key != exclude_policy_key,
            )
        )
    )


def _condition_signature(policy: RuntimePolicy) -> tuple:
    return tuple(
        sorted((c.field, c.operator.value, repr(c.value)) for c in (policy.conditions.all if policy.conditions else ()))
    )


def _authority_signature(policy: RuntimePolicy) -> tuple:
    """Two policies with an identical signature govern the exact same
    principal/action/resource/agent under the exact same conditions and
    effect -- an unambiguous duplicate, not two legitimately different
    tiers of the same authority (e.g. "under $50k" vs "over $50k", which
    differ in their conditions and therefore their signature)."""
    return (
        policy.scope.principal,
        policy.scope.action,
        policy.scope.agent,
        policy.scope.resource,
        policy.effect.value,
        _condition_signature(policy),
    )


def _check_duplicate_authority(
    candidate: RuntimePolicy, candidate_key: uuid.UUID, others: list[tuple[uuid.UUID, RuntimePolicy]]
) -> list[SafetyViolation]:
    candidate_sig = _authority_signature(candidate)
    violations = []
    for other_key, other_policy in others:
        if _authority_signature(other_policy) == candidate_sig:
            violations.append(
                SafetyViolation(
                    check="duplicate_authority",
                    message=(
                        f"An identical authority (same principal, action, resource, effect, and "
                        f"conditions) is already active under a different policy "
                        f"({other_key})."
                    ),
                    details={"conflicting_policy_key": str(other_key)},
                )
            )
    return violations


def _known_principal_names(policies: list[RuntimePolicy]) -> set[str]:
    return {p.scope.principal.strip().lower() for p in policies if p.scope.principal}


def _check_broken_inheritance(
    db: Session, candidate: RuntimePolicy, all_policies: list[RuntimePolicy]
) -> list[SafetyViolation]:
    delegated_by = candidate.constraints.delegated_by
    if not delegated_by:
        return []

    known_names = _known_principal_names(all_policies)
    if delegated_by.strip().lower() in known_names:
        return []

    if _is_uuid(delegated_by):
        if db.get(Principal, uuid.UUID(delegated_by)) is not None:
            return []
    else:
        if db.scalar(select(Principal).where(Principal.name.ilike(delegated_by.strip()))) is not None:
            return []

    return [
        SafetyViolation(
            check="broken_inheritance",
            message=(
                f"This policy delegates from '{delegated_by}', which is not scoped by any other "
                "active policy and does not resolve to a known Principal -- the delegation chain "
                "would be broken if this policy activates."
            ),
            details={"delegated_by": delegated_by},
        )
    ]


def _check_missing_principal(db: Session, candidate: RuntimePolicy) -> list[SafetyViolation]:
    """Only enforceable when scope.principal is a Principal id (the AI
    Authority Builder promotion path) -- a manually-authored RuntimePolicy
    is free to name its principal as plain text (Policy Studio's guided
    wizard predates the Principal model and remains fully supported), and
    there is no way to verify a free-text name against a real entity, the
    same tolerance `diff_versions`/`resolve_mandate_ids` already apply to
    this exact field."""
    principal = candidate.scope.principal
    if not principal or not _is_uuid(principal):
        return []
    if db.get(Principal, uuid.UUID(principal)) is not None:
        return []
    return [
        SafetyViolation(
            check="missing_principal",
            message=f"scope.principal '{principal}' does not resolve to any existing Principal.",
            details={"principal": principal},
        )
    ]


def _check_circular_delegation(all_policies: list[RuntimePolicy]) -> list[SafetyViolation]:
    relationships = tuple(
        CandidateRelationship(
            kind="delegation",
            from_principal=p.constraints.delegated_by,
            to_principal=p.scope.principal,
            confidence=1.0,
            source_excerpt="",
            source_location="runtime_policy_lifecycle.safety_checks",
        )
        for p in all_policies
        if p.constraints.delegated_by and p.scope.principal
    )
    if not relationships:
        return []

    graph = AuthorityGraph(relationships=relationships)
    conflicts = detect_circular_delegations(graph)
    return [
        SafetyViolation(check="circular_delegation", message=conflict.description, details={})
        for conflict in conflicts
    ]


def _check_invalid_thresholds(candidate: RuntimePolicy) -> list[SafetyViolation]:
    result = validators.validate(candidate)
    violations = []
    for error in result.errors:
        check = "invalid_threshold" if error.code == "OPERATOR_VALUE_MISMATCH" else "invalid_policy_structure"
        violations.append(
            SafetyViolation(
                check=check,
                message=error.message,
                details={"field": error.field, "code": error.code},
            )
        )
    return violations


def run_safety_checks(db: Session, policy_key: uuid.UUID, candidate_row: RuntimePolicyRecord) -> SafetyCheckResult:
    """Everything `activate_policy()` must pass before it may call the
    existing `deploy_policy()`. `candidate_row` is the version about to be
    activated; it is read, never written, by this function."""
    candidate = from_dict(candidate_row.content)
    other_rows = _other_active_runtime_policies(db, policy_key)
    others = [(row.policy_key, from_dict(row.content)) for row in other_rows]
    all_policies = [candidate] + [p for _, p in others]

    violations: list[SafetyViolation] = []
    violations.extend(_check_invalid_thresholds(candidate))
    violations.extend(_check_duplicate_authority(candidate, policy_key, others))
    violations.extend(_check_broken_inheritance(db, candidate, all_policies))
    violations.extend(_check_missing_principal(db, candidate))
    violations.extend(_check_circular_delegation(all_policies))

    return SafetyCheckResult(violations=tuple(violations))
