"""Decision Intelligence: pure-function unit tests for csv_export.py
(spreadsheet-formula-injection guard + CSV building). No DB."""

from app.domain.decision_intelligence.csv_export import build_csv, sanitize_csv_cell


def test_sanitize_leaves_normal_strings_untouched():
    assert sanitize_csv_cell("CASE-1001") == "CASE-1001"
    assert sanitize_csv_cell("") == ""


def test_sanitize_prefixes_a_leading_apostrophe_for_each_trigger_character():
    assert sanitize_csv_cell("=2+2") == "'=2+2"
    assert sanitize_csv_cell("+1234567890") == "'+1234567890"
    assert sanitize_csv_cell("-2+3") == "'-2+3"
    assert sanitize_csv_cell("@SUM(A1:A2)") == "'@SUM(A1:A2)"


def test_sanitize_only_applies_to_strings_not_numbers_or_none():
    assert sanitize_csv_cell(42) == 42
    assert sanitize_csv_cell(None) is None
    assert sanitize_csv_cell(3.14) == 3.14


def test_sanitize_does_not_touch_a_character_in_the_middle_of_a_string():
    assert sanitize_csv_cell("total=100") == "total=100"


def test_build_csv_produces_a_real_rfc4180_document_with_header():
    csv_text = build_csv(["id", "title"], [["1", "Refund cutoff"], ["2", "Escalation threshold"]])
    lines = csv_text.strip("\r\n").split("\r\n")
    assert lines[0] == "id,title"
    assert lines[1] == "1,Refund cutoff"
    assert lines[2] == "2,Escalation threshold"


def test_build_csv_sanitizes_every_cell_before_writing():
    csv_text = build_csv(["title"], [["=cmd|' /c calc'!A1"]])
    assert "'=cmd" in csv_text
    assert not csv_text.startswith("=cmd")


def test_build_csv_quotes_a_value_containing_a_comma():
    csv_text = build_csv(["notes"], [["needs review, urgently"]])
    assert '"needs review, urgently"' in csv_text
