"""Decision Intelligence: pure row-level validation/mapping for the CSV
case-import feature. Takes plain dicts (one per CSV row, as `csv.
DictReader` already produces) and a column-mapping dict, and returns a
structured, per-row verdict -- never touches the database or an ORM
object (domain/ may never import app.db, see
test_architectural_boundaries.py); di_import_service.py is the only thing
that turns a valid `MappedCaseRow` into a real `DICase` insert.

Column mapping: `column_mapping` is `{csv_header: target}`, where target
is one of the five DICase fields this feature supports
(`external_ref`, `facts`, `human_decision`, `escalation_reason`,
`outcome`) or the literal `"exclude"` to drop a column entirely. Any CSV
header NOT present as a key in `column_mapping` at all is treated as
unmapped and folded into `facts` under its own header name -- the
brief's own stated default ("remaining unmapped columns become facts
keys unless explicitly excluded"). A header can also be explicitly
mapped to `"facts"`, which has the identical effect but documents the
mapping intent instead of leaving it implicit.

Required/validated per row (this module's own deliberate interpretation
-- the brief left "required fields present" open):
  - A row where every cell is empty/whitespace is rejected outright
    (`empty_row`) -- an all-blank CSV line carries no evidence at all,
    not even a partial case.
  - A cell mapped to `human_decision` is the one field this product
    models as structured JSON (DICase.human_decision is JSONB), so a
    non-empty cell mapped there MUST be valid JSON
    (`invalid_human_decision_json`); `facts`-destined cells are stored
    as-is (JSON-parsed opportunistically, falling back to the raw string)
    since DICase.facts is deliberately schema-less (see DICase's own
    model docstring) and a facts value is never rejected for not being
    JSON.
  - `external_ref` duplicate detection happens at two levels, both
    reported as the same `duplicate_external_ref` error: against
    `existing_external_refs` (already-persisted cases in this workflow,
    passed in by the caller) and against every `external_ref` already
    seen earlier IN THIS SAME FILE -- the first occurrence of a ref wins
    and imports normally, a later occurrence in the same file is flagged
    exactly like a collision with an existing database row would be. The
    brief only required the former; the latter is this module's own
    judgment call, flagged here rather than silently added, since a CSV
    with two rows sharing a ref is exactly as ambiguous as one row
    colliding with the database.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

TARGET_FIELDS = frozenset({"external_ref", "facts", "human_decision", "escalation_reason", "outcome"})
EXCLUDE_TARGET = "exclude"


@dataclass(frozen=True)
class MappedCaseRow:
    """The DICase-shaped fields successfully extracted from one valid CSV
    row. `facts` always comes out as a dict, never None, matching
    DICase.facts' own non-nullable JSONB column."""

    row_number: int
    external_ref: str | None
    facts: dict
    human_decision: dict | None
    escalation_reason: str | None
    outcome: str | None


@dataclass(frozen=True)
class RowValidationResult:
    row_number: int
    case: MappedCaseRow | None
    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.case is not None and not self.errors


class InvalidColumnMappingError(ValueError):
    """Raised when `column_mapping` itself is malformed -- never for a
    per-row data problem, which is reported via RowValidationResult.errors
    instead so one bad row never aborts the whole file."""


def _validate_column_mapping(column_mapping: dict[str, str]) -> None:
    for header, target in column_mapping.items():
        if target != EXCLUDE_TARGET and target not in TARGET_FIELDS:
            raise InvalidColumnMappingError(
                f"unknown_mapping_target: column {header!r} maps to {target!r}, "
                f"expected one of {sorted(TARGET_FIELDS)} or {EXCLUDE_TARGET!r}"
            )


def _try_parse_json(raw: str):
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw


def validate_and_map_row(
    row: dict[str, str | None],
    row_number: int,
    column_mapping: dict[str, str],
    existing_external_refs: set[str],
    seen_external_refs_in_file: set[str],
) -> RowValidationResult:
    """Validates and maps exactly one CSV row. `seen_external_refs_in_file`
    is mutated in place (a ref from this row is added to it on success) so
    that a caller iterating rows in order gets correct intra-file
    duplicate detection for free -- the same pattern `csv.DictReader`
    itself is consumed with, one row at a time."""
    cells = {k: (v if v is not None else "") for k, v in row.items()}
    if all(not str(v).strip() for v in cells.values()):
        return RowValidationResult(row_number=row_number, case=None, errors=["empty_row"])

    errors: list[str] = []
    external_ref: str | None = None
    human_decision: dict | None = None
    escalation_reason: str | None = None
    outcome: str | None = None
    facts: dict = {}

    for header, raw_value in cells.items():
        value = str(raw_value).strip()
        target = column_mapping.get(header)

        if target == EXCLUDE_TARGET:
            continue
        if target is None:
            target = "facts"  # unmapped columns default into facts, per module docstring

        if not value:
            continue  # an empty cell contributes nothing, regardless of target

        if target == "external_ref":
            external_ref = value
        elif target == "human_decision":
            try:
                parsed = json.loads(value)
            except (json.JSONDecodeError, ValueError) as e:
                errors.append(f"invalid_human_decision_json: row {row_number} column {header!r}: {e}")
                continue
            if not isinstance(parsed, dict):
                errors.append(
                    f"invalid_human_decision_json: row {row_number} column {header!r}: "
                    f"must be a JSON object, got {type(parsed).__name__}"
                )
                continue
            human_decision = parsed
        elif target == "escalation_reason":
            escalation_reason = value
        elif target == "outcome":
            outcome = value
        elif target == "facts":
            facts[header] = _try_parse_json(value)

    if external_ref is not None:
        if external_ref in existing_external_refs or external_ref in seen_external_refs_in_file:
            errors.append(f"duplicate_external_ref: {external_ref!r}")
        else:
            seen_external_refs_in_file.add(external_ref)

    if errors:
        return RowValidationResult(row_number=row_number, case=None, errors=errors)

    return RowValidationResult(
        row_number=row_number,
        case=MappedCaseRow(
            row_number=row_number,
            external_ref=external_ref,
            facts=facts,
            human_decision=human_decision,
            escalation_reason=escalation_reason,
            outcome=outcome,
        ),
    )


def validate_and_map_csv_rows(
    rows: list[dict[str, str | None]],
    column_mapping: dict[str, str],
    existing_external_refs: set[str],
) -> list[RowValidationResult]:
    """Validates a whole parsed CSV (already `csv.DictReader`'d into plain
    dicts) against `column_mapping`, row by row, in file order. Raises
    InvalidColumnMappingError immediately if the mapping itself is
    malformed -- that's a request-shape problem, not a per-row data
    problem, so it is never folded into a per-row error list."""
    _validate_column_mapping(column_mapping)
    seen_in_file: set[str] = set()
    return [
        validate_and_map_row(row, i, column_mapping, existing_external_refs, seen_in_file)
        for i, row in enumerate(rows, start=1)
    ]
