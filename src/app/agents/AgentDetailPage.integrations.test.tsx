import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../demo/config", () => ({ DEMO_MODE: true }));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: { id: "u1", name: "Test User", email: "t@example.com" }, hasPermission: () => true }),
}));

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => {
    root.unmount();
  });
  container.remove();
  vi.restoreAllMocks();
});

// Trusted Integration Architecture, Phase 4 (section 27): a small,
// read-only "Trusted connections" section on Agent Detail -- named in
// its own separate test file (not touching the pre-existing, currently-
// unrelated AgentDetailPage WIP) so it stays independently reviewable.
describe("AgentDetailPage Trusted connections section (demo mode)", () => {
  it("shows the seeded runtime connection this agent is allowed to use", async () => {
    const { AGENT_AP_INVOICE } = await import("../demo/fixtures/agents");
    const { AgentDetailPage } = await import("./AgentDetailPage");
    await act(async () => {
      const { HelpProvider } = await import("../help/HelpContext");
      root.render(
        createElement(
          HelpProvider,
          null,
          createElement(
            MemoryRouter,
            { initialEntries: [`/agents/${AGENT_AP_INVOICE}`] },
            createElement(Routes, null, createElement(Route, { path: "/agents/:agentId", element: createElement(AgentDetailPage) }))
          )
        )
      );
      await new Promise((r) => setTimeout(r, 150));
    });

    expect(container.textContent).toContain("Trusted connections");
    expect(container.textContent).toContain("SAP S/4HANA");
    expect(container.textContent).toContain("SAP Procurement Adapter");
    expect(container.textContent).toContain("Production");
  });

  it("links to Settings > Integrations, and never manages the connection from Agent Detail", async () => {
    const { AGENT_AP_INVOICE } = await import("../demo/fixtures/agents");
    const { AgentDetailPage } = await import("./AgentDetailPage");
    await act(async () => {
      const { HelpProvider } = await import("../help/HelpContext");
      root.render(
        createElement(
          HelpProvider,
          null,
          createElement(
            MemoryRouter,
            { initialEntries: [`/agents/${AGENT_AP_INVOICE}`] },
            createElement(Routes, null, createElement(Route, { path: "/agents/:agentId", element: createElement(AgentDetailPage) }))
          )
        )
      );
      await new Promise((r) => setTimeout(r, 150));
    });

    const link = container.querySelector('a[href="/organization/integrations"]');
    expect(link).not.toBeNull();
    expect(container.textContent).not.toMatch(/activate connection|retire connection/i);
  });

  it("shows an honest empty state for an agent no connection allows", async () => {
    const { AGENT_PO_APPROVAL } = await import("../demo/fixtures/agents");
    const { AgentDetailPage } = await import("./AgentDetailPage");
    await act(async () => {
      const { HelpProvider } = await import("../help/HelpContext");
      root.render(
        createElement(
          HelpProvider,
          null,
          createElement(
            MemoryRouter,
            { initialEntries: [`/agents/${AGENT_PO_APPROVAL}`] },
            createElement(Routes, null, createElement(Route, { path: "/agents/:agentId", element: createElement(AgentDetailPage) }))
          )
        )
      );
      await new Promise((r) => setTimeout(r, 150));
    });

    expect(container.textContent).toContain("No runtime connection currently allows this agent");
  });
});
