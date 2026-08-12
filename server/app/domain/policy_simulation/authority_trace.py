"""Authority Trace (Runtime Policy Simulator, Phase 4): a deterministic,
presentation-level synthesis of how authority flowed for one simulated
Intent -- built entirely from data the simulation already computed (the
acting agent's name, the principal it's acting as, which policy version
was evaluated, and the real OPA-computed outcome). No new judgment is
made here; this only orders already-known facts into the steps a
reviewer would narrate out loud.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthorityTraceStep:
    label: str
    detail: str | None = None


def build_authority_trace(
    agent_name: str,
    acting_as_principal: str,
    policy_name: str,
    policy_version: int,
    matched_policy_name: str | None,
    outcome: str,
) -> list[AuthorityTraceStep]:
    """AI Agent -> Principal -> Policy vN -> (the rule that actually
    decided it, if any) -> outcome. `matched_policy_name` is the name of
    whichever RuleEvaluation actually matched (evaluated_mandates), which
    may differ from the policy under test itself (`policy_name`) when a
    different, already-active policy is what decided this scenario --
    exactly the "CFO Override" example in POLICY_SIMULATOR.md, where the
    rule being validated didn't decide the outcome, another already-live
    one did."""
    steps = [
        AuthorityTraceStep(label=agent_name, detail="Acting agent"),
        AuthorityTraceStep(label=acting_as_principal, detail="Acting as"),
        AuthorityTraceStep(label=f"{policy_name} v{policy_version}", detail="Policy under simulation"),
    ]
    if matched_policy_name and matched_policy_name != policy_name:
        steps.append(AuthorityTraceStep(label=matched_policy_name, detail="Rule that decided the outcome"))
    steps.append(AuthorityTraceStep(label=_outcome_label(outcome), detail="Result"))
    return steps


def _outcome_label(outcome: str) -> str:
    return {"ALLOW": "Approved", "DENY": "Denied", "HUMAN_REVIEW": "Escalation Required"}.get(outcome, outcome)
