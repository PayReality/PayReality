import { formatStatus } from "../../live/format";
import type { EffectiveStatus } from "../types";

const STATUS_COLOR: Record<EffectiveStatus, string> = {
  draft: "var(--pr-text-disabled)",
  pending_review: "var(--pr-warning-amber)",
  approved: "var(--pr-authority-blue)",
  rejected: "var(--pr-critical-red)",
  compiled: "var(--pr-verification-purple, var(--pr-authority-blue))",
  active: "var(--pr-trust-green)",
  retired: "var(--pr-text-disabled)",
  // Runtime Policy Lifecycle (Phase 5): "archived" is the one new stored
  // status; "superseded" is a read-side label for a retired row with a
  // newer active sibling, given its own shade so it reads as distinct
  // from a plain "retired" (nothing replaced it) at a glance.
  archived: "var(--pr-text-disabled)",
  superseded: "var(--pr-warning-amber)",
};

// Plain text with a left border in the status color, not a colored
// pill or icon: "enterprise, minimal, GitHub-level clarity, no
// gimmicks" (POLICY_STUDIO_WIREFRAMES.md's UI principles).
export function PolicyStatusBadge({ status }: { status: EffectiveStatus }) {
  return (
    <span
      style={{
        borderLeft: `2px solid ${STATUS_COLOR[status]}`,
        paddingLeft: 8,
        color: "var(--pr-text-primary)",
        fontSize: 13,
        fontFamily: "monospace",
      }}
    >
      {formatStatus(status)}
    </span>
  );
}
