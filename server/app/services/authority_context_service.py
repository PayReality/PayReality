"""Runtime Authority Context assembly (PHASE_2_RUNTIME_CONTEXT.md): an
ephemeral, request-scoped enrichment built fresh for every Intent,
immediately before the OPA query. Never stored -- merged into the
`context` dict intent_service.py already passes to
decision_engine.evaluate(), under the `authority` key, so a policy's
Condition can reference e.g. `context.authority.department` the moment
it's authored to, with zero change to rego_generator.py,
compile_bundle(), or OPA: dot-path access into `context` already works
for any field today.

Deliberately not a policy pre-filter
(RUNTIME_AUTHORITY_TRANSFORMATION.md Section 8): every active policy is
still evaluated by OPA, unchanged. This only makes richer data available
for a policy's own conditions to reference.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuthorityRelationship, BusinessUnit, Department, Organization, Principal, Team


def classify_risk(amount: float | None) -> str:
    """Moved from intent_service.py's _classify_risk (DOMAIN_REFACTOR_PLAN.md
    item 4 already named this move as a future step): needed here too now,
    since Runtime Authority Context carries risk_level for conditions to
    reference, and importing it back from intent_service would be a
    circular import (intent_service -> this module -> intent_service).
    Thresholds unchanged from the original."""
    if amount is None:
        return "LOW"
    if amount >= 250_000:
        return "CRITICAL"
    if amount >= 100_000:
        return "HIGH"
    if amount >= 50_000:
        return "MEDIUM"
    return "LOW"


def _name_or_none(db: Session, model, entity_id: uuid.UUID | None) -> str | None:
    if entity_id is None:
        return None
    row = db.get(model, entity_id)
    return row.name if row is not None else None


def _active_inbound_delegations(db: Session, principal: Principal) -> list[dict]:
    """Direct (one-hop) delegations granting this Principal authority --
    not a multi-hop chain walk. PHASE_2_RUNTIME_CONTEXT.md's performance
    note: multi-hop resolution is an audit/impact-analysis capability
    (Phase 4), not part of the decision hot path, so this stays a single
    indexed query.

    Post-audit implementation, Priority 2: takes the full Principal, not
    just its id, so the cross-organisation check below can compare
    organizations without a second round-trip for the common (same-org)
    case."""
    now = datetime.now(timezone.utc)
    rows = list(
        db.scalars(
            select(AuthorityRelationship).where(
                AuthorityRelationship.to_principal_id == principal.id,
                AuthorityRelationship.kind == "delegation",
                AuthorityRelationship.status == "active",
            )
        )
    )
    result = []
    for r in rows:
        # Same defensive tzinfo normalization as capability_service.py's
        # own expires_at comparison: a real Postgres timestamptz column
        # already round-trips with tzinfo set, so this is a no-op there;
        # only a naive-datetime backend (e.g. SQLite in tests) would
        # ever hit the `else` branch.
        valid_from = r.valid_from
        if valid_from is not None and valid_from.tzinfo is None:
            valid_from = valid_from.replace(tzinfo=timezone.utc)
        valid_to = r.valid_to
        if valid_to is not None and valid_to.tzinfo is None:
            valid_to = valid_to.replace(tzinfo=timezone.utc)
        if valid_from is not None and valid_from > now:
            continue
        if valid_to is not None and valid_to < now:
            continue
        # AuthorityRelationship.cross_org_approved's own documented
        # intent (db/models.py: "not honored in traversal unless
        # explicitly flagged -- fail-closed default") was never actually
        # enforced here: this function only ever filtered on
        # to_principal_id/kind/status/validity window, never on whether
        # the delegating principal belongs to a different organization.
        # Fail closed: an unapproved cross-org edge is silently excluded
        # from the runtime authority context, the same as if it didn't
        # exist, rather than granting effective authority across a
        # tenant boundary.
        if r.from_principal_id is not None and not r.cross_org_approved:
            from_principal = db.get(Principal, r.from_principal_id)
            if from_principal is not None and from_principal.organization_id != principal.organization_id:
                continue
        result.append(
            {
                "id": str(r.id),
                "from_principal_id": str(r.from_principal_id) if r.from_principal_id else None,
                "resource_id": str(r.resource_id) if r.resource_id else None,
                "operation": r.operation,
            }
        )
    return result


def resolve_runtime_authority_context(
    db: Session, principal: Principal | None, amount: float | None
) -> dict:
    """Given the already-resolved Principal (intent_service.py resolves
    this once via Agent.acting_for_principal_id), assemble the enrichment
    dict merged into decision_engine.evaluate()'s `context` argument.
    Every field is additive: an Intent whose Principal has none of these
    populated yet gets a context with mostly-null fields, never an error.
    """
    if principal is None:
        return {"risk_level": classify_risk(amount), "delegations": [], "delegation_count": 0}

    delegations = _active_inbound_delegations(db, principal)
    return {
        "organization": _name_or_none(db, Organization, principal.organization_id),
        "business_unit": _name_or_none(db, BusinessUnit, principal.business_unit_id),
        "department": _name_or_none(db, Department, principal.department_id),
        "team": _name_or_none(db, Team, principal.team_id),
        "role": principal.role,
        "risk_level": classify_risk(amount),
        "delegations": delegations,
        # Post-audit implementation, Priority 2: the array itself
        # (`delegations`) was already resolved and merged into the OPA
        # input correctly, but a RuntimePolicy Condition had no safe way
        # to reference it -- Operator.EXISTS compiles to a "!= null"
        # check (rego_generator.generate_condition_expression), and this
        # list is never null, only ever empty-or-populated, so an EXISTS
        # condition against `context.authority.delegations` would always
        # be true regardless of whether a delegation actually existed.
        # This scalar count is the smallest correction that makes the
        # already-resolved data safely conditionable with an existing,
        # already-correct operator (GT/GTE), without inventing any new
        # Rego generation case or multi-hop/inheritance semantics.
        "delegation_count": len(delegations),
    }
