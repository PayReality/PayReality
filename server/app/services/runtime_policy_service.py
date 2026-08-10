"""Policy Studio's service layer: bridges the new `runtime_policy_records`
table to the unmodified domain/runtime_policy/ and domain/compiler_v2/
packages (POLICY_STUDIO_ARCHITECTURE.md). Neither package is imported for
anything but its existing public functions and dataclasses.

Unlike compiler_v2 and runtime_policy/validators.py (which never raise
for a normal validation failure, by design), this module follows the
existing service-layer convention already established by policy_service.py
and intent_service.py: raise a specific exception for "not found" or "the
wrong status for this transition," which the router catches and maps to
an HTTP status code. That's a router-facing convention, not a validation
one; the two are not in tension.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Agent, Authority, EnterpriseSystem, Mandate, Policy, RuntimePolicyRecord
from app.domain.compiler_v2.compiler_errors import CompilerDiagnostics
from app.domain.compiler_v2.compiler_v2 import compile_bundle
from app.domain.compiler_v2.dry_run import DryRunResult, dry_run as run_dry_run
from app.domain.runtime_policy.conditions import Operator
from app.domain.runtime_policy.runtime_policy import RuntimePolicy
from app.domain.runtime_policy.schema import from_dict, to_dict
from app.opa_client import HttpOpaClient

_NUMERIC_OPERATORS = {Operator.LTE, Operator.GTE, Operator.LT, Operator.GT}


class RuntimePolicyNotFoundError(Exception):
    pass


class InvalidTransitionError(Exception):
    def __init__(self, from_status: str, action: str):
        self.from_status = from_status
        self.action = action
        super().__init__(f"cannot {action} a policy in status '{from_status}'")


class CompilationRequiredError(Exception):
    """Raised by dry_run/deploy when the requested version has never been
    compiled (compile stores the bundle info this needs)."""


class BundleChangedSinceCompileError(Exception):
    """Deploy recompiles (recompilation is deterministic, see
    COMPILER_V2_ARCHITECTURE.md) and compares the resulting bundle_hash
    against what was stored at compile time, refusing to deploy if
    another policy's active set changed in between, rather than silently
    deploying something that was never actually reviewed."""


class UnexpectedActiveWriterError(Exception):
    """Raised by deploy_policy if the currently-active Policy row wasn't
    written by this same function (bundle_uri doesn't match this
    module's own "runtime_policy_studio:..." format). This module and
    the legacy domain/compiler/compiler.py + services/policy_service.py
    pipeline both used to be able to write to the exact same OPA package
    and the exact same active-Policy-row slot with zero coordination --
    the legacy pipeline's authoring surface is now retired (see
    routers/policies.py), but this check is defense in depth against any
    writer this module isn't aware of, present or future: fail loudly
    rather than silently overwrite something deploy_policy didn't itself
    put there."""


_EXPECTED_BUNDLE_URI_PREFIX = "runtime_policy_studio:"


def _latest_version_row(db: Session, policy_key: uuid.UUID) -> RuntimePolicyRecord | None:
    return db.scalar(
        select(RuntimePolicyRecord)
        .where(RuntimePolicyRecord.policy_key == policy_key)
        .order_by(RuntimePolicyRecord.version.desc())
        .limit(1)
    )


def _row_to_policy(row: RuntimePolicyRecord) -> RuntimePolicy:
    return from_dict(row.content)


def list_latest_policies(db: Session, status: str | None = None) -> list[RuntimePolicyRecord]:
    """One row per policy_key: its latest version, matching the Policy
    List / Review Queue pages (POLICY_STUDIO_WIREFRAMES.md)."""
    all_rows = list(db.scalars(select(RuntimePolicyRecord).order_by(RuntimePolicyRecord.version.desc())))
    latest_by_key: dict[uuid.UUID, RuntimePolicyRecord] = {}
    for row in all_rows:
        if row.policy_key not in latest_by_key:
            latest_by_key[row.policy_key] = row
    results = list(latest_by_key.values())
    if status is not None:
        results = [r for r in results if r.status == status]
    return results


def list_policies_for_principal(db: Session, principal_name: str) -> list[RuntimePolicyRecord]:
    """Agent Detail Page's "Runtime Policies" section (AGENT_LIFECYCLE.md):
    a policy applies to an agent via its acting-for Principal's name,
    stored as scope.principal inside RuntimePolicyRecord.content (there is
    no direct agent<->policy foreign key, matching this codebase's
    no-ORM-relationship, plain-FK style -- filtered in Python rather than
    a JSONB query, same approach list_latest_policies itself already
    takes and consistent at today's scale)."""
    return [
        row for row in list_latest_policies(db)
        if row.content.get("scope", {}).get("principal") == principal_name
    ]


def get_latest(db: Session, policy_key: uuid.UUID) -> RuntimePolicyRecord:
    row = _latest_version_row(db, policy_key)
    if row is None:
        raise RuntimePolicyNotFoundError(str(policy_key))
    return row


def resolve_mandate_ids(db: Session, policy_keys: list[str]) -> list[str]:
    """Authority-as-a-continuous-object, Stage H: `policy_keys` is
    decision_engine.evaluate()'s `evaluated_mandates` output -- despite
    the name, these are RuntimePolicy policy_key strings
    (bundle_builder.py's own `evaluated_mandates contains {policy.id}`
    rule, where `policy.id` is a RuntimePolicy's id, i.e. its
    policy_key), not real Mandate ids. This resolves each key's ACTIVE
    record and reads back whatever real Mandate Stage G's
    `_ensure_mandate` already stamped into its constraints at deploy
    time. A RuntimePolicy deployed before Stage G existed, or one whose
    Authority Builder principal was never resolved, simply contributes
    nothing here -- additive, never a hard requirement."""
    mandate_ids: list[str] = []
    for key in policy_keys:
        try:
            policy_key = uuid.UUID(key)
        except ValueError:
            continue
        row = db.scalar(
            select(RuntimePolicyRecord).where(
                RuntimePolicyRecord.policy_key == policy_key,
                RuntimePolicyRecord.status == "active",
            )
        )
        if row is None:
            continue
        mandate_id = (row.content.get("constraints") or {}).get("mandate_id")
        if mandate_id and mandate_id not in mandate_ids:
            mandate_ids.append(mandate_id)
    return mandate_ids


def resolve_enterprise_system(db: Session, policy_keys: list[str]) -> EnterpriseSystem | None:
    """Phase 5, Release 2: the Enterprise System binding mechanism. Same
    shape as resolve_mandate_ids above -- reads back a value a reviewer
    already configured on the matched policy's own constraints
    (Constraints.enterprise_system_id), reusing the exact ACTIVE-record
    lookup pattern. Never inferred: a policy with no configured
    enterprise_system_id, or one pointing at a since-deleted
    EnterpriseSystem row, contributes nothing.

    Deterministic tie-break: `policy_keys` is decision_engine.evaluate()'s
    own `evaluated_mandates` output, in its own order; the first matched
    policy that both configures a value AND still references a real row
    wins. A Decision has exactly one enterprise_system_id (unlike
    evaluated_mandate_ids, which is a list), so this returns at most one
    row rather than collecting every match."""
    for key in policy_keys:
        try:
            policy_key = uuid.UUID(key)
        except ValueError:
            continue
        row = db.scalar(
            select(RuntimePolicyRecord).where(
                RuntimePolicyRecord.policy_key == policy_key,
                RuntimePolicyRecord.status == "active",
            )
        )
        if row is None:
            continue
        enterprise_system_id = (row.content.get("constraints") or {}).get("enterprise_system_id")
        if not enterprise_system_id:
            continue
        try:
            system = db.get(EnterpriseSystem, uuid.UUID(enterprise_system_id))
        except ValueError:
            continue
        if system is not None:
            return system
    return None


def list_versions(db: Session, policy_key: uuid.UUID) -> list[RuntimePolicyRecord]:
    rows = list(
        db.scalars(
            select(RuntimePolicyRecord)
            .where(RuntimePolicyRecord.policy_key == policy_key)
            .order_by(RuntimePolicyRecord.version.desc())
        )
    )
    if not rows:
        raise RuntimePolicyNotFoundError(str(policy_key))
    return rows


def get_version(db: Session, policy_key: uuid.UUID, version: int) -> RuntimePolicyRecord:
    row = db.scalar(
        select(RuntimePolicyRecord).where(
            RuntimePolicyRecord.policy_key == policy_key, RuntimePolicyRecord.version == version
        )
    )
    if row is None:
        raise RuntimePolicyNotFoundError(f"{policy_key} v{version}")
    return row


def create_policy(db: Session, policy: RuntimePolicy) -> RuntimePolicyRecord:
    """Always version 1, status draft, a fresh policy_key. `policy.id` is
    used as-is for policy_key if it parses as a UUID, otherwise one is
    generated; callers (the router) are expected to have already run
    runtime_policy.validators.validate() before this is called."""
    try:
        policy_key = uuid.UUID(policy.id)
    except ValueError:
        policy_key = uuid.uuid4()

    row = RuntimePolicyRecord(
        id=uuid.uuid4(),
        policy_key=policy_key,
        version=1,
        status="draft",
        content=to_dict(policy),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def edit_policy(db: Session, policy_key: uuid.UUID, updated_policy: RuntimePolicy) -> RuntimePolicyRecord:
    """Always creates a new draft version; never mutates an existing row
    (RUNTIME_POLICY_LANGUAGE.md's immutability, POLICY_STUDIO_WORKFLOW.md's
    "edit always produces a new draft version")."""
    latest = get_latest(db, policy_key)
    new_version = latest.version + 1
    row = RuntimePolicyRecord(
        id=uuid.uuid4(),
        policy_key=policy_key,
        version=new_version,
        status="draft",
        content=to_dict(updated_policy),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def submit_for_review(db: Session, policy_key: uuid.UUID) -> RuntimePolicyRecord:
    row = get_latest(db, policy_key)
    if row.status != "draft":
        raise InvalidTransitionError(row.status, "submit for review")
    row.status = "pending_review"
    db.commit()
    db.refresh(row)
    return row


def approve(
    db: Session,
    policy_key: uuid.UUID,
    approver: str,
    approver_user_id: uuid.UUID | None = None,
) -> RuntimePolicyRecord:
    """Authority-as-a-continuous-object, Stage D: `approver` (free text)
    stays exactly what every existing reader displays. `approver_user_id`
    is additive, populated only when the caller resolved a real session
    user (see dependencies.get_current_user_if_session); None for the
    Operator Key or a bare API key, both of which remain fully supported."""
    row = get_latest(db, policy_key)
    if row.status != "pending_review":
        raise InvalidTransitionError(row.status, "approve")
    content = dict(row.content)
    audit = dict(content.get("audit") or {})
    audit["approved"] = datetime.now(timezone.utc).isoformat()
    audit["approved_by"] = approver
    audit["approved_by_user_id"] = str(approver_user_id) if approver_user_id else None
    content["audit"] = audit
    row.content = content
    row.status = "approved"
    db.commit()
    db.refresh(row)
    return row


def reject(
    db: Session,
    policy_key: uuid.UUID,
    reviewer: str,
    reason: str,
    reviewer_user_id: uuid.UUID | None = None,
) -> RuntimePolicyRecord:
    row = get_latest(db, policy_key)
    if row.status != "pending_review":
        raise InvalidTransitionError(row.status, "reject")
    if not reason or not reason.strip():
        raise ValueError("a rejection reason is required")
    # Incidental correctness fix found while wiring Stage D: neither the
    # reviewer nor the reason this function already validates was ever
    # persisted anywhere. Recorded the same way approve() already does,
    # rather than adding a real identity field to an audit trail entry
    # that didn't otherwise exist.
    content = dict(row.content)
    audit = dict(content.get("audit") or {})
    audit["rejected"] = datetime.now(timezone.utc).isoformat()
    audit["rejected_by"] = reviewer
    audit["rejected_by_user_id"] = str(reviewer_user_id) if reviewer_user_id else None
    audit["rejection_reason"] = reason
    content["audit"] = audit
    row.content = content
    row.status = "rejected"
    db.commit()
    db.refresh(row)
    return row


def _bundle_id_for(policy_key: uuid.UUID, version: int) -> str:
    return f"bundle_{policy_key.hex}_{version}"


def reconcile_opa_with_active_policies(db: Session, opa_url: str = "http://localhost:8181") -> bool:
    """Re-pushes every currently-active RuntimePolicy to OPA's live
    "authorization" package. Meant to be called once at process startup
    (app.main.lifespan), because OPA's REST-loaded policies live only in
    its own process memory: PayReality runs OPA embedded in this same
    container, on a plan that idle-spins-down and cold-restarts, and
    nothing else re-uploads the active bundle after a restart. Without
    this, every real Intent after a restart silently evaluates against
    an undefined "authorization" package (HttpOpaClient.query returns
    `{}`, which decision.engine.evaluate reads as outcome="HUMAN_REVIEW",
    reason="undetermined") -- indistinguishable from a legitimate
    "nothing matched" result unless you already know to suspect it.

    Returns False (no-op) when there is nothing active to push: that's
    the correct, distinct "no_active_policy" state the legacy Policy
    table's own active-row check already reports."""
    active_rows = list(db.scalars(select(RuntimePolicyRecord).where(RuntimePolicyRecord.status == "active")))
    if not active_rows:
        return False

    policies = [_row_to_policy(r) for r in active_rows]
    result = compile_bundle(policies, bundle_id="startup-reconcile", bundle_version=1)
    if not result.ok:
        raise CompilationRequiredError(
            "active RuntimePolicy set no longer compiles cleanly; cannot reconcile OPA at startup"
        )

    HttpOpaClient(base_url=opa_url).upload_policy("authorization", result.bundle.rego_source)
    return True


def _other_active_policies(db: Session, exclude_policy_key: uuid.UUID) -> list[RuntimePolicy]:
    """Compiling one policy compiles it together with every other
    currently-active policy (POLICY_STUDIO_ARCHITECTURE.md): deploying a
    single-policy edit must not silently drop every other rule already
    governing real traffic."""
    active_rows = list(
        db.scalars(
            select(RuntimePolicyRecord).where(
                RuntimePolicyRecord.status == "active",
                RuntimePolicyRecord.policy_key != exclude_policy_key,
            )
        )
    )
    return [_row_to_policy(r) for r in active_rows]


@dataclass(frozen=True)
class CompileOutcome:
    record: RuntimePolicyRecord
    diagnostics: CompilerDiagnostics
    bundle_id: str | None
    bundle_hash: str | None

    @property
    def ok(self) -> bool:
        return self.diagnostics.ok


def compile_policy(db: Session, policy_key: uuid.UUID) -> CompileOutcome:
    row = get_latest(db, policy_key)
    if row.status != "approved":
        raise InvalidTransitionError(row.status, "compile")

    this_policy = _row_to_policy(row)
    bundle_policies = [this_policy] + _other_active_policies(db, policy_key)
    bundle_id = _bundle_id_for(policy_key, row.version)

    result = compile_bundle(bundle_policies, bundle_id=bundle_id, bundle_version=row.version)

    if not result.ok:
        return CompileOutcome(record=row, diagnostics=result.diagnostics, bundle_id=None, bundle_hash=None)

    row.status = "compiled"
    row.bundle_id = result.bundle.bundle_id
    row.bundle_hash = result.bundle.bundle_hash
    db.commit()
    db.refresh(row)
    return CompileOutcome(
        record=row, diagnostics=result.diagnostics, bundle_id=row.bundle_id, bundle_hash=row.bundle_hash
    )


def dry_run_policy(
    db: Session, policy_key: uuid.UUID, sample_input: dict, opa_url: str = "http://localhost:8181"
) -> DryRunResult:
    row = get_latest(db, policy_key)
    if row.status not in ("compiled", "active"):
        raise CompilationRequiredError(str(policy_key))

    this_policy = _row_to_policy(row)
    bundle_policies = [this_policy] + _other_active_policies(db, policy_key)
    result = compile_bundle(
        bundle_policies, bundle_id=_bundle_id_for(policy_key, row.version), bundle_version=row.version
    )
    if not result.ok:
        raise CompilationRequiredError(
            f"{policy_key} no longer compiles cleanly (recompile before dry-running again)"
        )
    return run_dry_run(result.bundle, sample_input, opa_url=opa_url)


@dataclass(frozen=True)
class DeployOutcome:
    policy_row_id: uuid.UUID
    bundle_id: str
    bundle_hash: str
    deployed_at: datetime
    # Authority-as-a-continuous-object, Stage I.5: additive. Threads out
    # whatever _ensure_mandate already computed into `content["constraints"]`
    # above -- null whenever this policy has no resolved Authority behind
    # it, exactly as before.
    authority_id: str | None = None
    mandate_id: str | None = None


# Authority-as-a-continuous-object, Stage G: a Runtime Policy with no
# stated Constraints.expires is not meant to lapse on its own -- its own
# draft/approved/compiled/active/retired lifecycle is the actual control
# over whether it's in force. A Mandate's valid_to is NOT NULL, so
# something has to be recorded; 100 years is a deliberately-long,
# clearly-arbitrary horizon that reads as "no stated expiry" rather than
# a real, meaningful date, the same spirit as Evidence's 2555-day
# (7-year) retention default elsewhere in this codebase.
_DEFAULT_MANDATE_VALIDITY = timedelta(days=365 * 100)


def _ensure_mandate(db: Session, constraints: dict, policy_row: Policy, now: datetime) -> dict:
    """Creates the Mandate this policy's Authority (if any) has been
    waiting for since promotion -- Mandate.policy_id is NOT NULL, so this
    is the earliest point in the lifecycle a real one can exist. Returns
    `constraints` with mandate_id populated; a policy whose promotion
    never resolved an authority_id (single-document Policy Builder, or
    an unresolved delegation) passes through unchanged, exactly as it
    always has."""
    authority_id = constraints.get("authority_id")
    if not authority_id or constraints.get("mandate_id"):
        return constraints

    authority = db.get(Authority, uuid.UUID(authority_id))
    if authority is None:
        return constraints

    expires_str = constraints.get("expires")
    valid_to = datetime.fromisoformat(expires_str) if expires_str else now + _DEFAULT_MANDATE_VALIDITY

    mandate = Mandate(
        policy_id=policy_row.id,
        authority_id=authority.id,
        principal_id=authority.principal_id,
        scope=authority.scope,
        max_amount=authority.limit_amount,
        currency=authority.currency,
        valid_from=now,
        valid_to=valid_to,
    )
    db.add(mandate)
    db.flush()

    constraints["mandate_id"] = str(mandate.id)
    return constraints


def deploy_policy(db: Session, policy_key: uuid.UUID, opa_url: str = "http://localhost:8181") -> DeployOutcome:
    """Real deploy, confirmed with the user before implementing
    (POLICY_STUDIO_ARCHITECTURE.md's "Deploy is real" section): pushes to
    the same OPA policy id ("authorization") the existing
    policy_service.activate_policy already uses, and creates a real row
    in the existing `policies` table, retiring whatever was previously
    active there exactly as that function already does today."""
    row = get_latest(db, policy_key)
    if row.status != "compiled":
        raise InvalidTransitionError(row.status, "deploy")

    this_policy = _row_to_policy(row)
    bundle_policies = [this_policy] + _other_active_policies(db, policy_key)
    result = compile_bundle(
        bundle_policies, bundle_id=_bundle_id_for(policy_key, row.version), bundle_version=row.version
    )
    if not result.ok:
        raise CompilationRequiredError(f"{policy_key} failed to recompile at deploy time")
    if result.bundle.bundle_hash != row.bundle_hash:
        raise BundleChangedSinceCompileError(
            f"bundle_hash changed since compile ({row.bundle_hash} -> {result.bundle.bundle_hash}); "
            "another policy's active set changed underneath this one, recompile and try again"
        )

    prior_active = db.scalar(select(Policy).where(Policy.status == "active"))
    if prior_active is not None and not prior_active.bundle_uri.startswith(_EXPECTED_BUNDLE_URI_PREFIX):
        raise UnexpectedActiveWriterError(
            f"the currently-active policy (id={prior_active.id}, bundle_uri={prior_active.bundle_uri!r}) "
            "was not written by runtime_policy_service.deploy_policy -- refusing to silently overwrite it"
        )

    opa = HttpOpaClient(base_url=opa_url)
    opa.upload_policy("authorization", result.bundle.rego_source)

    next_version = (db.scalar(select(Policy.version).order_by(Policy.version.desc()).limit(1)) or 0) + 1
    now = datetime.now(timezone.utc)
    if prior_active is not None:
        prior_active.status = "retired"
        prior_active.retired_at = now

    policy_row = Policy(
        version=next_version,
        status="active",
        bundle_hash=result.bundle.bundle_hash,
        bundle_uri=f"runtime_policy_studio:{policy_key}:{row.version}",
        compiled_at=now,
        activated_at=now,
    )
    db.add(policy_row)
    # Flushed (not just added) so policy_row.id exists below: Mandate.
    # policy_id is NOT NULL, and this is the first point in this
    # policy's lifecycle a real Policy row -- and therefore a real id --
    # exists at all.
    db.flush()

    prior_active_rp = db.scalar(
        select(RuntimePolicyRecord).where(
            RuntimePolicyRecord.policy_key == policy_key,
            RuntimePolicyRecord.status == "active",
        )
    )
    if prior_active_rp is not None and prior_active_rp.id != row.id:
        prior_active_rp.status = "retired"

    content = dict(row.content)
    content["constraints"] = _ensure_mandate(db, dict(content.get("constraints") or {}), policy_row, now)
    audit = dict(content.get("audit") or {})
    audit["deployed"] = now.isoformat()
    content["audit"] = audit
    row.content = content
    row.status = "active"

    db.commit()
    db.refresh(policy_row)
    return DeployOutcome(
        policy_row_id=policy_row.id,
        bundle_id=result.bundle.bundle_id,
        bundle_hash=result.bundle.bundle_hash,
        deployed_at=policy_row.activated_at,
        authority_id=content["constraints"].get("authority_id"),
        mandate_id=content["constraints"].get("mandate_id"),
    )


@dataclass(frozen=True)
class ConditionDiffEntry:
    kind: str  # "added" | "removed" | "modified" | "unchanged"
    field: str
    operator: str
    old_value: object = None
    new_value: object = None


@dataclass(frozen=True)
class PolicyDiff:
    conditions: list[ConditionDiffEntry]
    scope_changed: bool
    effect_changed: bool
    constraints_changed: bool
    affected_agents: list[dict]
    affected_policies: list[dict]
    risk_impact: str
    risk_reason: str


def _condition_key(c) -> tuple[str, str]:
    return (c.field, c.operator.value)


def compute_condition_diff(
    from_policy: RuntimePolicy, to_policy: RuntimePolicy
) -> tuple[list[ConditionDiffEntry], str, str]:
    """The pure core of the Policy Diff page: takes two RuntimePolicy
    values directly, no database involved, so it's fully unit-testable.
    diff_versions() below is the thin, DB-dependent wrapper that fetches
    the two versions and the affected-agents/affected-policies queries
    this function has no way to answer on its own."""
    from_by_key = {_condition_key(c): c for c in from_policy.conditions.all}
    to_by_key = {_condition_key(c): c for c in to_policy.conditions.all}

    entries: list[ConditionDiffEntry] = []
    risk_increased = False
    risk_decreased = False

    for key in sorted(set(from_by_key) | set(to_by_key)):
        field, op = key
        old = from_by_key.get(key)
        new = to_by_key.get(key)
        if old is not None and new is None:
            entries.append(ConditionDiffEntry("removed", field, op, old_value=old.value))
            risk_increased = True  # a removed constraint is strictly more permissive
        elif old is None and new is not None:
            entries.append(ConditionDiffEntry("added", field, op, new_value=new.value))
            risk_decreased = True  # an added constraint is strictly more restrictive
        elif old.value != new.value:
            entries.append(
                ConditionDiffEntry("modified", field, op, old_value=old.value, new_value=new.value)
            )
            if op in {o.value for o in _NUMERIC_OPERATORS}:
                if op in ("<=", "<") and new.value > old.value:
                    risk_increased = True
                elif op in ("<=", "<") and new.value < old.value:
                    risk_decreased = True
                elif op in (">=", ">") and new.value < old.value:
                    risk_increased = True
                elif op in (">=", ">") and new.value > old.value:
                    risk_decreased = True
        else:
            entries.append(ConditionDiffEntry("unchanged", field, op, old_value=old.value, new_value=new.value))

    if risk_increased and not risk_decreased:
        risk_impact, risk_reason = "increased", (
            "a numeric limit was raised or a condition was removed: this version allows "
            "strictly more than the version it replaces, for at least one possible input"
        )
    elif risk_decreased and not risk_increased:
        risk_impact, risk_reason = "decreased", (
            "a numeric limit was lowered or a condition was added: this version allows "
            "strictly less than the version it replaces"
        )
    elif risk_increased and risk_decreased:
        risk_impact, risk_reason = "mixed", (
            "some conditions became more permissive and others more restrictive; "
            "review the condition-level diff above rather than this summary alone"
        )
    else:
        risk_impact, risk_reason = "unchanged", "no condition, scope, or effect change was detected"

    return entries, risk_impact, risk_reason


def diff_versions(db: Session, policy_key: uuid.UUID, from_version: int, to_version: int) -> PolicyDiff:
    from_row = get_version(db, policy_key, from_version)
    to_row = get_version(db, policy_key, to_version)
    from_policy = _row_to_policy(from_row)
    to_policy = _row_to_policy(to_row)

    entries, risk_impact, risk_reason = compute_condition_diff(from_policy, to_policy)

    scope_changed = to_dict(from_policy)["scope"] != to_dict(to_policy)["scope"]
    effect_changed = from_policy.effect != to_policy.effect
    constraints_changed = to_dict(from_policy)["constraints"] != to_dict(to_policy)["constraints"]

    affected_agents = list(
        db.scalars(select(Agent).where(Agent.acting_for_principal_id == uuid.UUID(to_policy.scope.principal)))
    ) if _is_uuid(to_policy.scope.principal) else []
    affected_agents_out = [{"id": str(a.id), "name": a.name} for a in affected_agents]

    other_latest = [
        r for r in list_latest_policies(db) if r.policy_key != policy_key
    ]
    affected_policies_out = []
    for r in other_latest:
        p = _row_to_policy(r)
        if p.scope.principal == to_policy.scope.principal:
            affected_policies_out.append(
                {
                    "policy_key": str(r.policy_key),
                    "name": p.name,
                    "version": r.version,
                    "status": r.status,
                    "same_action": p.scope.action == to_policy.scope.action,
                }
            )

    return PolicyDiff(
        conditions=entries,
        scope_changed=scope_changed,
        effect_changed=effect_changed,
        constraints_changed=constraints_changed,
        affected_agents=affected_agents_out,
        affected_policies=affected_policies_out,
        risk_impact=risk_impact,
        risk_reason=risk_reason,
    )


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False
