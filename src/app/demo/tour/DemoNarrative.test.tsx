import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TOUR_STEPS } from "./steps";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../config", () => ({ DEMO_MODE: true }));
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

// Demo V2 (Trusted Authority Story): guards the guided tour's own copy
// directly, independent of rendering -- the cheapest, most direct check
// that a prohibited execution claim never regresses back into the tour.
describe("TOUR_STEPS copy", () => {
  it("never claims PayReality observed or proved the external system executed", () => {
    const allText = TOUR_STEPS.map((s) => `${s.title} ${s.body}`).join(" ");
    expect(allText).not.toMatch(/the erp executes/i);
    expect(allText).not.toMatch(/proceeds into the enterprise system of record/i);
    expect(allText).not.toMatch(/proves it happened correctly/i);
    expect(allText).not.toMatch(/non-bypassable/i);
    expect(allText).not.toMatch(/cannot execute without/i);
  });

  it("walks through the Agent / Trusted Adapter / PayReality distinction", () => {
    const allText = TOUR_STEPS.map((s) => `${s.title} ${s.body}`).join(" ");
    expect(allText).toMatch(/trusted adapter/i);
    expect(allText).toMatch(/action mapping/i);
    expect(allText.toLowerCase()).toContain("who's acting");
  });

  it("includes the retry/idempotency beat and the Allow counterexample", () => {
    const allText = TOUR_STEPS.map((s) => `${s.title} ${s.body}`).join(" ");
    expect(allText).toMatch(/never a second one/i);
    expect(allText).toMatch(/no trusted adapter/i);
  });
});

function renderAt(path: string, Component: () => JSX.Element, routePath: string) {
  return act(async () => {
    root.render(
      createElement(
        MemoryRouter,
        { initialEntries: [path] },
        createElement(Routes, null, createElement(Route, { path: routePath, element: createElement(Component) }))
      )
    );
    await new Promise((r) => setTimeout(r, 150));
  });
}

describe("DemoLanding narrative", () => {
  it("leads with the three-question model and the bank-details scenario, not the nine-agent world", async () => {
    const { DemoLanding } = await import("../DemoLanding");
    const { TourProvider } = await import("./TourProvider");
    await act(async () => {
      root.render(
        createElement(
          MemoryRouter,
          { initialEntries: ["/"] },
          createElement(TourProvider, null, createElement(DemoLanding))
        )
      );
      await new Promise((r) => setTimeout(r, 150));
    });

    expect(container.textContent).toContain("supplier's bank details");
    expect(container.textContent).toContain("The three questions PayReality answers");
    expect(container.textContent).not.toMatch(/proves it happened correctly/i);
  });
});

describe("DecisionDetailPage: the Adapter-mediated narrative decision", () => {
  it("shows integration provenance and a Human Review outcome", async () => {
    const { DECISION_HERO_ADAPTER_REVIEW } = await import("../fixtures/decisions");
    const { DecisionDetailPage } = await import("../../live/pages/DecisionDetailPage");
    await renderAt(`/decisions/${DECISION_HERO_ADAPTER_REVIEW}`, DecisionDetailPage, "/decisions/:decisionId");

    expect(container.textContent).toMatch(/human review/i);
    expect(container.textContent).toContain("Reported through a trusted connection");
    expect(container.textContent).toContain("ChangeSupplierBankDetails");
    expect(container.textContent).not.toMatch(/action (actually )?executed/i);
  });

  it("replaying the same operation returns the existing Decision, never a new one", async () => {
    const { DECISION_HERO_ADAPTER_REVIEW } = await import("../fixtures/decisions");
    const { DecisionDetailPage } = await import("../../live/pages/DecisionDetailPage");
    const { getLiveDecisions } = await import("../liveFeed");

    await renderAt(`/decisions/${DECISION_HERO_ADAPTER_REVIEW}`, DecisionDetailPage, "/decisions/:decisionId");

    const countBefore = getLiveDecisions().length;

    const replayButton = Array.from(container.querySelectorAll("button")).find((b) =>
      /simulate sap retrying this report/i.test(b.textContent ?? "")
    );
    expect(replayButton).toBeTruthy();

    await act(async () => {
      replayButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(getLiveDecisions().length).toBe(countBefore);
    expect(container.textContent).toContain(DECISION_HERO_ADAPTER_REVIEW);
    expect(container.textContent).toMatch(/no new decision was created/i);
  });
});

describe("DecisionDetailPage: the Allow counterexample", () => {
  it("shows an Allow outcome with no integration provenance (agent-direct)", async () => {
    const { DECISION_HERO_ALLOW } = await import("../fixtures/decisions");
    const { DecisionDetailPage } = await import("../../live/pages/DecisionDetailPage");
    await renderAt(`/decisions/${DECISION_HERO_ALLOW}`, DecisionDetailPage, "/decisions/:decisionId");

    expect(container.textContent).toContain("Allow");
    expect(container.textContent).not.toContain("Reported through a trusted connection");
  });
});
