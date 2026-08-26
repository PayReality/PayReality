import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

// Core Product Experience Redesign, section 3A: Agent Registry -- the
// registration workflow's own dedicated page.
describe("AgentRegisterPage (demo mode)", () => {
  it("renders the registration form", async () => {
    const { AgentRegisterPage } = await import("./AgentRegisterPage");
    await act(async () => {
      root.render(
        createElement(MemoryRouter, { initialEntries: ["/agents/register"] }, createElement(AgentRegisterPage))
      );
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(container.textContent).toContain("Register an agent");
    expect(container.querySelector('input[placeholder="AP-Automation-Agent"]')).not.toBeNull();
  });
});
