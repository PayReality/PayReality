"""Decision Intelligence: pure-function unit tests for csv_import.py
(Feature: CSV case import). No DB -- validate_and_map_csv_rows takes
plain dicts (exactly what csv.DictReader produces), matching this
module's own "domain/ never touches app.db" discipline."""

import pytest

from app.domain.decision_intelligence.csv_import import (
    InvalidColumnMappingError,
    validate_and_map_csv_rows,
    validate_and_map_row,
)


def test_valid_row_with_explicit_mapping_and_unmapped_facts_columns():
    mapping = {"Ref": "external_ref", "Decision": "human_decision"}
    rows = [{"Ref": "CASE-1", "Decision": '{"outcome": "approve"}', "Amount": "150", "Notes": "fine"}]

    [result] = validate_and_map_csv_rows(rows, mapping, existing_external_refs=set())

    assert result.is_valid
    assert result.case.external_ref == "CASE-1"
    assert result.case.human_decision == {"outcome": "approve"}
    # Unmapped columns fold into facts under their own header name.
    assert result.case.facts["Amount"] == 150  # opportunistically JSON-parsed
    assert result.case.facts["Notes"] == "fine"  # falls back to raw string


def test_excluded_column_is_dropped_entirely():
    mapping = {"Internal Note": "exclude"}
    rows = [{"Internal Note": "do not import this", "Amount": "50"}]

    [result] = validate_and_map_csv_rows(rows, mapping, existing_external_refs=set())

    assert result.is_valid
    assert "Internal Note" not in result.case.facts
    assert result.case.facts == {"Amount": 50}


def test_completely_empty_row_is_rejected():
    rows = [{"Ref": "", "Amount": "   "}]
    [result] = validate_and_map_csv_rows(rows, {"Ref": "external_ref"}, existing_external_refs=set())
    assert not result.is_valid
    assert result.errors == ["empty_row"]


def test_invalid_human_decision_json_is_a_per_row_error_not_a_crash():
    mapping = {"Decision": "human_decision"}
    rows = [{"Decision": "not valid json", "Amount": "10"}]

    [result] = validate_and_map_csv_rows(rows, mapping, existing_external_refs=set())

    assert not result.is_valid
    assert any("invalid_human_decision_json" in e for e in result.errors)


def test_human_decision_must_be_a_json_object_not_a_bare_scalar():
    mapping = {"Decision": "human_decision"}
    rows = [{"Decision": "42"}]  # valid JSON, but not an object

    [result] = validate_and_map_csv_rows(rows, mapping, existing_external_refs=set())

    assert not result.is_valid
    assert any("invalid_human_decision_json" in e for e in result.errors)


def test_duplicate_external_ref_against_existing_cases_is_rejected():
    mapping = {"Ref": "external_ref"}
    rows = [{"Ref": "CASE-1", "Amount": "10"}]

    [result] = validate_and_map_csv_rows(rows, mapping, existing_external_refs={"CASE-1"})

    assert not result.is_valid
    assert any("duplicate_external_ref" in e for e in result.errors)


def test_duplicate_external_ref_within_the_same_file_flags_the_second_occurrence_only():
    mapping = {"Ref": "external_ref"}
    rows = [
        {"Ref": "CASE-1", "Amount": "10"},
        {"Ref": "CASE-1", "Amount": "20"},
    ]

    first, second = validate_and_map_csv_rows(rows, mapping, existing_external_refs=set())

    assert first.is_valid
    assert not second.is_valid
    assert any("duplicate_external_ref" in e for e in second.errors)


def test_a_bad_row_does_not_affect_validation_of_other_rows():
    mapping = {"Ref": "external_ref", "Decision": "human_decision"}
    rows = [
        {"Ref": "CASE-1", "Decision": "{}"},
        {"Ref": "", "Decision": "not json"},  # row 2: invalid JSON, not empty (Ref present but blank)
        {"Ref": "CASE-3", "Decision": "{}"},
    ]

    results = validate_and_map_csv_rows(rows, mapping, existing_external_refs=set())

    assert results[0].is_valid
    assert not results[1].is_valid
    assert results[2].is_valid
    assert results[0].row_number == 1
    assert results[1].row_number == 2
    assert results[2].row_number == 3


def test_unknown_mapping_target_raises_invalid_column_mapping_error():
    mapping = {"Ref": "not_a_real_target"}
    with pytest.raises(InvalidColumnMappingError):
        validate_and_map_csv_rows([{"Ref": "CASE-1"}], mapping, existing_external_refs=set())


def test_seen_external_refs_in_file_is_mutated_for_streaming_style_callers():
    seen: set[str] = set()
    row = {"Ref": "CASE-9"}
    result = validate_and_map_row(row, 1, {"Ref": "external_ref"}, existing_external_refs=set(), seen_external_refs_in_file=seen)
    assert result.is_valid
    assert "CASE-9" in seen
