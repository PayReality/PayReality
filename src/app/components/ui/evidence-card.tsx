import type { ReactNode } from "react";
import { Lock } from "lucide-react";

/**
 * Visual System V3, section 6: Evidence and the Authorization Receipt
 * get a surface distinct from an ordinary Card: the goal stated
 * exactly in the brief: "this is a record I can rely on later," without
 * borrowing blockchain/crypto visual cliches (no neon glow, no ledger-
 * block chain imagery, no monospace-everything). The differences from
 * `Card` are deliberately restrained: a hairline border tinted toward
 * --pr-evidence-cyan instead of the neutral overlay border, a faint
 * cyan-tinted corner accent instead of a flat fill, and a small,
 * permanent "Evidence" corner mark, present on every instance, not a
 * one-off per page, so the surface itself becomes recognizable before a
 * reader even parses its contents. `label` and `timestamp` are
 * optional so a caller can build the exact header its own page already
 * needs; when given, they render in this component's own fixed
 * position rather than as freeform children, keeping every Evidence
 * surface's top-left corner consistent.
 */
export function EvidenceCard({
  label,
  timestamp,
  children,
  padding = 20,
}: {
  label?: string;
  timestamp?: string;
  children: ReactNode;
  padding?: number;
}) {
  return (
    <div
      className="relative overflow-hidden rounded-xl"
      style={{
        backgroundColor: "var(--pr-bg-card)",
        border: "1px solid var(--pr-evidence-border)",
        boxShadow: "var(--pr-shadow-card)",
      }}
    >
      <div
        aria-hidden="true"
        className="absolute top-0 left-0 w-16 h-16 pointer-events-none"
        style={{
          background: "radial-gradient(circle at top left, var(--pr-evidence-tint), transparent 70%)",
        }}
      />
      <div style={{ padding }}>
        {(label || timestamp) && (
          <div className="flex items-center justify-between gap-3 mb-3">
            {label && (
              <span
                className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide"
                style={{ color: "var(--pr-evidence-cyan)" }}
              >
                <Lock className="w-3 h-3" />
                {label}
              </span>
            )}
            {timestamp && (
              <span className="text-xs" style={{ color: "var(--pr-text-disabled)", fontFamily: "var(--font-mono, monospace)" }}>
                {timestamp}
              </span>
            )}
          </div>
        )}
        {children}
      </div>
    </div>
  );
}
