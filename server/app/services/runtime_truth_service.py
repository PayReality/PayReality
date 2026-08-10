"""Runtime Truth (Runtime Governance Architecture, Phase 3 --
30_PHASE_3_RUNTIME_TRUTH_SPEC.md): the resolution boundary, named and
isolated as its own module for the first time.

This introduces no new logic. `submit_intent` (services/intent_service.py)
already performed exactly these two steps, in this exact order, before
ever calling decision_engine.evaluate() -- a Principal Directory lookup,
then Runtime Authority Context assembly (services/authority_context_service.py,
itself unchanged by this phase). The boundary between "resolving what is
true" and "evaluating whether it's permitted" already existed as two
separate function calls in two separate modules; it was never blurred.
This module only gives that already-existing boundary a name and a single
call site, so a reader (or a future test) can see "Runtime Truth" as one
thing rather than two calls scattered across submit_intent's body.

Deliberately not built: a Resolver Intelligence framework, a fact
registry, or any new resolution source. Every fact resolved here comes
from exactly the same two sources documented in
29_PHASE_3_RESOLVER_INTELLIGENCE_SPEC.md (Principal Directory, Runtime
Context Service) -- this module composes them, it does not add a third.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Agent, Principal
from app.services.authority_context_service import resolve_runtime_authority_context


@dataclass(frozen=True)
class ResolvedFacts:
    """Runtime Truth's output: everything decision_engine.evaluate() and
    Decision Evidence need that isn't already on the Intent itself.
    Deliberately a plain, frozen data holder -- not a new abstraction,
    just a name for the two values submit_intent already carried
    separately as local variables."""

    principal: Principal | None
    principal_name: str
    authority_context: dict


def resolve(db: Session, agent: Agent, amount: float | None) -> ResolvedFacts:
    """Resolve every fact Runtime Authority needs, given only the Agent
    and the Intent's own amount -- identical to submit_intent's prior
    inline sequence, moved here unchanged:

    1. Principal Directory: resolve the Agent's acting-for Principal.
       RuntimePolicy.scope.principal is authored as the Principal's
       free-form *name* (AUTHORING_ARCHITECTURE.md), never a foreign key,
       so the raw UUID must be resolved to a name before it can ever
       reach a compiled policy's scope match.
    2. Runtime Context Service: assemble the Runtime Authority Context
       enrichment (organization/business_unit/department/team/role/
       risk_level/delegations) from that Principal.

    Resolution ends here. Everything returned is handed, unmodified, to
    decision_engine.evaluate() -- which never resolves anything itself,
    and to Decision Evidence -- which records these exact values, never
    recomputing them."""
    principal = db.get(Principal, agent.acting_for_principal_id)
    principal_name = principal.name if principal else str(agent.acting_for_principal_id)
    authority_context = resolve_runtime_authority_context(db, principal, amount)
    return ResolvedFacts(
        principal=principal, principal_name=principal_name, authority_context=authority_context
    )
