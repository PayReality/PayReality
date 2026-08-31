import type { ComponentType, ReactNode } from "react";

export interface AuthorityChainLink {
  icon: ComponentType<{ className?: string; style?: React.CSSProperties }>;
  label: string;
  value: ReactNode;
  /** Renders the link muted/dashed: an authority boundary that wasn't
   * reached, a fact that never resolved, a step this Decision didn't
   * need. Never hidden outright: an absent step is still real
   * information (section 15: "authority boundary," not just "authority
   * granted"). */
  inactive?: boolean;
}

/**
 * Visual System V3, section 5: "Authority has structure" without
 * turning every page into a flowchart. A single horizontal (wraps to
 * vertical on narrow viewports) sequence of small nodes connected by a
 * hairline, used for exactly the sequence this whole visual system is
 * organized around: Agent -> Action -> Authority -> Decision -> Evidence,
 * or a narrower slice of it (Principal -> Agent on Decision Detail's
 * own Authority card; Trusted Connection -> Action Mapping -> Runtime
 * Connection -> Agent on an Integration's Runtime Connection row).
 * Deliberately not a generic diagramming primitive: exactly one row,
 * exactly this shape, reused wherever the app already asserts a chain
 * of custody in prose today.
 */
export function AuthorityChain({ links }: { links: AuthorityChainLink[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-1 gap-y-3" role="list" aria-label="Authority chain">
      {links.map((link, i) => {
        const Icon = link.icon;
        const color = link.inactive ? "var(--pr-text-disabled)" : "var(--pr-chain-dot-active)";
        return (
          <div key={i} className="flex items-center" role="listitem">
            {i > 0 && (
              <span
                aria-hidden="true"
                className="inline-block mx-1.5"
                style={{ width: 20, height: 1, backgroundColor: "var(--pr-chain-line)" }}
              />
            )}
            <div
              className="flex items-center gap-2 rounded-lg px-2.5 py-1.5"
              style={{
                border: `1px solid ${link.inactive ? "var(--pr-overlay-05)" : "var(--pr-overlay-10)"}`,
                backgroundColor: link.inactive ? "transparent" : "var(--pr-overlay-03)",
                opacity: link.inactive ? 0.6 : 1,
              }}
            >
              <Icon className="w-3.5 h-3.5 flex-shrink-0" style={{ color }} />
              <div className="leading-tight">
                <p className="text-[10px] uppercase tracking-wide" style={{ color: "var(--pr-text-disabled)" }}>{link.label}</p>
                <p className="text-xs font-medium" style={{ color: link.inactive ? "var(--pr-text-muted)" : "var(--pr-text-primary)" }}>
                  {link.value}
                </p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
