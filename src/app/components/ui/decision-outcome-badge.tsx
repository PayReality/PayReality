import { OUTCOME_STYLE } from "../../live/components/decisionDisplay";
import { formatStatus } from "../../live/format";

const HUMAN_LABEL: Record<string, string> = {
  ALLOW: "Allowed",
  DENY: "Not allowed",
  HUMAN_REVIEW: "Needs human approval",
};

/**
 * Visual System V3, section 7/8: the canonical Decision-outcome
 * presentation, reused everywhere a Decision's ALLOW/DENY/HUMAN_REVIEW
 * appears (history rows, Decision Detail's hero, the Receipt, a future
 * DecisionSummary). Built on the existing OUTCOME_STYLE map
 * (decisionDisplay.tsx) rather than a second color/icon table; this
 * milestone's audit found that map already correct, just re-implemented
 * inline, slightly differently, at every call site. Icon + color + the
 * canonical human-facing label (section 8's own wording: "Allowed,"
 * "Not allowed," "Needs human approval," never the raw enum) together,
 * never color alone.
 */
export function DecisionOutcomeBadge({ outcome, size = "md" }: { outcome: string; size?: "sm" | "md" }) {
  const style = OUTCOME_STYLE[outcome];
  if (!style) {
    return <span style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>{formatStatus(outcome)}</span>;
  }
  const Icon = style.icon;
  const iconSize = size === "sm" ? 14 : 16;
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md font-medium"
      style={{
        backgroundColor: style.bg,
        color: style.fg,
        padding: size === "sm" ? "2px 8px" : "4px 10px",
        fontSize: size === "sm" ? 12 : 13,
      }}
    >
      <Icon style={{ width: iconSize, height: iconSize, flexShrink: 0 }} />
      {HUMAN_LABEL[outcome] ?? formatStatus(outcome)}
    </span>
  );
}
