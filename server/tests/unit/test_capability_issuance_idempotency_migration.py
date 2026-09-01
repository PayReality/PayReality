"""Trusted Integration Architecture, Phase 5.1: unit-tests the pure
row-selection decision migration d4e8b1a6f2c9 uses to deduplicate any
pre-existing multiple-Capability-per-Decision rows before adding the
new uniqueness constraint. Imported directly from the migration file
itself (no existing precedent for this in the repo, so a plain
importlib.util load, not a new test convention) so the exact logic
that will run in production is what's under test, not a reimplemented
copy that could drift from it.

No database needed: `choose_row_to_keep` is deliberately pure, taking
plain row-like objects and returning one of them -- see the migration
file's own docstring for why it was factored out this way."""

import importlib.util
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic" / "versions" / "d4e8b1a6f2c9_capability_issuance_idempotency.py"
)
_spec = importlib.util.spec_from_file_location("capability_issuance_idempotency_migration", _MIGRATION_PATH)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


@dataclass
class _Row:
    id: uuid.UUID
    consumed_at: datetime | None
    issued_at: datetime


def _row(consumed_at=None, issued_at=None):
    return _Row(id=uuid.uuid4(), consumed_at=consumed_at, issued_at=issued_at or datetime.now(timezone.utc))


NOW = datetime.now(timezone.utc)


def test_keeps_the_only_consumed_row_among_unconsumed_duplicates():
    consumed = _row(consumed_at=NOW, issued_at=NOW - timedelta(minutes=10))
    unconsumed_older = _row(consumed_at=None, issued_at=NOW - timedelta(minutes=20))
    unconsumed_newer = _row(consumed_at=None, issued_at=NOW - timedelta(minutes=1))

    kept = migration.choose_row_to_keep([consumed, unconsumed_older, unconsumed_newer])

    assert kept.id == consumed.id


def test_keeps_the_most_recently_issued_row_when_none_were_consumed():
    older = _row(issued_at=NOW - timedelta(minutes=30))
    newest = _row(issued_at=NOW - timedelta(seconds=5))
    middle = _row(issued_at=NOW - timedelta(minutes=10))

    kept = migration.choose_row_to_keep([older, newest, middle])

    assert kept.id == newest.id


def test_keeps_the_earliest_consumed_row_when_multiple_look_consumed_is_impossible_but_ties_are_handled():
    """Not a realistic production case (see the "more than one consumed"
    test below for the real hostile scenario) -- just confirms the sort
    is stable/correct when exactly one consumed row exists alongside
    several unconsumed ones issued both before and after it."""
    consumed = _row(consumed_at=NOW - timedelta(minutes=2), issued_at=NOW - timedelta(minutes=15))
    later_unconsumed = _row(consumed_at=None, issued_at=NOW - timedelta(seconds=1))

    kept = migration.choose_row_to_keep([consumed, later_unconsumed])

    assert kept.id == consumed.id


def test_raises_when_more_than_one_row_was_independently_consumed():
    """The literal "two executable permissions for one operation"
    scenario this whole phase exists to prevent, if it had somehow
    already happened before this migration ran. Deliberately refuses to
    silently pick one and discard evidence of the other -- see the
    migration's own upgrade() docstring."""
    first_consumed = _row(consumed_at=NOW - timedelta(minutes=5), issued_at=NOW - timedelta(minutes=20))
    second_consumed = _row(consumed_at=NOW - timedelta(minutes=1), issued_at=NOW - timedelta(minutes=10))

    with pytest.raises(ValueError, match="independently consumed"):
        migration.choose_row_to_keep([first_consumed, second_consumed])


def test_single_row_is_trivially_kept():
    only = _row()
    assert migration.choose_row_to_keep([only]).id == only.id
