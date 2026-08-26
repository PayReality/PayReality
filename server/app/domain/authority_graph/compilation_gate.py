"""Authority Graph -> RuntimePolicy Compilation Gate (GitHub issue #6).

Pure, DB-free validation: given a candidate's content (the same
RuntimePolicyRequest-shaped dict already read by
ai_policy_builder_service._find_resolved_principal_for_candidate) and an
approved Authority Graph snapshot (AuthorityGraphApproval.evidence_snapshot),
decide whether promotion is allowed -- and if not, exactly why.

Same discipline as domain/compiler_v2/compiler_errors.py: this module
never raises for "the graph doesn't support this candidate" -- that's
data, not a programming error. It always returns a GraphReadinessResult;
the caller (ai_policy_builder_service.promote_candidate) decides whether
to turn a not-ready result into an exception.

What this module explicitly does NOT do, by design:
- It never invents, adjusts, or infers a condition/threshold/effect --
  those come only from the candidate's own content, unchanged.
- It never calls an LLM, queries OPA, or touches the database.
- It never resolves against LIVE AuthorityPrincipal/AuthorityRelationship
  rows -- only the frozen, immutable evidence_snapshot of the approval
  being compiled against, so the same (candidate, approval) pair always
  produces the same result regardless of what's changed on the corpus
  since that approval (determinism requirement, GAVIN_REMEDIATION_PLAN.md's
  "the same graph state produces the same compile result every time").
"""

from dataclasses import dataclass, field
from typing import Any

NO_APPROVED_GRAPH = "NO_APPROVED_GRAPH"
UNRESOLVED_CONFLICTS_IN_APPROVED_GRAPH = "UNRESOLVED_CONFLICTS_IN_APPROVED_GRAPH"
UNRESOLVED_PRINCIPAL = "UNRESOLVED_PRINCIPAL"
UNRESOLVED_OR_INACTIVE_RELATIONSHIP = "UNRESOLVED_OR_INACTIVE_RELATIONSHIP"


@dataclass(frozen=True)
class GraphGateError:
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class GraphReadinessResult:
    ready: bool
    errors: tuple[GraphGateError, ...] = field(default_factory=tuple)
    # Present only when ready=True -- the exact resolved principal name
    # this candidate's authority governs, as it appears in the approved
    # snapshot. Not itself proof of anything beyond "found in this
    # snapshot"; provenance stamping uses the approval's own id/version,
    # not this name.
    resolved_principal_name: str | None = None


@dataclass(frozen=True)
class GraphProvenance:
    """What gets stamped onto a graph-derived RuntimePolicy's Metadata
    (domain/runtime_policy/metadata.py) once check_graph_readiness
    returns ready=True. Every field a plain string/int -- no live
    reference back to the graph, matching the same immutability
    discipline Historical Policy Binding already applies (a stamped
    fact, never a pointer that could later resolve to something
    different)."""

    corpus_id: str
    approval_id: str
    graph_version: int
    candidate_id: str


def _candidate_principal_name(content: dict[str, Any]) -> str | None:
    scope_data = content.get("scope") or {}
    name = scope_data.get("principal")
    return name.strip() if isinstance(name, str) and name.strip() else None


def _candidate_delegated_by(content: dict[str, Any]) -> str | None:
    constraints_data = content.get("constraints") or {}
    name = constraints_data.get("delegated_by")
    return name.strip() if isinstance(name, str) and name.strip() else None


def _find_principal_entry(snapshot: dict[str, Any], name: str) -> dict[str, Any] | None:
    target = name.lower()
    for p in snapshot.get("principals") or []:
        if isinstance(p.get("name"), str) and p["name"].strip().lower() == target:
            return p
    return None


def _has_active_relationship(snapshot: dict[str, Any], from_name: str, to_name: str) -> bool:
    from_target = from_name.lower()
    to_target = to_name.lower()
    for r in snapshot.get("relationships") or []:
        if r.get("kind") not in ("delegation", "escalation"):
            continue
        if r.get("status") != "active":
            continue
        rel_from = r.get("from_principal")
        rel_to = r.get("to_principal")
        if (
            isinstance(rel_from, str) and rel_from.strip().lower() == from_target
            and isinstance(rel_to, str) and rel_to.strip().lower() == to_target
        ):
            return True
    return False


def check_graph_readiness(
    content: dict[str, Any], approval_snapshot: dict[str, Any] | None
) -> GraphReadinessResult:
    """`approval_snapshot` is `AuthorityGraphApproval.evidence_snapshot`
    for the specific approval being compiled against, or None when no
    approval exists at all for this candidate's corpus.

    Conflict handling: the snapshot's `conflicts` list has no structured
    link to which principal/action each conflict concerns (a real data-
    model gap confirmed during this milestone's audit -- AuthorityConflict
    carries only a free-text description, never a principal/relationship
    FK). Rather than guess which conflicts are safe to ignore, this gate
    conservatively blocks ALL graph-derived promotion whenever the
    approved snapshot recorded ANY open conflict -- the same "fail
    closed rather than guess" discipline compiler_v2's own `contains`
    operator already applies when it can't prove non-overlap. A reviewer
    must approve a new, conflict-free graph version before graph-derived
    promotion can proceed. This is a deliberate, disclosed interpretation
    of "no unresolved conflict touches this principal/action" -- not a
    literal per-principal check, since the data to make that check
    precise doesn't exist yet.
    """
    if approval_snapshot is None:
        return GraphReadinessResult(
            ready=False,
            errors=(GraphGateError(
                code=NO_APPROVED_GRAPH,
                message="This candidate's corpus has no approved Authority Graph version yet. "
                        "Approve a graph version before promoting a candidate discovered from it.",
                path="corpus_id",
            ),),
        )

    conflicts = approval_snapshot.get("conflicts") or []
    if conflicts:
        return GraphReadinessResult(
            ready=False,
            errors=(GraphGateError(
                code=UNRESOLVED_CONFLICTS_IN_APPROVED_GRAPH,
                message=f"The approved Authority Graph version has {len(conflicts)} open conflict(s) recorded. "
                        "Approve a new, conflict-free graph version before graph-derived promotion can proceed.",
                path="conflicts",
            ),),
        )

    principal_name = _candidate_principal_name(content)
    if not principal_name:
        return GraphReadinessResult(
            ready=False,
            errors=(GraphGateError(
                code=UNRESOLVED_PRINCIPAL,
                message="This candidate names no principal (scope.principal is empty), so it cannot be "
                        "grounded in the approved Authority Graph.",
                path="scope.principal",
            ),),
        )

    principal_entry = _find_principal_entry(approval_snapshot, principal_name)
    if principal_entry is None or not principal_entry.get("resolved_principal_id"):
        return GraphReadinessResult(
            ready=False,
            errors=(GraphGateError(
                code=UNRESOLVED_PRINCIPAL,
                message=f'"{principal_name}" is not resolved to a real Principal in the approved Authority '
                        "Graph version. Resolve it in Authority Builder, then approve a new graph version.",
                path="scope.principal",
            ),),
        )

    delegated_by = _candidate_delegated_by(content)
    if delegated_by and not _has_active_relationship(approval_snapshot, delegated_by, principal_name):
        return GraphReadinessResult(
            ready=False,
            errors=(GraphGateError(
                code=UNRESOLVED_OR_INACTIVE_RELATIONSHIP,
                message=f'This candidate states authority delegated by "{delegated_by}" to "{principal_name}", '
                        "but no active delegation or escalation relationship between them exists in the "
                        "approved Authority Graph version.",
                path="constraints.delegated_by",
            ),),
        )

    return GraphReadinessResult(ready=True, resolved_principal_name=principal_name)
