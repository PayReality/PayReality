"""Runtime Governance Architecture, Phase 5 (45_PHASE_5_BROKEN_PROMISE_REPORT.md):
Policy Determinism promises the same active-policy set always compiles to
the same bundle_hash. Both places runtime_policy_service.py reads "every
currently-active RuntimePolicy" from the database
(reconcile_opa_with_active_policies, _other_active_policies) previously
issued their SELECT with no ORDER BY -- meaning the row order Postgres
happened to return (never guaranteed without one) fed directly into
compile_bundle's policy list, and build_bundle serializes policies in
whatever order it's given. Two compiles of the identical active set could
therefore produce two different bundle_hash values with nothing about the
policies themselves having changed.

This codebase has no DB-backed unit-test fixture anywhere (confirmed
before writing this file, consistent with every prior phase's own
findings) -- so rather than standing up a real database to prove ordering
behavior end-to-end, this test does the same thing test_architectural_
boundaries.py's import checks do: verify the *statement* itself carries
the guarantee, with a fake Session that only needs to record what
SQLAlchemy Core statement it was asked to run.
"""

from app.services.runtime_policy_service import _other_active_policies, reconcile_opa_with_active_policies


class _RecordingSession:
    """Records the Select statement it was asked to run; never touches a
    real database. `scalars` returns an empty result, which is enough --
    this test cares only about the statement's own ORDER BY clause, not
    about any row it would return."""

    def __init__(self):
        self.statements = []

    def scalars(self, stmt):
        self.statements.append(stmt)
        return []


def test_other_active_policies_query_is_ordered():
    db = _RecordingSession()
    _other_active_policies(db, exclude_policy_key="00000000-0000-0000-0000-000000000000")
    assert len(db.statements) == 1
    assert "ORDER BY" in str(db.statements[0])


def test_reconcile_active_policies_query_is_ordered():
    db = _RecordingSession()
    reconcile_opa_with_active_policies(db)
    assert len(db.statements) == 1
    assert "ORDER BY" in str(db.statements[0])
