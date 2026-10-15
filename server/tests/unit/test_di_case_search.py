"""Decision Intelligence: unit tests for the server-side case search
query building (Feature: server-side case search). Tests
`di_case_service._apply_search_filter` by compiling the resulting
SQLAlchemy statement to real Postgres SQL text and inspecting it --
SQLAlchemy Core statement construction is pure/lazy, so this needs no
database connection, only a dialect to compile against."""

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.db.models import DICase
from app.services.di_case_service import _apply_search_filter


def _compiled(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_no_q_leaves_the_statement_unchanged():
    base = select(DICase)
    result = _apply_search_filter(base, None)
    assert result is base


def test_empty_string_q_leaves_the_statement_unchanged():
    base = select(DICase)
    result = _apply_search_filter(base, "")
    assert result is base


def test_q_adds_an_ilike_clause_against_external_ref():
    stmt = _apply_search_filter(select(DICase), "refund")
    sql = _compiled(stmt)
    assert "ILIKE" in sql
    assert "external_ref" in sql
    assert "%refund%" in sql


def test_q_adds_an_ilike_clause_against_facts_cast_to_text():
    stmt = _apply_search_filter(select(DICase), "photo_evidence")
    sql = _compiled(stmt)
    assert "facts" in sql
    assert "CAST" in sql.upper() or "::text" in sql.lower() or "text" in sql.lower()
    assert sql.upper().count("ILIKE") == 2  # one for external_ref, one for facts::text


def test_q_clauses_are_combined_with_or_not_and():
    stmt = _apply_search_filter(select(DICase), "x")
    sql = _compiled(stmt)
    assert " OR " in sql.upper()
