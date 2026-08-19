import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RequirePermission } from "./RequireAuth";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

// RequirePermission is the one component every permission-gated page in
// this app wraps its content in (see routes.tsx). Mocking useAuth here
// rather than going through a real AuthProvider keeps this test focused
// purely on the gate's own branching, independent of login/session
// plumbing (covered separately in AuthContext.test.tsx).
const mockHasPermission = vi.fn<(permission: string) => boolean>();
vi.mock("./AuthContext", () => ({
  useAuth: () => ({ hasPermission: mockHasPermission }),
}));

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  mockHasPermission.mockReset();
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
