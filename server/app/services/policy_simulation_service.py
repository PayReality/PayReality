"""Runtime Policy Simulator service layer (Authority Intelligence
Program, Phase 4, POLICY_SIMULATOR.md): a dry run of Runtime Authority
for a hypothetical Intent, executed against the exact same OPA
evaluation Runtime Authority uses in production, isolated from it
entirely by domain/compiler_v2/dry_run.py's already-existing,
already-verified package-rewrite mechanism.

This module introduces no new OPA-isolation mechanism, no new Rego
compiler, and no new evaluation semantics -- it assembles already-
existing pieces (runtime_policy_service's own _row_to_policy/
_other_active_policies, compiler_v2.compile_bundle, compiler_v2.dry_run)
into a richer, explainable result, and adds two genuinely new,
additive capabilities the existing single-sample dry-run tool
(routers/runtime_policies.py's own /dry-run endpoint) doesn't have:
saved Test Scenarios and Batch Simulation.

Nothing here calls an LLM. Nothing here writes to a Decision, an
Evidence row, a Mandate, or any table real Intent evaluation reads.
The only thing this module ever persists is a SimulationScenario's own
definition -- never a simulated outcome (see that model's own
docstring: "a saved QUESTION, not a saved ANSWER").
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import SimulationScenario
from app.domain.compiler_v2.compiler_v2 import compile_bundle
from app.domain.compiler_v2.dry_run import DryRunError, dry_run as run_dry_run
from app.domain.decision.engine import build_opa_input
from app.domain.evidence.signing import payload_hash
from app.domain.policy_simulation.authority_trace import AuthorityTraceStep, build_authority_trace
from app.domain.policy_simulation.batch_evaluator import loaded_bundle, query_loaded_bundle
from app.domain.policy_simulation.explainer import RuleEvaluation, build_rule_evaluations
from app.services import fact_service
from app.services.runtime_policy_service import (
    CompilationRequiredError,
    RuntimePolicyNotFoundError,  # noqa: F401 -- re-exported for router catch clauses
    _ENTERPRISE_KNOWLEDGE_FIELD_PREFIX,
    _other_active_policies,
    _row_to_policy,
    get_latest,
)


class ScenarioNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class SimulationInput:
    """The hypothetical Intent under simulation. `principal` is who the
    action is performed AS (Scope.principal / acting_for_principal_id),
    the exact vocabulary the existing dry-run tool
    (schemas/runtime_policy.py's DryRunRequest) already uses -- not a
    new one. `agent_name` is presentation-only (the Authority Trace's
    first step); it is never matched against anything, since a
    simulation has no real Agent identity behind a hypothetical action.
    `context` mirrors Runtime Authority Context's own shape (e.g.
    {"authority": {"department": "Finance", "region": "South Africa"}})
    for policies whose conditions reference "context.*" fields -- the
    existing simple dry-run tool has no equivalent, since it never
    populates a `context` sibling in the OPA input at all.

    `counterparty` (PayReality 1.0 Audit finding G03): additive, mirrors
    the real Intent model's own field exactly -- it is the Trusted
    Enterprise Fact subject real Runtime Authority resolves facts
    against (intent_service.submit_intent's own `[(counterparty, key)
    for key in needed_fact_keys]`). Optional and defaulting to None
    because a simulation genuinely may not have one in mind yet; see
    `simulate()`'s own handling for what happens to a fact-gated policy
    when it's absent -- a visible limitation, never a silent guess."""

    principal: str
    action: str
    resource: str | None = None
    amount: float | None = None
    currency: str | None = None
    agent_name: str = "Simulated Agent"
    context: dict[str, Any] = field(default_factory=dict)
    counterparty: str | None = None

    def to_intent(self) -> dict[str, Any]:
        intent: dict[str, Any] = {"action": self.action}
        if self.resource is not None:
            intent["resource"] = self.resource
        if self.amount is not None:
            intent["amount"] = self.amount
        if self.currency is not None:
            intent["currency"] = self.currency
        return intent

    def to_dict(self) -> dict[str, Any]:
        return {
            "principal": self.principal, "action": self.action, "resource": self.resource,
            "amount": self.amount, "currency": self.currency, "agent_name": self.agent_name,
            "context": self.context, "counterparty": self.counterparty,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "SimulationInput":
        return SimulationInput(
            principal=data["principal"], action=data["action"], resource=data.get("resource"),
            amount=data.get("amount"), currency=data.get("currency"),
            agent_name=data.get("agent_name", "Simulated Agent"), context=data.get("context") or {},
            # Absent on every scenario saved before this field existed --
            # None is the correct, honest read for those, not a guess.
            counterparty=data.get("counterparty"),
        )


@dataclass(frozen=True)
class EvidencePreview:
    """Evidence Preview (Task-scoped, never persisted): reuses
    domain/evidence/signing.py's canonicalize/hash logic unchanged, but
    is deliberately never signed with the real Evidence signing key.
    Signing a simulated, never-real decision with the production
    Ed25519 key would produce a signature that verifies successfully
    against the real public key -- indistinguishable from genuine
    Evidence to anyone who checks it later. A hash alone lets a reviewer
    confirm this preview wasn't altered between generating it and
    discussing it, without ever producing something that could be
    mistaken for, or replayed as, a real, verifiable Decision Receipt."""

    decision: str
    policy_version: int
    policy_bundle_hash: str
    principal: str
    action: str
    resource: str | None
    evaluated_at: str
    receipt_hash: str
    preview: bool = True


@dataclass(frozen=True)
class SimulationResult:
    decision: str  # "ALLOW" | "DENY" | "HUMAN_REVIEW"
    policy_key: str
    policy_name: str
    policy_version: int
    policy_bundle_hash: str
    generated_at: str
    review_reason: str | None
    deny_reason: str | None
    rules: list[RuleEvaluation]
    authority_trace: list[AuthorityTraceStep]
    evidence_preview: EvidencePreview
    # PayReality 1.0 Audit finding G03: the exact Trusted Enterprise
    # Facts actually resolved and fed into this simulation's OPA
    # evaluation -- {key: value}, empty whenever none were needed or
    # none resolved. Lets a reviewer see precisely what real-world fact
    # state this result depended on, the same transparency
    # facts_evaluated already gives a real Decision's Evidence.
    facts_evaluated: dict[str, Any] = field(default_factory=dict)
    # A real, visible limitation this simulation could NOT resolve --
    # never a silent guess. Populated only when at least one active
    # policy's condition references an enterprise_knowledge.<key> this
    # simulation had no counterparty to look it up against; the
    # resulting evaluation is still real and still fail-closed (an
    # unresolved fact behaves exactly as it would in production -- the
    # referencing rule simply doesn't match), but a reviewer should
    # know the absence was because no subject was given, not because a
    # fact genuinely doesn't exist.
    warnings: list[str] = field(default_factory=list)


def _decision_from_flags(allow: bool, deny: bool, requires_review: bool) -> str:
    """Mirrors routers/runtime_policies.py's existing /dry-run endpoint's
    own outcome mapping exactly (same three-way branch, same order) --
    not a second, independently-invented notion of what allow/deny/
    requires_review mean."""
    if requires_review:
        return "HUMAN_REVIEW"
    if allow and not deny:
        return "ALLOW"
    if deny:
        return "DENY"
    return "HUMAN_REVIEW"


def _compile_for_simulation(db: Session, policy_key: uuid.UUID, organization_id: uuid.UUID | None):
    """The same composition runtime_policy_service.dry_run_policy already
    uses internally (this policy version + every OTHER active policy),
    exposed here because the simulator additionally needs the actual
    list of RuntimePolicy objects for the rule-by-rule explanation --
    dry_run_policy() only returns a DryRunResult, not the policy set it
    compiled.

    Milestone 6: `organization_id` threaded through both calls below.
    Neither this function nor anything upstream of it was ever updated
    for Milestone 2's Multi-Tenant Foundation -- get_latest and
    _other_active_policies have required this argument since that
    milestone, but every call site in this whole module predated it, so
    every one of them raised TypeError in production the moment this
    feature was ever actually exercised. get_latest's own organization
    filter is also what makes this the correct place to enforce "a
    simulation can only ever run against the caller's own organization's
    policy," not a separate check -- an unknown or cross-organization
    policy_key raises RuntimePolicyNotFoundError here exactly as it
    would for any other organization-scoped lookup in this codebase."""
    row = get_latest(db, policy_key, organization_id)
    this_policy = _row_to_policy(row)
    other_policies = _other_active_policies(db, policy_key, organization_id)
    all_policies = [this_policy] + other_policies
    result = compile_bundle(
        all_policies, bundle_id=f"simulation-{policy_key.hex}", bundle_version=row.version
    )
    return row, this_policy, all_policies, result


def _enterprise_knowledge_keys_referenced(all_policies: list) -> list[str]:
    """PayReality 1.0 Audit finding G03: the simulator's own equivalent
    of runtime_policy_service.list_enterprise_knowledge_keys_for_active_
    policies -- deliberately NOT that function, because that one scans
    already-*active* Policy rows straight from the database, and the
    whole point of a simulation is to evaluate a policy that may not be
    active yet (still draft/compiled). Scans the actual RuntimePolicy
    domain objects this simulation is about to compile against instead
    (this_policy + every other currently-active policy,
    _compile_for_simulation's own `all_policies`) -- the same set a real
    deploy of `this_policy` would put into production. Reuses the real
    field-prefix constant, not a redefined copy, so the two functions
    can never silently drift on what "an enterprise_knowledge field"
    means."""
    keys: set[str] = set()
    for policy in all_policies:
        for condition in policy.conditions.all:
            if condition.field.startswith(_ENTERPRISE_KNOWLEDGE_FIELD_PREFIX):
                keys.add(condition.field[len(_ENTERPRISE_KNOWLEDGE_FIELD_PREFIX):])
    return sorted(keys)


def simulate(
    db: Session, policy_key: uuid.UUID, sim_input: SimulationInput,
    organization_id: uuid.UUID | None, opa_url: str | None = None,
) -> SimulationResult:
    """The core "dry run of Runtime Authority." Compiles the selected
    policy version together with every other currently-active policy --
    the exact set a real deployment would put into production -- and
    evaluates it via compiler_v2.dry_run's already-existing, already-
    verified isolated-package mechanism. Never writes anything.

    PayReality 1.0 Audit finding G03: previously built its own OPA input
    by hand, omitting `enterprise_knowledge` entirely -- any fact-gated
    policy simulated as if no Trusted Enterprise Facts existed at all,
    silently diverging from what real Runtime Authority would actually
    decide, with no warning. Now reuses domain.decision.engine's own
    pure build_opa_input (the exact function intent_service.submit_intent
    itself calls) and resolves facts the same way submit_intent does --
    fact_service.resolve_facts against sim_input.counterparty as the
    subject, for exactly the keys this simulation's own policy set
    references (_enterprise_knowledge_keys_referenced above). A missing,
    expired, or conflicting fact behaves exactly as it would in
    production (fail-closed, via the same undefined-in-Rego mechanism) --
    this function never invents a fallback value. If a policy needs a
    fact but this simulation was given no counterparty to look it up
    against, that's flagged as a real, visible limitation
    (SimulationResult.warnings) rather than silently evaluated as if the
    fact requirement didn't exist."""
    row, this_policy, all_policies, compile_result = _compile_for_simulation(db, policy_key, organization_id)
    if not compile_result.ok:
        raise CompilationRequiredError(
            f"{policy_key} does not currently compile cleanly -- fix the errors before simulating"
        )
    bundle = compile_result.bundle

    intent = sim_input.to_intent()
    context = sim_input.context

    needed_fact_keys = _enterprise_knowledge_keys_referenced(all_policies)
    warnings: list[str] = []
    resolved_facts = []
    if needed_fact_keys:
        if sim_input.counterparty is None:
            warnings.append(
                "This policy set references enterprise_knowledge fact(s) "
                f"({', '.join(needed_fact_keys)}), but no counterparty was given to simulate "
                "against -- these facts are being evaluated as unresolved (fail-closed, the same "
                "way a genuinely missing fact behaves in production), not silently ignored."
            )
        elif organization_id is not None:
            # A missing, expired, or conflicting fact here is NOT a
            # simulation limitation -- production resolves facts exactly
            # this same way (intent_service.submit_intent's own
            # resolve_facts call, same FactConflictError -> [] fallback),
            # so the fail-closed result below IS full parity, not a gap.
            # No warning: see SimulationResult.warnings' own docstring --
            # warnings exist only for what this simulation genuinely
            # could not resolve (no counterparty to look up against),
            # not for a real, resolved "no trusted fact exists" answer.
            try:
                resolved_facts = fact_service.resolve_facts(
                    db, organization_id, [(sim_input.counterparty, key) for key in needed_fact_keys]
                )
            except fact_service.FactConflictError:
                resolved_facts = []
    enterprise_knowledge = {f.key: f.value for f in resolved_facts}

    opa_input = build_opa_input(
        intent, context, sim_input.principal, bundle.version, enterprise_knowledge=enterprise_knowledge
    )

    dry_run_result = run_dry_run(bundle, opa_input, opa_url=opa_url or settings.opa_url)

    decision = _decision_from_flags(dry_run_result.allow, dry_run_result.deny, dry_run_result.requires_review)
    rules = build_rule_evaluations(
        all_policies, intent, context, sim_input.principal, dry_run_result.evaluated_mandates
    )
    matched_rule = next((r for r in rules if r.matched), None)

    trace = build_authority_trace(
        agent_name=sim_input.agent_name,
        acting_as_principal=sim_input.principal,
        policy_name=this_policy.name,
        policy_version=this_policy.version,
        matched_policy_name=matched_rule.policy_name if matched_rule else None,
        outcome=decision,
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    preview_payload = {
        "decision": decision, "policy_version": bundle.version, "policy_bundle_hash": bundle.bundle_hash,
        "principal": sim_input.principal, "action": sim_input.action, "resource": sim_input.resource,
        "evaluated_at": now_iso,
    }
    evidence_preview = EvidencePreview(
        decision=decision, policy_version=bundle.version, policy_bundle_hash=bundle.bundle_hash,
        principal=sim_input.principal, action=sim_input.action, resource=sim_input.resource,
        evaluated_at=now_iso, receipt_hash=payload_hash(preview_payload),
    )

    return SimulationResult(
        decision=decision, policy_key=str(policy_key), policy_name=this_policy.name,
        policy_version=bundle.version, policy_bundle_hash=bundle.bundle_hash, generated_at=now_iso,
        review_reason=dry_run_result.review_reason, deny_reason=dry_run_result.deny_reason,
        rules=rules, authority_trace=trace, evidence_preview=evidence_preview,
        facts_evaluated=enterprise_knowledge, warnings=warnings,
    )


# --- Test Scenarios -------------------------------------------------------


def create_scenario(
    db: Session, policy_key: uuid.UUID, name: str, sim_input: SimulationInput,
    expected_outcome: str, organization_id: uuid.UUID | None, created_by: str | None = None,
) -> SimulationScenario:
    """Milestone 6: verifies policy_key belongs to the caller's own
    organization (get_latest raises RuntimePolicyNotFoundError
    otherwise) before stamping the new row -- SimulationScenario.
    organization_id has existed since Milestone 2, but nothing ever
    populated it, leaving every saved scenario readable/listable by any
    organization that guessed its UUID (list_scenarios/get_scenario
    below had the same gap)."""
    get_latest(db, policy_key, organization_id)
    scenario = SimulationScenario(
        id=uuid.uuid4(), policy_key=policy_key, name=name,
        input=sim_input.to_dict(), expected_outcome=expected_outcome, created_by=created_by,
        organization_id=organization_id,
    )
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    return scenario


def list_scenarios(db: Session, policy_key: uuid.UUID, organization_id: uuid.UUID | None) -> list[SimulationScenario]:
    get_latest(db, policy_key, organization_id)
    return list(
        db.scalars(
            select(SimulationScenario)
            .where(
                SimulationScenario.policy_key == policy_key,
                SimulationScenario.organization_id == organization_id,
            )
            .order_by(SimulationScenario.created_at.desc())
        )
    )


def get_scenario(db: Session, scenario_id: uuid.UUID, organization_id: uuid.UUID | None) -> SimulationScenario:
    row = db.get(SimulationScenario, scenario_id)
    if row is None or row.organization_id != organization_id:
        raise ScenarioNotFoundError(str(scenario_id))
    return row


@dataclass(frozen=True)
class ScenarioRunResult:
    scenario_id: str
    scenario_name: str
    expected_outcome: str
    actual_outcome: str
    passed: bool
    result: SimulationResult


def run_scenario(
    db: Session, scenario_id: uuid.UUID, organization_id: uuid.UUID | None, opa_url: str | None = None
) -> ScenarioRunResult:
    """Re-runs a saved scenario's INPUT against the policy's current
    state and computes PASS/FAIL live -- the scenario row itself is
    never updated with this outcome, so running the same scenario again
    after a policy edit can legitimately produce a different actual
    result without that being a data inconsistency."""
    scenario = get_scenario(db, scenario_id, organization_id)
    sim_input = SimulationInput.from_dict(scenario.input)
    result = simulate(db, scenario.policy_key, sim_input, organization_id, opa_url=opa_url)
    return ScenarioRunResult(
        scenario_id=str(scenario.id), scenario_name=scenario.name,
        expected_outcome=scenario.expected_outcome, actual_outcome=result.decision,
        passed=(result.decision == scenario.expected_outcome), result=result,
    )


# --- Batch Simulation -------------------------------------------------------


@dataclass(frozen=True)
class BatchRow:
    row_number: int
    principal: str
    action: str
    decision: str | None
    error: str | None = None
    # PayReality 1.0 Audit finding G03 (verification-closure pass): set,
    # instead of `decision`, when this candidate policy set references an
    # enterprise_knowledge.* fact and this row gave no `counterparty` to
    # resolve it against -- a real, visible limitation, never a silent
    # ALLOW/DENY/HUMAN_REVIEW guessed as if the fact requirement didn't
    # exist. Distinct from `error`: this is not a malformed row, it is a
    # row this simulator genuinely cannot evaluate truthfully.
    limitation: str | None = None


_BATCH_SAMPLE_LIMIT = 50


@dataclass(frozen=True)
class BatchSimulationResult:
    total: int
    allowed: int
    denied: int
    escalated: int
    errors: int
    sample_rows: list[BatchRow]
    sample_truncated: bool
    policy_version: int
    policy_bundle_hash: str
    # PayReality 1.0 Audit finding G03 (verification-closure pass): rows
    # this simulator declined to evaluate at all, rather than silently
    # returning an ALLOW/DENY/HUMAN_REVIEW that ignored a Trusted
    # Enterprise Fact requirement it had no subject to resolve against.
    # Never folded into `errors` (which means "malformed row"), and never
    # folded into `allowed`/`denied`/`escalated` (which would be exactly
    # the silently-incorrect result this field exists to prevent).
    cannot_simulate: int = 0


def run_batch(
    db: Session, policy_key: uuid.UUID, rows: list[dict[str, Any]],
    organization_id: uuid.UUID | None, opa_url: str | None = None,
) -> BatchSimulationResult:
    """Task: Batch Simulation -- replay many historical actions against
    the candidate policy version. Compiles and loads the bundle into OPA
    ONCE (domain/policy_simulation/batch_evaluator.loaded_bundle),
    querying it once per row, rather than repeating dry_run()'s own
    upload/query/delete cycle for every row -- the isolation guarantee
    is identical (a unique throwaway package, deleted afterward), only
    the amortization differs. Never persists a single row's result;
    only the aggregate counts and a capped sample are ever returned.

    PayReality 1.0 Audit finding G03 (verification-closure pass): this
    previously hand-built its OPA input exactly like simulate() used to,
    with the identical Trusted Enterprise Facts gap -- a fact-gated
    policy silently evaluated every row as if no facts existed at all.
    Now reuses the same shared pieces simulate() itself uses --
    build_opa_input and fact_service.resolve_facts, and
    _enterprise_knowledge_keys_referenced to learn what this policy set
    actually needs, computed once for the whole batch rather than
    duplicated per row. A CSV `counterparty` (or `vendor`) column is the
    minimal, natural per-row extension: it is already the exact same
    field the wire format and the SDK both use, not a newly-invented
    concept. Where a row lacks it AND the policy set needs a fact, this
    is Option B, not a silent Option A degrade: the row is marked
    CANNOT_SIMULATE and excluded from the allowed/denied/escalated
    counts entirely, rather than evaluated as if the fact requirement
    weren't there."""
    _row, _this_policy, all_policies, compile_result = _compile_for_simulation(db, policy_key, organization_id)
    if not compile_result.ok:
        raise CompilationRequiredError(f"{policy_key} does not currently compile cleanly")
    bundle = compile_result.bundle
    resolved_opa_url = opa_url or settings.opa_url
    needed_fact_keys = _enterprise_knowledge_keys_referenced(all_policies)

    allowed = denied = escalated = errors = cannot_simulate = 0
    sample: list[BatchRow] = []

    with loaded_bundle(bundle, resolved_opa_url) as data_path:
        for i, raw_row in enumerate(rows, start=1):
            principal = str(raw_row.get("principal", "")).strip()
            action = str(raw_row.get("action", "")).strip()
            try:
                if not principal or not action:
                    raise ValueError("principal and action are required")

                counterparty = str(raw_row.get("counterparty") or raw_row.get("vendor") or "").strip() or None
                if needed_fact_keys and not counterparty:
                    cannot_simulate += 1
                    if len(sample) < _BATCH_SAMPLE_LIMIT:
                        sample.append(BatchRow(
                            row_number=i, principal=principal, action=action, decision=None,
                            limitation=(
                                "This policy requires Trusted Enterprise Fact(s) "
                                f"({', '.join(needed_fact_keys)}), but this row does not identify the fact "
                                "subject (a `counterparty` or `vendor` column) required for truthful resolution."
                            ),
                        ))
                    continue

                amount_raw = raw_row.get("amount")
                intent: dict[str, Any] = {"action": action}
                if raw_row.get("resource"):
                    intent["resource"] = raw_row["resource"]
                if amount_raw not in (None, ""):
                    intent["amount"] = float(amount_raw)
                if raw_row.get("currency"):
                    intent["currency"] = raw_row["currency"]

                # Any column beyond the core six (principal/action/
                # resource/amount/currency/counterparty|vendor) is passed
                # through as Runtime Authority Context, flat -- a batch
                # CSV's own header row is the only vocabulary this needs
                # to understand.
                context = {
                    k: v for k, v in raw_row.items()
                    if k not in ("principal", "action", "resource", "amount", "currency", "counterparty", "vendor")
                    and v not in (None, "")
                }

                enterprise_knowledge: dict[str, Any] = {}
                if needed_fact_keys and organization_id is not None:
                    try:
                        resolved_facts = fact_service.resolve_facts(
                            db, organization_id, [(counterparty, key) for key in needed_fact_keys]
                        )
                    except fact_service.FactConflictError:
                        resolved_facts = []
                    enterprise_knowledge = {f.key: f.value for f in resolved_facts}

                opa_input = build_opa_input(
                    intent, context, principal, bundle.version, enterprise_knowledge=enterprise_knowledge
                )
                result = query_loaded_bundle(resolved_opa_url, data_path, opa_input)
                decision = _decision_from_flags(
                    result.get("allow", False), result.get("deny", False), result.get("requires_review", False)
                )
                if decision == "ALLOW":
                    allowed += 1
                elif decision == "DENY":
                    denied += 1
                else:
                    escalated += 1
                if len(sample) < _BATCH_SAMPLE_LIMIT:
                    sample.append(BatchRow(row_number=i, principal=principal, action=action, decision=decision))
            except (ValueError, DryRunError) as e:
                errors += 1
                if len(sample) < _BATCH_SAMPLE_LIMIT:
                    sample.append(
                        BatchRow(row_number=i, principal=principal or "?", action=action or "?",
                                  decision=None, error=str(e))
                    )

    return BatchSimulationResult(
        total=len(rows), allowed=allowed, denied=denied, escalated=escalated, errors=errors,
        cannot_simulate=cannot_simulate,
        sample_rows=sample, sample_truncated=len(rows) > _BATCH_SAMPLE_LIMIT,
        policy_version=bundle.version, policy_bundle_hash=bundle.bundle_hash,
    )
