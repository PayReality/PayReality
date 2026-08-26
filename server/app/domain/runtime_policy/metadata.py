"""Metadata and audit trail: descriptive and provenance information.

Neither one ever participates in a decision's outcome. If a change to a
RuntimePolicy's Metadata or AuditTrail would change what it evaluates to
for a given Intent, that information belongs in Conditions or
Constraints instead, not here.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Metadata:
    owner: str | None = None
    created_by: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    # Authority Graph -> RuntimePolicy Compilation Gate: additive,
    # nullable, mirroring Constraints.authority_id's own established
    # pattern (a string id, stamped once at promotion, never
    # recomputed). All five are set together, only by
    # ai_policy_builder_service.promote_candidate, only when a
    # corpus-scoped candidate's promotion was gated on -- and
    # succeeded against -- a specific AuthorityGraphApproval.
    # `source_type` is "authority_graph" for a graph-derived policy and
    # None for every other policy (manually authored in Policy Studio,
    # or promoted from a standalone/non-corpus AI Policy Builder
    # candidate) -- a manually-authored policy must never carry fake
    # graph provenance, so these five stay None together or are set
    # together, never partially.
    source_type: str | None = None
    source_corpus_id: str | None = None
    source_graph_approval_id: str | None = None
    source_graph_version: int | None = None
    source_candidate_id: str | None = None


@dataclass(frozen=True)
class AuditTrail:
    """created/modified/approved/deployed are the four events named in
    the spec this implements. The *_by actor fields for the latter three
    are an addition beyond the literal spec: an audit trail that records
    only *when* something happened and not *who* did it is missing the
    half that actually matters for an enterprise audit, and `created_by`
    already exists on Metadata as a precedent for recording identity
    alongside an event. Until real human authentication exists
    (VERSION_3_ROADMAP.md), these remain free-text identity strings, the
    same honest limitation `resolved_by`/`reviewer_id` already have
    elsewhere in this system.
    """

    created: datetime
    modified: datetime | None = None
    approved: datetime | None = None
    deployed: datetime | None = None
    modified_by: str | None = None
    approved_by: str | None = None
    deployed_by: str | None = None
