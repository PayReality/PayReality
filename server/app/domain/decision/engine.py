"""Decision Engine: spec Section 16.2's algorithm, ported directly to Python.

Pure orchestration: no DB access. Callers pass in an OPA client and a
PolicyStore-like lookup for the active policy, which makes this module
unit-testable against fakes before any real OPA/DB integration exists.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

# Runtime Governance Architecture, Phase 1 (24_PHASE_1_RUNTIME_CORE_PLAN.md
# section 24.2.1): the Decision Evidence discipline requires an explicit,
# self-contained Authority Version pinned on every decision, mirroring the
# already-established COMPILER_VERSION pattern (bundle_builder.py) rather
# than inventing a new convention. Bump this only when evaluate()'s own
# decision logic changes in a way that could alter a past decision's
# outcome if replayed -- never for unrelated refactors.
DECISION_ENGINE_VERSION = "1.0.0"


class OPATimeoutError(Exception):
    """Raised by an OpaClient implementation when a query exceeds its timeout."""


class OPAEvaluationError(Exception):
    """Raised by an OpaClient implementation for any other OPA failure."""

    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


class NoActivePolicyError(Exception):
    """Raised by a PolicyStore implementation when no Policy is active."""


@dataclass(frozen=True)
class ActivePolicy:
    id: str
    version: int
    # Optional, defaulted: Phase 1 threads this through from the Policy
    # row's existing bundle_hash column so a Decision can pin the
    # content-addressed identity of what it was evaluated against, not
    # only the sequence number. Defaulted so any PolicyStore
    # implementation (including test fakes) that doesn't supply it keeps
    # working unmodified.
    bundle_hash: str | None = None


@dataclass(frozen=True)
class Decision:
    outcome: str  # "ALLOW" | "DENY" | "HUMAN_REVIEW"
    reason: str | None = None
    evaluated_mandates: list[str] = field(default_factory=list)
    policy_id: str | None = None
    # Runtime Governance Architecture, Phase 1: explicit, redundant Policy
    # Version pinning on the Decision itself, alongside the existing
    # policy_id FK -- so replay never depends on the `policies` row still
    # existing to answer "which version governed this," even though that
    # row is retained (never deleted) today. None when no policy was ever
    # consulted (e.g. no_active_policy, opa_timeout before a version was
    # read) -- never a fabricated placeholder.
    policy_version: int | None = None
    policy_bundle_hash: str | None = None
    # The version of this evaluation engine itself -- Decision Evidence's
    # "who evaluated" made explicit rather than only implied by which
    # code happened to be deployed when the record was created.
    authority_version: str = DECISION_ENGINE_VERSION


class OpaClient(Protocol):
    def query(self, input_doc: dict[str, Any], timeout_ms: int) -> dict[str, Any]: ...


class PolicyStore(Protocol):
    def get_active(self) -> ActivePolicy: ...


def build_opa_input(
    intent: dict[str, Any],
    context: dict[str, Any],
    acting_for_principal_id: str,
    policy_version: int,
    *,
    agent_id: str | None = None,
    enterprise_knowledge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Milestone 17.1 remediation: `agent_id` closes a real, pre-existing
    # gap discovered (not introduced) during the prior milestone.
    # rego_generator.generate_scope_block has always emitted
    # `input.agent.id == "<configured agent>"` for a RuntimePolicy
    # authored with Scope.agent narrowing, but this "agent" section never
    # actually carried an `id` key -- only `acting_for_principal_id` --
    # so that comparison was always undefined, and a Scope.agent-
    # narrowed policy could never match any real Intent, for any agent,
    # ever. The fix is exactly this one missing field, not a compiler or
    # Rego-generation change: `Agent.id` (the real, globally-unique
    # primary key, never reused, unlike `Agent.name`) is the correct,
    # already-canonical identifier to satisfy it. Optional and
    # keyword-only so every existing caller/test that has no real Agent
    # in hand (the pure decision-engine unit tests in
    # test_decision_engine.py, which use fakes with no agent identity at
    # all) keeps working unchanged; the real request path
    # (intent_service.submit_intent) always has a real Agent and always
    # passes its id.
    #
    # Trusted Enterprise Facts (ENTERPRISE_KNOWLEDGE_DECISION_RECORD.md
    # Decision 5): a new, clearly namespaced section, sibling to
    # `context`, not merged into it -- a condition references it as
    # `enterprise_knowledge.<key>` (compiler_v2.py's own prefix
    # exception), never mixed into the caller-extensible `context` dict.
    # Defaults to `{}` so every existing caller/test that doesn't pass
    # this argument at all keeps evaluating exactly as before -- no
    # existing compiled policy could ever reference a section that did
    # not exist yet, so this is safe for replay of any past decision.
    return {
        "intent": intent,
        "context": context,
        "agent": {"id": agent_id, "acting_for_principal_id": acting_for_principal_id},
        "policy_version": policy_version,
        "enterprise_knowledge": enterprise_knowledge or {},
    }


def evaluate(
    intent: dict[str, Any],
    context: dict[str, Any],
    acting_for_principal_id: str,
    policy_store: PolicyStore,
    opa_client: OpaClient,
    timeout_ms: int = 200,
    *,
    agent_id: str | None = None,
    enterprise_knowledge: dict[str, Any] | None = None,
) -> Decision:
    """Direct port of spec Section 16.2's reference algorithm.

    Fail-closed (Principle 8): any error, timeout, or missing active policy
    resolves to HUMAN_REVIEW, never ALLOW.

    `agent_id`/`enterprise_knowledge` are deliberately keyword-only:
    several existing test files override this function's *positional*
    default (`decision_engine.evaluate.__defaults__ = (5000,)`, bumping
    `timeout_ms` for a slow ephemeral OPA startup) -- keyword-only
    arguments live in `__kwdefaults__`, a completely separate dict, so
    adding either parameter cannot silently break that existing override
    pattern or shift what a positional-defaults tuple of length 1 means."""
    try:
        active_policy = policy_store.get_active()
    except NoActivePolicyError:
        return Decision(outcome="HUMAN_REVIEW", reason="no_active_policy")

    # Runtime Governance Architecture, Phase 1: every Decision constructed
    # from this point on has an active_policy in hand, so every branch
    # below pins policy_version/policy_bundle_hash explicitly -- only the
    # no_active_policy branch above (no policy was ever consulted) leaves
    # them at their None default, honestly, rather than fabricating a
    # version for a policy that was never read.
    try:
        opa_input = build_opa_input(
            intent, context, acting_for_principal_id, active_policy.version,
            agent_id=agent_id, enterprise_knowledge=enterprise_knowledge,
        )
        result = opa_client.query(opa_input, timeout_ms=timeout_ms)
    except OPATimeoutError:
        return Decision(
            outcome="HUMAN_REVIEW",
            reason="opa_timeout",
            policy_id=active_policy.id,
            policy_version=active_policy.version,
            policy_bundle_hash=active_policy.bundle_hash,
        )
    except OPAEvaluationError as e:
        return Decision(
            outcome="HUMAN_REVIEW",
            reason=f"opa_error:{e.code}",
            policy_id=active_policy.id,
            policy_version=active_policy.version,
            policy_bundle_hash=active_policy.bundle_hash,
        )

    evaluated = result.get("evaluated_mandates", [])

    if result.get("requires_review") is True:
        return Decision(
            outcome="HUMAN_REVIEW",
            reason=result.get("review_reason"),
            evaluated_mandates=evaluated,
            policy_id=active_policy.id,
            policy_version=active_policy.version,
            policy_bundle_hash=active_policy.bundle_hash,
        )
    if result.get("allow") is True and result.get("deny") is not True:
        return Decision(
            outcome="ALLOW",
            evaluated_mandates=evaluated,
            policy_id=active_policy.id,
            policy_version=active_policy.version,
            policy_bundle_hash=active_policy.bundle_hash,
        )
    if result.get("deny") is True:
        return Decision(
            outcome="DENY",
            reason=result.get("deny_reason"),
            evaluated_mandates=evaluated,
            policy_id=active_policy.id,
            policy_version=active_policy.version,
            policy_bundle_hash=active_policy.bundle_hash,
        )

    # Anything not explicitly ALLOW or DENY is HUMAN_REVIEW (fail closed).
    return Decision(
        outcome="HUMAN_REVIEW",
        reason="undetermined",
        policy_id=active_policy.id,
        policy_version=active_policy.version,
        policy_bundle_hash=active_policy.bundle_hash,
    )
