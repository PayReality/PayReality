import type { CSSProperties, ComponentType } from "react";

interface StatusBadgeProps {
  color: string;
  label: string;
  /** Visual System V3, section 8: status must never rely on color alone.
   * Optional so every pre-existing call site (color + text already
   * satisfies that rule on its own) keeps compiling unchanged; new
   * call sites for a vocabulary with a natural icon (Allowed/Not
   * allowed/Needs human approval, Active/Suspended/Revoked, and
   * similar) should pass one. */
  icon?: ComponentType<{ className?: string; style?: CSSProperties }>;
}

/**
 * Product Experience Remediation Milestone 1 (Phase 8): the left-border-
 * plus-text treatment AgentStatusBadge and PolicyStatusBadge each
 * independently implemented, byte-for-byte identical, extracted here so
 * a third lifecycle vocabulary (e.g. Evidence status, Capability state)
 * reads consistently with the first two without a third copy of the
 * same six lines. "Plain text with a left border in the status color,
 * not a colored pill or icon," PolicyStatusBadge's own comment,
 * carried forward as this primitive's actual contract, not just a
 * historical note: status is never conveyed by color alone here, the
 * label text is always present.
 *
 * Visual System V3, section 8: the shape (left border, monospace label)
 * stays exactly as designed above; it already satisfies "not color
 * alone" via text. The icon prop is additive, for the vocabularies this
 * milestone's audit found genuinely benefit from a third channel
 * (Decision outcomes, Agent/Trusted Connection lifecycle) on top of
 * color and text, not a requirement retrofitted onto every existing
 * caller.
 */
export function StatusBadge({ color, label, icon: Icon }: StatusBadgeProps) {
  const style: CSSProperties = {
    borderLeft: `2px solid ${color}`,
    paddingLeft: 8,
    color: "var(--pr-text-primary)",
    fontSize: 13,
    fontFamily: "monospace",
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
  };
  return (
    <span style={style}>
      {Icon && <Icon className="w-3.5 h-3.5" style={{ color, flexShrink: 0 }} />}
      {label}
    </span>
  );
}
