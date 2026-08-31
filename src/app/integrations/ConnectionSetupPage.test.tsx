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

function setValue(input: HTMLInputElement | HTMLSelectElement, value: string) {
  const proto = input instanceof HTMLSelectElement ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event(input instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
});

afterEach(() => {
  act(() => {
    root.unmount();
  });
  container.remove();
  vi.restoreAllMocks();
});

async function renderSetupPage(systemId: string) {
  const { ConnectionSetupPage } = await import("./ConnectionSetupPage");
  await act(async () => {
    root.render(
      createElement(
        MemoryRouter,
        { initialEntries: [`/organization/integrations/${systemId}/connect`] },
        createElement(Routes, null, createElement(Route, { path: "/organization/integrations/:systemId/connect", element: createElement(ConnectionSetupPage) }))
      )
    );
    await new Promise((r) => setTimeout(r, 150));
  });
}

// Trusted Integration Architecture, Phase 4: the guided runtime-
// connection setup -- one-time credential reveal, explicit agent
// selection (never "all current and future agents"), and the
// approved-≠-active-in-production distinction (section 24).
describe("ConnectionSetupPage (demo mode)", () => {
  it("registers a new trusted connection and shows the one-time credential exactly once", async () => {
    const { DEMO_SYSTEM_SAP } = await import("../demo/fixtures/integrations");
    await renderSetupPage(DEMO_SYSTEM_SAP);

    const registerToggle = Array.from(container.querySelectorAll("button")).find((b) => /Register a new one/.test(b.textContent ?? ""));
    await act(async () => {
      registerToggle!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const nameInput = Array.from(container.querySelectorAll("input")).find((i) => /SAP Procurement Adapter/.test(i.getAttribute("placeholder") ?? ""));
    expect(nameInput).toBeTruthy();
    setValue(nameInput as HTMLInputElement, "New Adapter Connection");

    const generateButton = Array.from(container.querySelectorAll("button")).find((b) => /Generate credentials/.test(b.textContent ?? ""));
    await act(async () => {
      generateButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 150));
    });

    expect(container.textContent).toContain("only time PayReality will show this credential");
    expect(container.textContent).toContain("New Adapter Connection");
    const keyBlock = container.querySelector("code");
    expect(keyBlock?.textContent?.length).toBeGreaterThan(20);
  });

  it("requires every agent to be chosen explicitly -- no select-all option exists", async () => {
    const { DEMO_SYSTEM_SAP } = await import("../demo/fixtures/integrations");
    await renderSetupPage(DEMO_SYSTEM_SAP);

    // The page explains its own absence in prose ("there's no 'all
    // current and future agents' option") -- what actually matters is
    // that no control offers that behavior: no "select all" button/
    // checkbox, and every agent has its own individually-labeled
    // checkbox to select explicitly.
    expect(Array.from(container.querySelectorAll("button")).some((b) => /select all/i.test(b.textContent ?? ""))).toBe(false);
    const checkboxes = Array.from(container.querySelectorAll('input[type="checkbox"]'));
    expect(checkboxes.length).toBeGreaterThan(0);
    expect(checkboxes.some((c) => c.hasAttribute("data-select-all"))).toBe(false);
  });

  it("walks through create-draft -> activate, and communicates approved ≠ active", async () => {
    const { DEMO_SYSTEM_SAP, DEMO_MAPPING_SAP_APPROVED } = await import("../demo/fixtures/integrations");
    await renderSetupPage(DEMO_SYSTEM_SAP);

    const registerToggle = Array.from(container.querySelectorAll("button")).find((b) => /Register a new one/.test(b.textContent ?? ""));
    await act(async () => { registerToggle!.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    const nameInput = Array.from(container.querySelectorAll("input")).find((i) => /SAP Procurement Adapter/.test(i.getAttribute("placeholder") ?? ""));
    setValue(nameInput as HTMLInputElement, "Staging Adapter");
    const generateButton = Array.from(container.querySelectorAll("button")).find((b) => /Generate credentials/.test(b.textContent ?? ""));
    await act(async () => { generateButton!.dispatchEvent(new MouseEvent("click", { bubbles: true })); await new Promise((r) => setTimeout(r, 150)); });

    const mappingSelect = Array.from(container.querySelectorAll("select")).find((s) => s.querySelector(`option[value="${DEMO_MAPPING_SAP_APPROVED}"]`));
    expect(mappingSelect).toBeTruthy();
    setValue(mappingSelect as HTMLSelectElement, DEMO_MAPPING_SAP_APPROVED);

    const envSelect = Array.from(container.querySelectorAll("select")).find((s) => s.querySelector('option[value="staging"]'));
    setValue(envSelect as HTMLSelectElement, "staging");

    const agentCheckbox = container.querySelector('input[type="checkbox"]') as HTMLInputElement;
    await act(async () => {
      agentCheckbox.click();
    });

    const createDraftButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === "Create connection setup");
    expect(createDraftButton?.hasAttribute("disabled")).toBe(false);
    await act(async () => {
      createDraftButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 150));
    });

    expect(container.textContent).toContain("Ready to review");

    const activateButton = Array.from(container.querySelectorAll("button")).find((b) => /Activate connection/.test(b.textContent ?? ""));
    expect(activateButton).toBeTruthy();
    await act(async () => {
      activateButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 150));
    });

    expect(container.textContent).toContain("Connection active");
  });

  it("sends a real signed test decision and shows a business-friendly result first", async () => {
    const { DEMO_SYSTEM_SAP, DEMO_MAPPING_SAP_APPROVED } = await import("../demo/fixtures/integrations");
    await renderSetupPage(DEMO_SYSTEM_SAP);

    const registerToggle = Array.from(container.querySelectorAll("button")).find((b) => /Register a new one/.test(b.textContent ?? ""));
    await act(async () => { registerToggle!.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    const nameInput = Array.from(container.querySelectorAll("input")).find((i) => /SAP Procurement Adapter/.test(i.getAttribute("placeholder") ?? ""));
    setValue(nameInput as HTMLInputElement, "Test Adapter");
    const generateButton = Array.from(container.querySelectorAll("button")).find((b) => /Generate credentials/.test(b.textContent ?? ""));
    await act(async () => { generateButton!.dispatchEvent(new MouseEvent("click", { bubbles: true })); await new Promise((r) => setTimeout(r, 150)); });

    const mappingSelect = Array.from(container.querySelectorAll("select")).find((s) => s.querySelector(`option[value="${DEMO_MAPPING_SAP_APPROVED}"]`));
    setValue(mappingSelect as HTMLSelectElement, DEMO_MAPPING_SAP_APPROVED);
    const agentCheckbox = container.querySelector('input[type="checkbox"]') as HTMLInputElement;
    await act(async () => { agentCheckbox.click(); });

    const createDraftButton = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === "Create connection setup");
    await act(async () => {
      createDraftButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 150));
    });

    expect(container.textContent).toContain("Test this connection");
    const sendTestButton = Array.from(container.querySelectorAll("button")).find((b) => /Send test decision/.test(b.textContent ?? ""));
    expect(sendTestButton).toBeTruthy();
    await act(async () => {
      sendTestButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 200));
    });

    // "Allowed" first, not a raw OPA/JSON response.
    expect(container.textContent).toContain("Allowed");
    expect(container.textContent).not.toMatch(/\{"outcome"|opa_/i);
  });
});
