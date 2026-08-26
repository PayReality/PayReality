import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../../demo/config", () => ({ DEMO_MODE: true }));

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

function renderAt(path: string, Component: () => JSX.Element) {
  return act(async () => {
    root.render(
      createElement(
        MemoryRouter,
        { initialEntries: [path] },
        createElement(Routes, null, createElement(Route, { path: "/decisions/:decisionId/receipt", element: createElement(Component) }))
      )
    );
    await new Promise((r) => setTimeout(r, 80));
  });
}

// Issue #4 (Authorization Receipts): the stable, named artifact reachable
// from Decision Detail -- renders the assembled decision/authority/
// facts/evidence/verification view for a real demo decision id.
describe("AuthorizationReceiptPage (demo mode)", () => {
  it("renders the receipt for an ALLOW decision, verified", async () => {
    const { DECISION_HERO_ALLOW } = await import("../../demo/fixtures/decisions");
    const { AuthorizationReceiptPage } = await import("./AuthorizationReceiptPage");
    await renderAt(`/decisions/${DECISION_HERO_ALLOW}/receipt`, AuthorizationReceiptPage);

    expect(container.textContent).toContain("Authorization Receipt");
    expect(container.textContent).toContain("Allow");
    expect(container.textContent).toContain("Signature verified");
    expect(container.textContent).toContain("Governing authority");
    expect(container.textContent).toContain("Trusted enterprise facts");
  });

  it("expands technical verification details on request, showing the underlying evidence identity", async () => {
    const { DECISION_HERO_ALLOW } = await import("../../demo/fixtures/decisions");
    const { AuthorizationReceiptPage } = await import("./AuthorizationReceiptPage");
    await renderAt(`/decisions/${DECISION_HERO_ALLOW}/receipt`, AuthorizationReceiptPage);

    expect(container.textContent).not.toContain("Signing key ID");

    const toggle = Array.from(container.querySelectorAll("button")).find((b) => /Technical verification details/.test(b.textContent ?? ""));
    expect(toggle).toBeTruthy();
    await act(async () => {
      toggle!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 30));
    });

    expect(container.textContent).toContain("Signing key ID");
    expect(container.textContent).toContain("Evidence ID");
  });

  it("never renders a claim that consumption means the downstream action executed", async () => {
    const { DECISION_HERO_ALLOW } = await import("../../demo/fixtures/decisions");
    const { AuthorizationReceiptPage } = await import("./AuthorizationReceiptPage");
    await renderAt(`/decisions/${DECISION_HERO_ALLOW}/receipt`, AuthorizationReceiptPage);

    const text = container.textContent ?? "";
    expect(text).not.toMatch(/action (actually )?executed/i);
    if (text.includes("Capability authorization")) {
      expect(text).toContain("not confirmation that the");
    }
  });
});
