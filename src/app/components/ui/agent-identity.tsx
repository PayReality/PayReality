const STATUS_DOT: Record<string, string> = {
  active: "var(--pr-trust-green)",
  registered: "var(--pr-text-disabled)",
  suspended: "var(--pr-warning-amber)",
  revoked: "var(--pr-critical-red)",
  retired: "var(--pr-text-disabled)",
};

function initials(name: string): string {
  const parts = name.replace(/[^a-zA-Z0-9\s-]/g, " ").trim().split(/[\s-]+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

/**
 * Visual System V3, section 14: the recognizable Agent mark, reused
 * across the Agent inventory, Agent Detail, Decision rows, Trusted
 * Connections, and (unchanged in mechanism, restyled to match) the
 * demo/website. Deliberately NOT a humanoid robot illustration and NOT
 * anthropomorphized: a square (never circular, so it never reads as a
 * human-user avatar), fixed authority-blue tint regardless of which
 * agent: an Agent's identity is its name and its governed status, not
 * a decorative color assigned per row, with initials derived from its
 * own name, the same convention this codebase already uses for
 * initials-based identity elsewhere (see AGENT_DIRECTORY.md's own
 * precedent). A small status dot at the corner is the one variable
 * element, carrying the lifecycle state (section 8: color plus the
 * name/label text next to it, never color alone).
 */
export function AgentIdentity({ name, status, size = "md" }: { name: string; status?: string; size?: "sm" | "md" | "lg" }) {
  const px = size === "sm" ? 24 : size === "lg" ? 40 : 32;
  const fontSize = size === "sm" ? 10 : size === "lg" ? 15 : 12;
  const dotColor = status ? STATUS_DOT[status] ?? "var(--pr-text-disabled)" : undefined;
  return (
    <span className="relative inline-flex flex-shrink-0" style={{ width: px, height: px }}>
      <span
        className="w-full h-full rounded-lg flex items-center justify-center font-semibold"
        style={{
          backgroundColor: "color-mix(in srgb, var(--pr-authority-blue) 16%, transparent)",
          color: "var(--pr-authority-blue)",
          fontSize,
        }}
        aria-hidden="true"
      >
        {initials(name)}
      </span>
      {dotColor && (
        <span
          className="absolute rounded-full"
          aria-hidden="true"
          style={{
            width: px * 0.3125,
            height: px * 0.3125,
            bottom: -1,
            right: -1,
            backgroundColor: dotColor,
            border: "1.5px solid var(--pr-bg-card)",
          }}
        />
      )}
    </span>
  );
}
