"""Decision Intelligence: pure CSV-building helpers shared by every real
export this module ships (Priority Questions, Replay results) -- no
database access (domain/ may never import app.db).

Spreadsheet-formula-injection guard (CSV injection, OWASP's own name for
this): a cell whose value starts with `=`, `+`, `-`, or `@` can be
interpreted by Excel/Sheets/LibreOffice as a formula when the exported
file is later opened, not as literal text -- a real risk for any export
that includes human-entered free text (a Case's `external_ref`, a
Question's `title`, a Replay result's `notes`, ...). This module's
chosen mitigation (one of two standard, defensible options; documented
here per this feature's own brief) is the "leading apostrophe" convention
every major spreadsheet application already honors: prefix a bare `'`
onto any value starting with one of those four characters. Opening the
file renders the value as the harmless literal text `'=2+2` rather than
evaluating it as a formula, while the apostrophe is invisible in the
cell's displayed content. The alternative (wrapping the value in a
leading `\t`, or stripping the leading character) was not chosen because
it would silently alter the stored data's own meaning when re-imported;
prefixing is reversible and visibly marks what happened.

Critically: this sanitization happens ONLY here, at export/egress time.
The actual stored value (e.g. in DICase.facts or DIImportJob.row_errors)
is never mutated -- see csv_import.py and di_import_service.py, which
store exactly what was uploaded, raw."""

from __future__ import annotations

import csv
import io
from typing import Any

_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@")


def sanitize_csv_cell(value: Any) -> Any:
    """Returns `value` unchanged unless it is a string starting with one
    of the four characters a spreadsheet application would interpret as
    the start of a formula, in which case a single leading `'` is
    prefixed. Non-string values (None, numbers, bools) pass through
    untouched -- only text can carry an injected formula."""
    if isinstance(value, str) and value.startswith(_FORMULA_TRIGGER_CHARS):
        return "'" + value
    return value


def build_csv(header: list[str], rows: list[list[Any]]) -> str:
    """Builds a real CSV document (CRLF line endings, RFC 4180 quoting via
    the standard library's own `csv` module) as a single string, sanitizing
    every cell with `sanitize_csv_cell` first. Used by both of this
    module's real export endpoints (Priority Questions, Replay results) so
    the injection guard can never be forgotten by a future third export."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow([sanitize_csv_cell(cell) for cell in row])
    return buffer.getvalue()
