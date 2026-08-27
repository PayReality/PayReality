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
vi.mock("../help/HelpContext", () => ({
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

describe("AIAuthorityBuilderCorpusReviewPage (demo mode)", () => {
  it("mounts without throwing for the real demo corpus id", async () => {
    const { AIAuthorityBuilderCorpusReviewPage } = await import("./CorpusReviewPage");
    let caught: unknown = null;
    await act(async () => {
      try {
        root.render(
          createElement(
            MemoryRouter,
            { initialEntries: ["/governance/authority-builder/corpus-meridian-governance-docs"] },
            createElement(
              Routes,
              null,
              createElement(Route, {
                path: "/governance/authority-builder/:corpusId",
                element: createElement(AIAuthorityBuilderCorpusReviewPage),
              })
            )
          )
        );
        await new Promise((r) => setTimeout(r, 50));
      } catch (e) {
        caught = e;
      }
    });
    expect(caught).toBeNull();
  });

  it("shows lineage labels and a working View changes disclosure on Approval History (issue #5)", async () => {
    const { AIAuthorityBuilderCorpusReviewPage } = await import("./CorpusReviewPage");
    await act(async () => {
      root.render(
        createElement(
          MemoryRouter,
          { initialEntries: ["/governance/authority-builder/corpus-meridian-governance-docs"] },
          createElement(
            Routes,
            null,
            createElement(Route, {
              path: "/governance/authority-builder/:corpusId",
              element: createElement(AIAuthorityBuilderCorpusReviewPage),
            })
          )
        )
      );
      await new Promise((r) => setTimeout(r, 50));
    });

    const historyTabButton = Array.from(container.querySelectorAll("button")).find((b) =>
      (b.textContent ?? "").includes("Approval History")
    );
    expect(historyTabButton).toBeTruthy();
    await act(async () => {
      historyTabButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(container.textContent).toContain("Current");
    expect(container.textContent).toContain("Previous version: v1");
    expect(container.textContent).toContain("First approved version");
    expect(container.textContent).toContain("No RuntimePolicies compiled from this version yet.");

    const viewChangesButton = Array.from(container.querySelectorAll("button")).find((b) =>
      (b.textContent ?? "").includes("View changes")
    );
    expect(viewChangesButton).toBeTruthy();
    await act(async () => {
      viewChangesButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(container.textContent).toContain("Changes from v1 to v2");
    expect(container.textContent).toContain("Added Marcus Webb");
    expect(container.textContent).toContain("Added Elena Ruiz");
  });
});
