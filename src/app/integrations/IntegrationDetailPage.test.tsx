import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../demo/config", () => ({ DEMO_MODE: true }));

let container: HTMLDivElement;
let root: Root;
let currentHasPermission = () => true;

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: { id: "u1", name: "Test User", email: "t@example.com" }, hasPermission: (p: string) => currentHasPermission(), }),
}));

function setValue(input: HTMLInputElement | HTMLSelectElement, value: string) {
  const proto = input instanceof HTMLSelectElement ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event(input instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
}

beforeEach(() => {
  currentHasPermission = () => true;
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

async function renderDetailPage(systemId: string) {
  const { IntegrationDetailPage } = await import("./IntegrationDetailPage");
  await act(async () => {
    root.render(
      createElement(
        MemoryRouter,
        { initialEntries: [`/organization/integrations/${systemId}`] },
        createElement(Routes, null, createElement(Route, { path: "/organization/integrations/:systemId", element: createElement(IntegrationDetailPage) }))
      )
    );
    await new Promise((r) => setTimeout(r, 150));
  });
}

// Trusted Integration Architecture, Phase 4: Action Mapping create ->
// validate -> approve, multiple approved versions coexisting, and
// permission-gated approve/activate.
describe("IntegrationDetailPage (demo mode)", () => {
  it("shows the seeded approved mapping in plain business language", async () => {
    const { DEMO_SYSTEM_SAP } = await import("../demo/fixtures/integrations");
    await renderDetailPage(DEMO_SYSTEM_SAP);

    expect(container.textContent).toContain("SAP S/4HANA");
    expect(container.textContent).toContain("ChangeSupplierBankDetails");
    // Trusted Integration Architecture, Phase 6.1 (Part C): the seeded
    // mapping's own canonical action, not vendor_payment -- see
    // fixtures/integrations.ts's own comment on why.
    expect(container.textContent).toContain("Supplier Bank Details Change");
    expect(container.textContent).not.toMatch(/IntegrationContractVersion|EnforcementBinding|canonical fingerprint/i);
  });

  it("creates a draft mapping, validates it, and approves it -- coexisting with the already-approved version", async () => {
    const { DEMO_SYSTEM_SAP } = await import("../demo/fixtures/integrations");
    await renderDetailPage(DEMO_SYSTEM_SAP);

    const newMappingButton = Array.from(container.querySelectorAll("button")).find((b) => /New mapping/.test(b.textContent ?? ""));
    await act(async () => {
      newMappingButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 30));
    });

    const sourceInput = Array.from(document.body.querySelectorAll("input")).find((i) => /ChangeSupplierBankDetails/.test(i.getAttribute("placeholder") ?? ""));
    expect(sourceInput).toBeTruthy();
    setValue(sourceInput as HTMLInputElement, "UpdatePaymentTerms");

    const actionSelect = Array.from(document.body.querySelectorAll("select")).find((s) => s.querySelector("option[value='vendor_payment']"));
    expect(actionSelect).toBeTruthy();
    setValue(actionSelect as HTMLSelectElement, "vendor_payment");

    const createButton = Array.from(document.body.querySelectorAll("button")).find((b) => b.textContent === "Create draft mapping");
    await act(async () => {
      createButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 150));
    });

    expect(container.textContent).toContain("UpdatePaymentTerms");
    expect(container.textContent).toContain("Draft");

    const validateButton = Array.from(container.querySelectorAll("button")).find((b) => /Validate mapping/.test(b.textContent ?? ""));
    expect(validateButton).toBeTruthy();
    await act(async () => {
      validateButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 150));
    });
    expect(container.textContent).toContain("Validated");

    const approveButton = Array.from(container.querySelectorAll("button")).find((b) => /Approve mapping/.test(b.textContent ?? ""));
    expect(approveButton).toBeTruthy();
    await act(async () => {
      approveButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 150));
    });

    // Both the original seeded approved mapping AND this new one are
    // now approved -- multiple approved versions genuinely coexist,
    // never collapsed into a single "current version" concept.
    const approvedBadges = Array.from(container.querySelectorAll("*")).filter((el) => el.textContent === "Approved" && el.children.length === 0);
    expect(approvedBadges.length).toBeGreaterThanOrEqual(2);
  });

  it("hides Approve/Retire actions from a user without publish permission", async () => {
    currentHasPermission = () => false;
    const { DEMO_SYSTEM_SAP } = await import("../demo/fixtures/integrations");
    await renderDetailPage(DEMO_SYSTEM_SAP);

    expect(Array.from(container.querySelectorAll("button")).some((b) => /Retire/.test(b.textContent ?? ""))).toBe(false);
    expect(Array.from(container.querySelectorAll("button")).some((b) => /Set up connection/.test(b.textContent ?? ""))).toBe(false);
  });

  it("shows an API failure state with a retry action", async () => {
    vi.resetModules();
    vi.doMock("./api", () => ({
      integrationsApi: {
        getSystem: () => Promise.reject(new Error("boom")),
        listMappings: () => Promise.reject(new Error("boom")),
        listConnections: () => Promise.reject(new Error("boom")),
        listTrustedConnections: () => Promise.reject(new Error("boom")),
      },
    }));
    vi.doMock("../agents/api", () => ({ agentsApi: { list: () => Promise.resolve({ agents: [], total: 0, limit: 0, offset: 0 }) } }));
    const { DEMO_SYSTEM_SAP } = await import("../demo/fixtures/integrations");
    await renderDetailPage(DEMO_SYSTEM_SAP);

    expect(Array.from(container.querySelectorAll("button")).some((b) => b.textContent === "Retry")).toBe(true);
    vi.doUnmock("./api");
    vi.doUnmock("../agents/api");
  });
});
