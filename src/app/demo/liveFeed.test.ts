import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LiveAgent, LivePrincipal } from "../live/types";

// Frontend baseline closure: mockRouter.ts imports getRegisteredAgents/
// findRegisteredAgent/addRegisteredAgent/updateRegisteredAgent/
// getRegisteredPrincipals/findRegisteredPrincipal/addRegisteredPrincipal
// from this module for real (non-stale) mock-agent-registration routing
// -- a prior commit added mockRouter.ts's own use of these without ever
// committing their implementation here, breaking a clean checkout's
// build. This test exercises the actual contract mockRouter.ts depends
// on, so a regression here is caught by `npm test`, not only by
// `npm run build` failing on a missing export.

function makeAgent(overrides: Partial<LiveAgent> = {}): LiveAgent {
  return {
    id: "agent-test-1",
    certificate_id: null,
    certificate_status: null,
    name: "Test Agent",
    acting_for_principal_id: "principal-test-1",
    status: "registered",
    owner: null,
    business_unit: null,
    environment: null,
    tags: [],
    description: null,
    purpose: null,
    model: null,
    version: null,
    runtime: null,
    platform: null,
    labels: [],
    sdk_version: null,
    last_seen_at: null,
    health: "unknown",
    rotation_requested_at: null,
    created_at: new Date().toISOString(),
    updated_at: null,
    ...overrides,
  };
}

function makePrincipal(overrides: Partial<LivePrincipal> = {}): LivePrincipal {
  return {
    id: "principal-test-1",
    name: "Test Principal",
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("liveFeed registered-agent overlay", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("starts empty", async () => {
    const { getRegisteredAgents, getRegisteredPrincipals } = await import("./liveFeed");
    expect(getRegisteredAgents()).toEqual([]);
    expect(getRegisteredPrincipals()).toEqual([]);
  });

  it("addRegisteredAgent makes the agent findable by id", async () => {
    const { addRegisteredAgent, findRegisteredAgent } = await import("./liveFeed");
    const agent = makeAgent({ id: "agent-add-1" });
    addRegisteredAgent(agent);
    expect(findRegisteredAgent("agent-add-1")).toEqual(agent);
  });

  it("findRegisteredAgent returns undefined for an unknown id", async () => {
    const { findRegisteredAgent } = await import("./liveFeed");
    expect(findRegisteredAgent("no-such-agent")).toBeUndefined();
  });

  it("updateRegisteredAgent patches an existing agent and bumps updated_at", async () => {
    const { addRegisteredAgent, updateRegisteredAgent, findRegisteredAgent } = await import("./liveFeed");
    const agent = makeAgent({ id: "agent-update-1", status: "registered" });
    addRegisteredAgent(agent);

    const updated = updateRegisteredAgent("agent-update-1", { status: "active" });

    expect(updated?.status).toBe("active");
    expect(updated?.updated_at).not.toBeNull();
    expect(findRegisteredAgent("agent-update-1")?.status).toBe("active");
  });

  it("updateRegisteredAgent returns undefined for an unknown id and adds nothing", async () => {
    const { updateRegisteredAgent, getRegisteredAgents } = await import("./liveFeed");
    const before = getRegisteredAgents().length;
    const result = updateRegisteredAgent("no-such-agent", { status: "active" });
    expect(result).toBeUndefined();
    expect(getRegisteredAgents().length).toBe(before);
  });

  it("addRegisteredPrincipal makes the principal findable by id", async () => {
    const { addRegisteredPrincipal, findRegisteredPrincipal } = await import("./liveFeed");
    const principal = makePrincipal({ id: "principal-add-1" });
    addRegisteredPrincipal(principal);
    expect(findRegisteredPrincipal("principal-add-1")).toEqual(principal);
  });
});
