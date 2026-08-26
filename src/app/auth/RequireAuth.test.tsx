import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RequireAuth, RequirePermission } from "./RequireAuth";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

// RequirePermission is the one component every permission-gated page in
// this app wraps its content in (see routes.tsx). Mocking useAuth here
// rather than going through a real AuthProvider keeps this test focused
// purely on the gate's own branching, independent of login/session
// plumbing (covered separately in AuthContext.test.tsx).
const mockHasPermission = vi.fn<(permission: string) => boolean>();
const mockAuthState: { user: unknown; loading: boolean; sessionExpired: boolean } = {
  user: null,
  loading: false,
  sessionExpired: false,
};
vi.mock("./AuthContext", () => ({
  useAuth: () => ({ hasPermission: mockHasPermission, ...mockAuthState }),
}));

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  mockHasPermission.mockReset();
  mockAuthState.user = null;
  mockAuthState.loading = false;
  mockAuthState.sessionExpired = false;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => {
    root.unmount();
  });
  container.remove();
});

describe("RequirePermission", () => {
  it("renders its children when the user has the required permission", () => {
    mockHasPermission.mockReturnValue(true);
    act(() => {
      root.render(
        createElement(
          RequirePermission,
          { permission: "evidence.view" },
          createElement("div", { "data-testid": "gated-content" }, "Evidence page")
        )
      );
    });
    expect(mockHasPermission).toHaveBeenCalledWith("evidence.view");
    expect(container.textContent).toBe("Evidence page");
  });

  it("renders a no-access message instead of children when the permission is missing", () => {
    mockHasPermission.mockReturnValue(false);
    act(() => {
      root.render(
        createElement(
          RequirePermission,
          { permission: "settings.view" },
          createElement("div", null, "Organisation Settings page")
        )
      );
    });
    expect(container.textContent).not.toContain("Organisation Settings page");
    expect(container.textContent).toContain("don't have permission");
  });
});

describe("RequireAuth session-expiry state", () => {
  it("renders the session-expired recovery state instead of children when sessionExpired is true", () => {
    mockAuthState.sessionExpired = true;
    mockAuthState.loading = false;
    mockAuthState.user = null;
    act(() => {
      root.render(
        createElement(
          MemoryRouter,
          { initialEntries: ["/agents"] },
          createElement(RequireAuth, null, createElement("div", null, "Agents page"))
        )
      );
    });
    expect(container.textContent).not.toContain("Agents page");
    expect(container.textContent).toContain("session has expired");
    expect(container.textContent).toContain("Sign in again");
  });

  it("renders children normally when sessionExpired is false and a user is present", () => {
    mockAuthState.sessionExpired = false;
    mockAuthState.loading = false;
    mockAuthState.user = { id: "u1" };
    act(() => {
      root.render(
        createElement(
          MemoryRouter,
          { initialEntries: ["/agents"] },
          createElement(RequireAuth, null, createElement("div", null, "Agents page"))
        )
      );
    });
    expect(container.textContent).toContain("Agents page");
  });

  it("prioritizes the session-expired state over the loading state", () => {
    mockAuthState.sessionExpired = true;
    mockAuthState.loading = true;
    act(() => {
      root.render(
        createElement(
          MemoryRouter,
          { initialEntries: ["/agents"] },
          createElement(RequireAuth, null, createElement("div", null, "Agents page"))
        )
      );
    });
    expect(container.textContent).toContain("session has expired");
    expect(container.textContent).not.toBe("Loading...");
  });
});
