import { beforeEach, describe, expect, it, vi } from "vitest";
import { demoAgents } from "./fixtures/agents";
import { getAgentPrivateKey } from "../live/agentKeyStore";

// The bug this fixes: a fresh demo visitor's browser has no locally
// stored private key for any of the demo's pre-existing fixture agents
// (only the real register/rotate-keys flow ever calls
// saveAgentKeyPair), so ManualDecisionSheet.tsx's signableAgents filter
// had nothing to show -- every agent in the Test Runtime Authority
// drawer's picker was permanently unselectable. ensureDemoAgentKeysSeeded
// must leave a real key behind for every demo agent, exactly once.

beforeEach(() => {
  localStorage.clear();
  vi.resetModules();
});

async function seed() {
  const mod = await import("./seedAgentKeys");
  mod.ensureDemoAgentKeysSeeded();
}

describe("ensureDemoAgentKeysSeeded", () => {
  it("leaves every demo agent with a real, non-empty private key", async () => {
    await seed();
    for (const agent of demoAgents) {
      const key = getAgentPrivateKey(agent.id);
      expect(key).not.toBeNull();
      expect(key?.length).toBeGreaterThan(0);
    }
  });

  it("is idempotent: calling it again does not overwrite an existing key", async () => {
    await seed();
    const before = getAgentPrivateKey(demoAgents[0].id);

    const mod = await import("./seedAgentKeys");
    mod.ensureDemoAgentKeysSeeded();

    expect(getAgentPrivateKey(demoAgents[0].id)).toBe(before);
  });

  it("does not overwrite a key that already exists for some other reason (e.g. the real register flow)", async () => {
    const { saveAgentKeyPair } = await import("../live/agentKeyStore");
    saveAgentKeyPair(demoAgents[0].id, "pre-existing-private-key", "pre-existing-public-key");

    await seed();

    expect(getAgentPrivateKey(demoAgents[0].id)).toBe("pre-existing-private-key");
  });
});
