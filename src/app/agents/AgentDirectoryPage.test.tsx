import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../components/ui/toast";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../demo/config", () => ({ DEMO_MODE: true }));

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

// Core Product Experience Redesign, section 3/3A: Agents is inventory
// only now -- the registration workflow moved to its own route.
describe("AgentDirectoryPage (demo mode)", () => {
  it("no longer shows the registration form inline", async () => {
    const { AgentDirectoryPage } = await import("./AgentDirectoryPage");
    await act(async () => {
      root.render(
        createElement(
          MemoryRouter,
          { initialEntries: ["/agents"] },
          createElement(ToastProvider, null, createElement(AgentDirectoryPage))
        )
      );
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(container.textContent).not.toContain("Register a new agent");
    expect(container.querySelector('a[href="/agents/register"]')).not.toBeNull();
  });
});
