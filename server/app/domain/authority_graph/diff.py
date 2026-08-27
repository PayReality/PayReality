"""Authority Graph version diff (GitHub issue #5).

Pure, deterministic comparison of two AuthorityGraphApproval.
evidence_snapshot dicts -- same discipline as this package's own
compilation_gate.py: no DB calls, no LLM calls, no network calls, never
mutates either input. The caller (services/ai_authority_builder_service.py's
diff_graph_approvals) is responsible for fetching both approvals and
verifying they belong to the same corpus/organization before calling this
module; this module trusts its inputs completely and knows nothing about
corpora, organizations, or the database.

Identity for principals/relationships/conflicts/gaps is each item's own
"id" key, already present in evidence_snapshot (the underlying
AuthorityPrincipal/AuthorityRelationship/AuthorityConflict/AuthorityGap row
id). This is stable across a corpus's own approval history today because
run_extraction only ever runs once per corpus (every later reviewer action
mutates an existing row rather than creating a new one) -- not a
deliberately designed cross-version identity scheme. If a "re-extract this
corpus" capability is ever added, this assumption needs re-verifying; it is
not re-verified here.

An item present in both snapshots under the same id, with any other field
different, is "changed" (before/after values recorded per differing
field). Present only in "to" is "added". Present only in "from" is
"removed". Resources, operations, and questions are not part of
evidence_snapshot today and so cannot be diffed -- not a limitation of
this module, a limitation of what gets captured at approval time
(disclosed, not silently absent).
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FieldChange:
    field: str
    before: Any
    after: Any


@dataclass(frozen=True)
class ChangedItem:
    id: str
    before: dict[str, Any]
    after: dict[str, Any]
    changed_fields: tuple[FieldChange, ...]


@dataclass(frozen=True)
class ItemDiff:
    added: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    removed: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    changed: tuple[ChangedItem, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CoverageDiff:
    before: dict[str, Any]
    after: dict[str, Any]
    changed_fields: tuple[FieldChange, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GraphSnapshotDiff:
    principals: ItemDiff
    relationships: ItemDiff
    conflicts: ItemDiff
    gaps: ItemDiff
    coverage: CoverageDiff


def _index_by_id(items: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in (items or []) if isinstance(item.get("id"), str)}


def _diff_items(before_list: list[dict[str, Any]] | None, after_list: list[dict[str, Any]] | None) -> ItemDiff:
    before = _index_by_id(before_list)
    after = _index_by_id(after_list)
    added_ids = after.keys() - before.keys()
    removed_ids = before.keys() - after.keys()
    common_ids = before.keys() & after.keys()

    added = tuple(after[i] for i in sorted(added_ids))
    removed = tuple(before[i] for i in sorted(removed_ids))
    changed = []
    for i in sorted(common_ids):
        b, a = before[i], after[i]
        changed_fields = tuple(
            FieldChange(field=k, before=b.get(k), after=a.get(k))
            for k in sorted(set(b) | set(a))
            if k != "id" and b.get(k) != a.get(k)
        )
        if changed_fields:
            changed.append(ChangedItem(id=i, before=b, after=a, changed_fields=changed_fields))
    return ItemDiff(added=added, removed=removed, changed=tuple(changed))


def _diff_coverage(before: dict[str, Any] | None, after: dict[str, Any] | None) -> CoverageDiff:
    before = before or {}
    after = after or {}
    changed_fields = tuple(
        FieldChange(field=k, before=before.get(k), after=after.get(k))
        for k in sorted(set(before) | set(after))
        if before.get(k) != after.get(k)
    )
    return CoverageDiff(before=before, after=after, changed_fields=changed_fields)


def diff_graph_snapshots(from_snapshot: dict[str, Any], to_snapshot: dict[str, Any]) -> GraphSnapshotDiff:
    """Two identical snapshots (including the identical-object case)
    produce an empty diff in every section -- this function never
    assumes `from_snapshot is not to_snapshot`, and never writes into
    either dict."""
    return GraphSnapshotDiff(
        principals=_diff_items(from_snapshot.get("principals"), to_snapshot.get("principals")),
        relationships=_diff_items(from_snapshot.get("relationships"), to_snapshot.get("relationships")),
        conflicts=_diff_items(from_snapshot.get("conflicts"), to_snapshot.get("conflicts")),
        gaps=_diff_items(from_snapshot.get("gaps"), to_snapshot.get("gaps")),
        coverage=_diff_coverage(from_snapshot.get("coverage"), to_snapshot.get("coverage")),
    )
