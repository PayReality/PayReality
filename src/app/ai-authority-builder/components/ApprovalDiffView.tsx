import { useEffect, useState } from "react";
import { aiAuthorityBuilderApi } from "../api";
import { describeApiError } from "../../live/format";
import type { ChangedItem, GraphApprovalDiff, ItemDiff } from "../types";
import { SkeletonRows } from "../../components/ui/skeleton";

// Authority Graph Lineage & Versioning (issue #5): a deterministic,
// same-corpus comparison of two approved graph versions, rendered inline
// under the approval it belongs to -- not a new dashboard, just the
// existing Approval History section's own "View changes" disclosure.
// Change type is always communicated by a text label (Added/Removed/
// Changed), never by color alone -- color here is decoration on top of
// text that already carries the meaning.

const ITEM_LABEL = (kind: string, item: Record<string, unknown>): string => {
  if (typeof item.name === "string") return item.name;
  if (kind === "relationships" && typeof item.from_principal === "string" && typeof item.to_principal === "string") {
    return `${item.from_principal} → ${item.to_principal}`;
  }
  if (typeof item.description === "string") return item.description;
  return typeof item.id === "string" ? item.id : "(unknown)";
};

function ChangedRow({ kind, item }: { kind: string; item: ChangedItem }) {
  return (
    <li style={{ marginBottom: 4 }}>
      <span style={{ color: "var(--pr-warning-amber)", fontWeight: 500 }}>Changed</span>{" "}
      <span style={{ color: "var(--pr-text-primary)" }}>{ITEM_LABEL(kind, item.after)}</span>
      <ul style={{ marginTop: 2, marginLeft: 16, color: "var(--pr-text-muted)" }}>
        {item.changed_fields.map((f) => (
          <li key={f.field}>
            {f.field}: <span style={{ textDecoration: "line-through" }}>{String(f.before ?? "—")}</span>
            {" → "}
            {String(f.after ?? "—")}
          </li>
        ))}
      </ul>
    </li>
  );
}

function ItemDiffSection({ title, kind, diff }: { title: string; kind: string; diff: ItemDiff }) {
  const total = diff.added.length + diff.removed.length + diff.changed.length;
  if (total === 0) return null;
  return (
    <div style={{ marginTop: 12 }}>
      <p style={{ fontSize: 12, fontWeight: 600, color: "var(--pr-text-primary)" }}>{title}</p>
      <ul style={{ fontSize: 12, marginTop: 4, listStyle: "none", padding: 0 }}>
        {diff.added.map((item, i) => (
          <li key={`added-${i}`} style={{ marginBottom: 4 }}>
            <span style={{ color: "var(--pr-trust-green)", fontWeight: 500 }}>Added</span>{" "}
            <span style={{ color: "var(--pr-text-primary)" }}>{ITEM_LABEL(kind, item)}</span>
          </li>
        ))}
        {diff.removed.map((item, i) => (
          <li key={`removed-${i}`} style={{ marginBottom: 4 }}>
            <span style={{ color: "var(--pr-critical-red)", fontWeight: 500 }}>Removed</span>{" "}
            <span style={{ color: "var(--pr-text-primary)" }}>{ITEM_LABEL(kind, item)}</span>
          </li>
        ))}
        {diff.changed.map((item, i) => (
          <ChangedRow key={`changed-${i}`} kind={kind} item={item} />
        ))}
      </ul>
    </div>
  );
}

export function ApprovalDiffView({ corpusId, approvalId }: { corpusId: string; approvalId: string }) {
  const [diff, setDiff] = useState<GraphApprovalDiff | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setDiff(null);
    setError(null);
    aiAuthorityBuilderApi
      .getApprovalDiff(corpusId, approvalId)
      .then((result) => { if (!cancelled) setDiff(result); })
      .catch((e) => { if (!cancelled) setError(describeApiError(e, "Load changes")); });
    return () => {
      cancelled = true;
    };
  }, [corpusId, approvalId]);

  if (error) {
    return <p role="alert" style={{ color: "var(--pr-critical-red)", fontSize: 12, marginTop: 8 }}>{error}</p>;
  }
  if (!diff) {
    return (
      <div style={{ marginTop: 8 }}>
        <SkeletonRows count={2} height={14} />
      </div>
    );
  }

  const totalChanges =
    diff.summary.principals_added + diff.summary.principals_removed + diff.summary.principals_changed +
    diff.summary.relationships_added + diff.summary.relationships_removed + diff.summary.relationships_changed +
    diff.summary.conflicts_added + diff.summary.conflicts_removed + diff.summary.conflicts_changed +
    diff.summary.gaps_added + diff.summary.gaps_removed + diff.summary.gaps_changed +
    (diff.summary.coverage_changed ? 1 : 0);

  return (
    <div
      style={{
        marginTop: 8,
        padding: "10px 12px",
        borderRadius: 8,
        backgroundColor: "var(--pr-bg-hover)",
      }}
    >
      <p style={{ fontSize: 12, fontWeight: 600, color: "var(--pr-text-primary)" }}>
        Changes from v{diff.from_approval.version} to v{diff.to_approval.version}
      </p>
      {totalChanges === 0 ? (
        <p style={{ fontSize: 12, color: "var(--pr-text-muted)", marginTop: 4 }}>
          No changes -- this graph version is identical to v{diff.from_approval.version}.
        </p>
      ) : (
        <>
          <ItemDiffSection title="Principals" kind="principals" diff={diff.principals} />
          <ItemDiffSection title="Relationships" kind="relationships" diff={diff.relationships} />
          <ItemDiffSection title="Conflicts" kind="conflicts" diff={diff.conflicts} />
          <ItemDiffSection title="Gaps" kind="gaps" diff={diff.gaps} />
          {diff.summary.coverage_changed && (
            <div style={{ marginTop: 12 }}>
              <p style={{ fontSize: 12, fontWeight: 600, color: "var(--pr-text-primary)" }}>Coverage</p>
              <ul style={{ fontSize: 12, marginTop: 4, marginLeft: 16, color: "var(--pr-text-muted)" }}>
                {diff.coverage.changed_fields.map((f) => (
                  <li key={f.field}>
                    {f.field}: {String(f.before ?? "—")} {"→"} {String(f.after ?? "—")}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}
