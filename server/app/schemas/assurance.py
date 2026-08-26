"""Product Experience Remediation Milestone 1, Phase 6: the bounded,
organisation-scoped Assurance summary contract. Every field here is a
real count or state genuinely computable from existing data (see
assurance_service.get_summary's own docstring for exactly which query
backs each one) -- no invented score, no fabricated trend, nothing a
real backend query can't produce today.
"""

from datetime import datetime

from pydantic import BaseModel


class AssuranceSummaryResponse(BaseModel):
    # Authority health
    total_agents: int
    active_agents: int
    active_policies: int
    policies_review_due: int
    policies_authority_expired: int

    # Runtime activity (all-time, org-scoped; not a fabricated trend --
    # a single point-in-time count, same as everything else here)
    allow_count: int
    deny_count: int
    human_review_count: int

    # Human oversight
    pending_review_count: int
    oldest_pending_review_at: datetime | None = None
    resolved_review_count: int

    # Evidence integrity (counts only -- full chain/signature
    # verification remains a separate, on-demand call to the existing
    # GET /v1/evidence/chain/verify, deliberately not re-run on every
    # summary load)
    evidence_total: int
    evidence_verified: int
    evidence_pending: int
    evidence_rejected: int
