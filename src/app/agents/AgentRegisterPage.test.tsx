import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";

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
        createElement(
          MemoryRouter,
          { initialEntries: ["/agents/register"] },
          createElement(AuthProvider, null, createElement(AgentRegisterPage))
        )
      );
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(container.textContent).toContain("Register an agent");
    expect(container.querySelector('input[placeholder="AP-Automation-Agent"]')).not.toBeNull();
  });

  // Regression: POST /v1/agents used to echo back a fixed, never-persisted
  // "agent-new" id, so "Go to agent & activate" led to a 404-ing detail
  // page. It now gets a real, unique id that GET /v1/agents/:id can find.
  it("registers a real, findable agent and reflects the signed-in role's actual activate permission", async () => {
    const { AgentRegisterPage } = await import("./AgentRegisterPage");
    await act(async () => {
      root.render(
        createElement(
          MemoryRouter,
          { initialEntries: ["/agents/register"] },
          createElement(AuthProvider, null, createElement(AgentRegisterPage))
        )
      );
      await new Promise((r) => setTimeout(r, 50));
    });

    const nameInput = container.querySelector('input[placeholder="AP-Automation-Agent"]') as HTMLInputElement;
    await act(async () => {
      nameInput.dispatchEvent(new Event("focusin", { bubbles: true }));
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")!.set!;
      setter.call(nameInput, "jhvb");
      nameInput.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const select = container.querySelector("select") as HTMLSelectElement;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, "value")!.set!;
      setter.call(select, select.options[1].value);
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const registerBtn = Array.from(container.querySelectorAll("button")).find((b) => /Register agent/.test(b.textContent ?? ""));
    await act(async () => {
      registerBtn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(container.textContent).toContain("Agent registered");
    // demoCurrentUser is owner, whose real permission set (see
    // fixtures/users.ts) includes agent.activate -- the CTA must offer
    // the action this identity can actually take, not a denial message.
    const goButton = Array.from(container.querySelectorAll("button")).find((b) => /Go to agent/.test(b.textContent ?? ""));
    expect(goButton?.textContent).toBe("Go to agent & activate");
    expect(container.textContent).not.toContain("requires the agent.activate permission");
  });
});
