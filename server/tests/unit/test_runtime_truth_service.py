"""Runtime Governance Architecture, Phase 3
(30_PHASE_3_RUNTIME_TRUTH_SPEC.md): runtime_truth_service.resolve() itself
touches the database (Principal Directory lookup, then
authority_context_service.resolve_runtime_authority_context, which
queries four more tables) -- exactly like the two calls it replaces
already did, and exactly like every other DB-dependent code path in this
repository, it has no unit-level DB fixture (confirmed: this codebase has
none anywhere, by design -- DB-touching behavior is verified against real
production/integration runs, not mocked). This phase does not introduce
a new testing pattern to work around that; it inherits the same
verification story the two calls already had before being named and
composed into one function.

What *is* directly, honestly unit-testable without a database is the
shape of Runtime Truth's own output -- ResolvedFacts is a plain, frozen
data holder, and this file tests exactly that, no more."""

from app.services.runtime_truth_service import ResolvedFacts


def test_resolved_facts_holds_exactly_what_was_given():
    facts = ResolvedFacts(
        principal=None,
        principal_name="unresolved-principal-id",
        authority_context={"risk_level": "LOW"},
    )
    assert facts.principal is None
    assert facts.principal_name == "unresolved-principal-id"
    assert facts.authority_context == {"risk_level": "LOW"}


def test_resolved_facts_is_frozen():
    """Runtime Truth's output must not be mutated after resolution --
    Decision Evidence and Runtime Authority both consume the same
    instance, and neither is allowed to be the one that changes what the
    other sees."""
    facts = ResolvedFacts(principal=None, principal_name="x", authority_context={})
    try:
        facts.principal_name = "y"
        assert False, "ResolvedFacts must be immutable"
    except AttributeError:
        pass
