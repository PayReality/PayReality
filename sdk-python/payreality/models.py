"""Plain data returned by the SDK's public methods. Nothing here talks
to the network or the filesystem; these are just typed, immutable
results.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .exceptions import AuthorizationDenied, HumanReviewRequired

ALLOW = "ALLOW"
DENY = "DENY"
HUMAN_REVIEW = "HUMAN_REVIEW"


@dataclass(frozen=True)
class Decision:
    """The result of `agent.authorize()` or `agent.get_decision()`.
    Never raised as an exception by `authorize()` itself: ALLOW, DENY,
    and HUMAN_REVIEW are all normal, expected outcomes of a real
    authorization check, exactly like a declined charge is a normal
    outcome for a payments API, not a program error."""

    outcome: str  # "ALLOW" | "DENY" | "HUMAN_REVIEW"
    decision_id: str
    evidence_id: str | None
    reason: str | None
    explanation: str | None
    status: str  # "RESOLVED" | "PENDING"
    evaluated_mandates: tuple[str, ...] = field(default_factory=tuple)
    resolution: "Resolution | None" = None
    # Human Review Continuation (issue #10): the caller's own external
    # workflow/job/request id, echoed back exactly as submitted on
    # authorize() -- lets a caller that resumes polling in a fresh
    # process (no local memory of which correlation_id it used) confirm
    # it has the right decision. Trace metadata only; never consulted by
    # this SDK for anything.
    correlation_id: str | None = None
    # Set from get_decision() (the server's GetDecisionResponse always
    # carries it); None from authorize()'s own response shape, which
    # doesn't include it today.
    created_at: str | None = None

    @property
    def allowed(self) -> bool:
        return self.outcome == ALLOW

    @property
    def denied(self) -> bool:
        return self.outcome == DENY

    @property
    def requires_human_review(self) -> bool:
        return self.outcome == HUMAN_REVIEW

    @property
    def pending(self) -> bool:
        return self.status == "PENDING"

    def raise_for_outcome(self) -> None:
        """Opt-in exception-flow control for callers who prefer it over
        checking `.allowed`, mirroring `requests.Response.raise_for_status()`.
        Does nothing on ALLOW."""
        if self.outcome == DENY:
            raise AuthorizationDenied(self)
        if self.outcome == HUMAN_REVIEW:
            raise HumanReviewRequired(self)


@dataclass(frozen=True)
class Resolution:
    """How a HUMAN_REVIEW decision was ultimately resolved, once it has
    been. Only present on a Decision fetched after resolution."""

    resolution: str  # "approved" | "denied"
    resolved_by: str
    reason: str | None
    # Human Review Continuation (issue #10): when the resolution was
    # recorded (GetDecisionResponse.resolution.created_at) -- an ISO
    # 8601 string, matching how every other timestamp already crosses
    # the wire in this SDK (see Decision.created_at above).
    resolved_at: str | None = None


@dataclass(frozen=True)
class RegisteredAgent:
    """What `agent.register()` returns: the identifiers the server
    assigned. These are also what gets persisted locally so a later
    `Agent(private_key=...)` using the same key doesn't need to
    register again.

    `status` (added in Phase 9, AGENT_LIFECYCLE.md) mirrors the agent's
    server-side lifecycle status locally, so `authorize()` can refuse a
    known-retired or known-revoked identity immediately, without a
    network round trip, the same way `authorize()` already refuses a
    principal mismatch locally. Defaults to "active" so credential files
    written by an older SDK version (with no status key at all) still
    load correctly via `RegisteredAgent(**record)`."""

    agent_id: str
    certificate_id: str
    principal_id: str
    principal_name: str
    name: str
    status: str = "active"
