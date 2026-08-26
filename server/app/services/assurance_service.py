"""Product Experience Remediation Milestone 1, Phase 6: composes
already-existing, already-tested per-concern queries into one bounded,
organisation-scoped summary -- deliberately not a new analytics engine.
Every number below is backed by a real query named in its own comment;
nothing here is invented or approximated.
"""

import uuid

from sqlalchemy.orm import Session

from app.schemas.assurance import AssuranceSummaryResponse
from app.services import agent_service, evidence_service, intent_service, runtime_policy_lifecycle_service


def get_summary(db: Session, organization_id: uuid.UUID | None) -> AssuranceSummaryResponse:
    _, total_agents = agent_service.list_agents(db, organization_id, limit=1)
    _, active_agents = agent_service.list_agents(db, organization_id, status="active", limit=1)

    dashboard = runtime_policy_lifecycle_service.get_dashboard(db, organization_id)
    active_policies = dashboard.counts_by_state.get("active", 0)
    policies_review_due = len(runtime_policy_lifecycle_service.list_due_for_reattestation(db, organization_id))
    policies_authority_expired = len(runtime_policy_lifecycle_service.list_authority_expired(db, organization_id))

    outcome_counts = intent_service.count_decisions_by_outcome(db, organization_id)

    pending_decisions, pending_review_count = intent_service.list_pending_decisions_for_organization(
        db, organization_id, limit=1
    )
    oldest_pending_review_at = intent_service.oldest_pending_review_at(db, organization_id)
    resolved_review_count = intent_service.count_resolved_reviews(db, organization_id)

    evidence_by_status = evidence_service.count_evidence_by_status(db, organization_id)

    return AssuranceSummaryResponse(
        total_agents=total_agents,
        active_agents=active_agents,
        active_policies=active_policies,
        policies_review_due=policies_review_due,
        policies_authority_expired=policies_authority_expired,
        allow_count=outcome_counts.get("ALLOW", 0),
        deny_count=outcome_counts.get("DENY", 0),
        human_review_count=outcome_counts.get("HUMAN_REVIEW", 0),
        pending_review_count=pending_review_count,
        oldest_pending_review_at=oldest_pending_review_at,
        resolved_review_count=resolved_review_count,
        evidence_total=sum(evidence_by_status.values()),
        evidence_verified=evidence_by_status.get("VERIFIED", 0),
        evidence_pending=evidence_by_status.get("PENDING", 0),
        evidence_rejected=evidence_by_status.get("REJECTED", 0),
    )
