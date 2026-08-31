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

async function renderAt(path: string) {
  const { IntegrationsListPage } = await import("./IntegrationsListPage");
  await act(async () => {
    root.render(
      createElement(
        MemoryRouter,
        { initialEntries: [path] },
        createElement(Routes, null, createElement(Route, { path: "/organization/integrations", element: createElement(IntegrationsListPage) }))
      )
    );
    await new Promise((r) => setTimeout(r, 80));
  });
}

// Trusted Integration Architecture, Phase 4: the primary Settings ->
// Integrations experience -- proves the seeded example system renders
// with honest, derived summary facts (not a fabricated score), and
// that connecting a new system is a real, guided, minimal-first-step
// flow (section 6: just a name).
describe("IntegrationsListPage (demo mode)", () => {
  it("shows the seeded system with real, derived summary facts", async () => {
    await renderAt("/organization/integrations");

    expect(container.textContent).toContain("SAP S/4HANA");
    expect(container.textContent).toContain("Connected");
    expect(container.textContent).toContain("Mapped actions");
    expect(container.textContent).toContain("Approved mappings");
  });

  it("never invents a fake health/assurance score", async () => {
    await renderAt("/organization/integrations");
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/assurance score|health score|\d+% (healthy|protected)/i);
  });

  it("connecting a system only asks for a name, not API docs or certificates", async () => {
    await renderAt("/organization/integrations");

    const connectButton = Array.from(container.querySelectorAll("button")).find((b) => /Connect a system/.test(b.textContent ?? ""));
    expect(connectButton).toBeTruthy();
    await act(async () => {
      connectButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 30));
    });

    // Radix's Sheet portals to document.body, not this test's local
    // container -- the same reason no existing test in this codebase
    // queries Sheet content from the local container.
    const nameInput = Array.from(document.body.querySelectorAll("input")).find((i) => /SAP S\/4HANA/i.test(i.getAttribute("placeholder") ?? ""));
    expect(nameInput).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/certificate|private key|api key/i);

    await act(async () => {
      // React patches HTMLInputElement's own "value" setter to track
      // the last-set value for its synthetic change detection --
      // assigning `.value =` directly goes through that patched
      // setter, which then sees "no change" and never fires onChange.
      // Using the native prototype setter directly is the standard
      // workaround (no @testing-library/react in this project to do
      // it for us).
      const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")!.set!;
      setValue.call(nameInput, "Salesforce");
      (nameInput as HTMLInputElement).dispatchEvent(new Event("input", { bubbles: true }));
    });

    const submit = Array.from(document.body.querySelectorAll("button")).find((b) => b.textContent === "Connect system");
    expect(submit).toBeTruthy();
    await act(async () => {
      submit!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 300));
    });

    expect(container.textContent).toContain("Salesforce");
  });
});

describe("IntegrationsListPage empty state (isolated store)", () => {
  it("shows a plain-language empty state with a single primary action", async () => {
    vi.resetModules();
    vi.doMock("./api", () => ({
      integrationsApi: {
        listSystems: () => Promise.resolve([]),
        listConnections: () => Promise.resolve([]),
        listMappings: () => Promise.resolve([]),
      },
    }));
    const { IntegrationsListPage } = await import("./IntegrationsListPage");
    await act(async () => {
      root.render(
        createElement(
          MemoryRouter,
          { initialEntries: ["/organization/integrations"] },
          createElement(Routes, null, createElement(Route, { path: "/organization/integrations", element: createElement(IntegrationsListPage) }))
        )
      );
      await new Promise((r) => setTimeout(r, 80));
    });

    expect(container.textContent).toContain("No systems connected yet");
    expect(container.textContent).toContain("guided setup");
    expect(container.textContent).not.toMatch(/api documentation|architecture diagram/i);
    vi.doUnmock("./api");
  });
});
