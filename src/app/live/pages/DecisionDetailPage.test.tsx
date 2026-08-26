import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../../demo/config", () => ({ DEMO_MODE: true }));
vi.mock("../../auth/AuthContext", () => ({
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

// Core Product Experience Redesign, section 4C: the causal-narrative
// Decision Detail page renders the decision's outcome plus its
// supporting sections for a real demo decision id.
describe("DecisionDetailPage (demo mode)", () => {
  it("renders the outcome and causal sections for a real decision", async () => {
    const { DECISION_HERO_ALLOW } = await import("../../demo/fixtures/decisions");
    const { DecisionDetailPage } = await import("./DecisionDetailPage");
    await act(async () => {
      root.render(
        createElement(
          MemoryRouter,
          { initialEntries: [`/decisions/${DECISION_HERO_ALLOW}`] },
          createElement(
            Routes,
            null,
            createElement(Route, { path: "/decisions/:decisionId", element: createElement(DecisionDetailPage) })
          )
        )
      );
      await new Promise((r) => setTimeout(r, 80));
    });

    expect(container.textContent).toContain("Allow");
    expect(container.textContent).toContain("Authority");
    expect(container.textContent).toContain("Policy");
    expect(container.textContent).toContain("Capability authorization");
    expect(container.textContent).toContain("Evidence");
  });
});
