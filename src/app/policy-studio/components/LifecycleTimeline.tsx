import { useEffect, useState } from "react";
import { policyLifecycleApi } from "../lifecycleApi";
import { formatStatus } from "../../live/format";
import { Alert } from "../../components/ui/alert";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import type { LifecycleEvent } from "../types";

const EVENT_COLOR: Record<string, string> = {
  activated: "var(--pr-trust-green)",
  rejected: "var(--pr-critical-red)",
  activation_blocked: "var(--pr-critical-red)",
  archived: "var(--pr-text-disabled)",
  deprecated: "var(--pr-warning-amber)",
  rolled_back: "var(--pr-warning-amber)",
  retired: "var(--pr-text-disabled)",
};

function eventLabel(event: LifecycleEvent): string {
  if (event.event_type === "rolled_back" && typeof event.payload.target_version === "number") {
    return `Rolled back to v${event.payload.target_version}`;
  }
  return formatStatus(event.event_type);
}

// Runtime Policy Lifecycle (Phase 5): replaces PolicyWorkspacePage's
// former raw audit-dict dump with the real, immutable, hashed lifecycle
// record -- the same table this policy's Enterprise Audit and Policy
// Timeline requirements are both served from (one mechanism, two views).
export function LifecycleTimeline({ policyKey }: { policyKey: string }) {
  const [events, setEvents] = useState<LifecycleEvent[] | null>(null);
  const [error, setError] = useState(false);

  function load() {
    setError(false);
    policyLifecycleApi.timeline(policyKey).then((t) => setEvents(t.events)).catch(() => setError(true));
  }

  useEffect(load, [policyKey]);

  if (error) {
    return (
      <Alert severity="warning">
        <div className="flex items-center gap-3">
          <span>Could not load the timeline.</span>
          <Button variant="ghost" size="sm" onClick={load}>Retry</Button>
        </div>
      </Alert>
    );
  }

  if (!events) return <Skeleton height={60} />;

  if (events.length === 0) {
    return <p style={{ fontSize: 13, color: "var(--pr-text-muted)" }}>No lifecycle activity recorded yet.</p>;
  }

  return (
    <div className="space-y-2">
      {[...events].reverse().map((event) => (
        <div key={event.id} className="py-1.5" style={{ borderTop: "1px solid var(--pr-overlay-05)", fontSize: 13 }}>
          <div className="flex items-start gap-3">
            <span
              style={{
                borderLeft: `2px solid ${EVENT_COLOR[event.event_type] ?? "var(--pr-authority-blue)"}`,
                paddingLeft: 8,
                color: "var(--pr-text-primary)",
                fontFamily: "monospace",
                minWidth: 160,
              }}
            >
              {eventLabel(event)}
            </span>
            <span style={{ color: "var(--pr-text-muted)" }}>v{event.version}</span>
            {event.actor && <span style={{ color: "var(--pr-text-secondary)" }}>by {event.actor}</span>}
            <span style={{ color: "var(--pr-text-disabled)", marginLeft: "auto" }}>
              {new Date(event.occurred_at).toLocaleString()}
            </span>
          </div>
          {event.reason && (
            <p style={{ fontSize: 12, color: "var(--pr-text-muted)", marginTop: 2, marginLeft: 12 }}>{event.reason}</p>
          )}
        </div>
      ))}
    </div>
  );
}

export function SafetyViolationsList({ violations }: { violations: { check: string; message: string }[] }) {
  if (violations.length === 0) {
    return <p style={{ fontSize: 13, color: "var(--pr-trust-green)" }}>No safety issues detected.</p>;
  }
  return (
    <div className="space-y-1.5">
      {violations.map((v, i) => (
        <div key={i} style={{ fontSize: 13, borderLeft: "2px solid var(--pr-critical-red)", paddingLeft: 8 }}>
          <span style={{ color: "var(--pr-critical-red)", fontFamily: "monospace", fontSize: 11, textTransform: "uppercase" }}>
            {formatStatus(v.check)}
          </span>
          <p style={{ color: "var(--pr-text-primary)" }}>{v.message}</p>
        </div>
      ))}
    </div>
  );
}
