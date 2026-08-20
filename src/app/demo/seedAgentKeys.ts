import { demoAgents } from "./fixtures/agents";
import { generateKeyPair } from "../live/crypto";
import { getAgentPrivateKey, saveAgentKeyPair } from "../live/agentKeyStore";

// Outside DEMO_MODE, an agent only gets a browser-local private key
// through the real register/rotate-keys flow (AgentDirectoryPage.tsx,
// AgentDetailPage.tsx) -- correct there, since a real Agent generates
// its own keypair. The public demo's agents already exist as fixtures
// with a decision/evidence history, so a fresh visitor's browser never
// goes through that flow for them, and LiveTestIntent.tsx's own
// signableAgents filter (agents.ts:local, requires a stored private key)
// then had nothing to show: every demo agent was permanently
// unselectable on the Runtime Decision Center page. The mock
// POST /v1/intents handler (mockRouter.ts) returns a fixed canned result
// regardless of which key actually signs the request, so which real
// bytes end up in localStorage here doesn't matter -- only that
// something valid exists, so the UI's own gate passes the same way it
// would for a real, freshly-registered agent.
let seeded = false;

export function ensureDemoAgentKeysSeeded(): void {
  if (seeded) return;
  seeded = true;
  for (const agent of demoAgents) {
    if (getAgentPrivateKey(agent.id)) continue;
    const { privateKeyB64, publicKeyB64 } = generateKeyPair();
    saveAgentKeyPair(agent.id, privateKeyB64, publicKeyB64);
  }
}
