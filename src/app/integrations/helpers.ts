import type { ActionMapping, RuntimeConnection } from "./types";

// Trusted Integration Architecture, Phase 4 (section 4): the honest,
// derived summary facts a System card shows -- computed client-side
// from the existing list endpoints (Phase 1's contract-versions, Phase
// 2's enforcement-bindings), never a fabricated health/assurance score.
// "Not configured" is a real, first-class state here, never silently
// hidden.

export type SetupState = "not_started" | "mapping_in_progress" | "ready_to_connect" | "connected";

export interface SystemSummary {
  mappedActionsCount: number;
  approvedMappingsCount: number;
  environments: string[];
  activeAgentIds: string[];
  setupState: SetupState;
}

export function summarizeSystem(mappings: ActionMapping[], connections: RuntimeConnection[]): SystemSummary {
  const mappedActionsCount = new Set(mappings.map((m) => m.source_operation)).size;
  const approvedMappingsCount = mappings.filter((m) => m.status === "approved").length;
  const activeConnections = connections.filter((c) => c.status === "active");
  const environments = Array.from(new Set(activeConnections.map((c) => c.environment)));
  const activeAgentIds = Array.from(new Set(activeConnections.flatMap((c) => c.allowed_agent_ids)));

  let setupState: SetupState;
  if (mappings.length === 0) {
    setupState = "not_started";
  } else if (activeConnections.length > 0) {
    setupState = "connected";
  } else if (approvedMappingsCount > 0) {
    setupState = "ready_to_connect";
  } else {
    setupState = "mapping_in_progress";
  }

  return { mappedActionsCount, approvedMappingsCount, environments, activeAgentIds, setupState };
}

export const SETUP_STATE_LABEL: Record<SetupState, string> = {
  not_started: "Not started",
  mapping_in_progress: "Mapping in progress",
  ready_to_connect: "Ready to connect",
  connected: "Connected",
};

export const SETUP_STATE_COLOR: Record<SetupState, string> = {
  not_started: "var(--pr-text-disabled)",
  mapping_in_progress: "var(--pr-warning-amber)",
  ready_to_connect: "var(--pr-authority-blue)",
  connected: "var(--pr-trust-green)",
};

// Section 8: "This tells PayReality what an action in this system
// means." -- the one-line human summary shown wherever a mapping is
// listed, never leading with source_operation/canonical_action as raw
// backend strings without this framing sentence somewhere nearby.
export function describeMapping(mapping: ActionMapping): string {
  return `"${mapping.source_operation}" means "${humanizeAction(mapping.canonical_action)}" to PayReality`;
}

export function humanizeAction(action: string): string {
  return action.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
