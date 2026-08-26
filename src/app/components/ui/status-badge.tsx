import type { CSSProperties } from "react";

interface StatusBadgeProps {
  color: string;
  label: string;
}

/**
 * Product Experience Remediation Milestone 1 (Phase 8): the left-border-
 * plus-text treatment AgentStatusBadge and PolicyStatusBadge each
 * independently implemented, byte-for-byte identical, extracted here so
 * a third lifecycle vocabulary (e.g. Evidence status, Capability state)
 * reads consistently with the first two without a third copy of the
 * same six lines. "Plain text with a left border in the status color,
 * not a colored pill or icon" -- PolicyStatusBadge's own comment,
 * carried forward as this primitive's actual contract, not just a
 * historical note: status is never conveyed by color alone here, the
 * label text is always present.
 */
export function StatusBadge({ color, label }: StatusBadgeProps) {
  const style: CSSProperties = {
    borderLeft: `2px solid ${color}`,
    paddingLeft: 8,
    color: "var(--pr-text-primary)",
    fontSize: 13,
    fontFamily: "monospace",
  };
  return <span style={style}>{label}</span>;
}
