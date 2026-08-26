import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../../demo/config", () => ({ DEMO_MODE: true }));
vi.mock("../../auth/AuthContext", () => ({
  useAuth: () => ({ user: { id: "u1", name: "Test User", email: "t@example.com" }, hasPermission: () => true }),
}));
vi.mock("../../help/HelpContext", () => ({
  useHelp: () => ({ openLearnArticle: () => {} }),
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

// Core Product Experience Redesign, section 22: focused coverage for
// the Decision Center's history rendering and its demoted manual-test
// entry point -- the two behaviors section 4 most depends on.
describe("DecisionHistoryPage (demo mode)", () => {
  it("renders operational history as the landing state, not a submission form", async () => {
    const { DecisionHistoryPage } = await import("./DecisionHistoryPage");
    await act(async () => {
      root.render(
        createElement(MemoryRouter, { initialEntries: ["/decisions"] }, createElement(DecisionHistoryPage))
      );
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(container.textContent).toContain("Decisions");
    // The old page's always-visible submission form must not be the
    // landing content any more.
    expect(container.textContent).not.toContain("Submit signed intent");
    // A real history row from the demo fixtures should be visible.
    expect(container.querySelector("table")).not.toBeNull();
  });

  it("demotes manual testing to a secondary drawer, opened explicitly, with no ref console error", async () => {
    // Visual Experience V2 (found via real browser QA): opening this
    // exact drawer used to log a real React console error --
    // "Function components cannot be given refs" -- because sheet.tsx's
    // SheetOverlay/SheetContent were plain function components on a
    // project that targets React 18 (no automatic ref-as-prop), while
    // Radix Dialog's Presence/Slot machinery attaches a ref to whatever
    // they render. Fixed with React.forwardRef; this asserts the
    // specific warning never fires again, not just that nothing throws.
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { DecisionHistoryPage } = await import("./DecisionHistoryPage");
    await act(async () => {
      root.render(
        createElement(MemoryRouter, { initialEntries: ["/decisions"] }, createElement(DecisionHistoryPage))
      );
      await new Promise((r) => setTimeout(r, 50));
    });

    // Not shown until the drawer is opened.
    expect(container.textContent).not.toContain("Submit signed test intent");

    const trigger = Array.from(container.querySelectorAll("button")).find((b) =>
      b.textContent?.includes("Test Runtime Authority")
    );
    expect(trigger).toBeTruthy();
    await act(async () => {
      trigger!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(document.body.textContent).toContain("creates a genuine Intent");
    expect(document.body.textContent).toContain("Submit signed test intent");

    const refWarnings = errorSpy.mock.calls.filter((args) =>
      String(args[0]).includes("Function components cannot be given refs")
    );
    expect(refWarnings).toHaveLength(0);
  });
});
