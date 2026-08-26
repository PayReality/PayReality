import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./AuthContext";
import { apiClient, ApiError } from "../live/apiClient";
import type { CurrentUser, LoginResponse } from "./types";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

// DEMO_MODE reads import.meta.env.VITE_PUBLIC_DEMO_MODE, unset under
// vitest, so AuthProvider takes its real (non-demo) branch here: no
// session token in localStorage means it goes straight to
// user=null/loading=false, and login() below drives it through the
// mocked authApi exactly the way a real login would.
const mockLogin = vi.fn<(email: string, password: string) => Promise<LoginResponse>>();
vi.mock("./authApi", () => ({
  authApi: {
    login: (email: string, password: string) => mockLogin(email, password),
    logout: vi.fn().mockResolvedValue(undefined),
    me: vi.fn(),
  },
}));

function baseUser(permissions: string[]): CurrentUser {
  return {
    id: "user-test",
    organization_id: "org-test",
    email: "test@example.com",
    name: "Test User",
    role: "reviewer",
    status: "active",
    mfa_enabled: false,
    must_reset_password: false,
    last_login_at: null,
    permissions,
  };
}

let container: HTMLDivElement;
let root: Root;
let latest: ReturnType<typeof useAuth> | null;

function Probe() {
  latest = useAuth();
  return null;
}

function mount() {
  act(() => {
    root.render(createElement(AuthProvider, null, createElement(Probe)));
  });
}

beforeEach(() => {
  mockLogin.mockReset();
  localStorage.clear();
  latest = null;
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

describe("hasPermission", () => {
  it("returns false for every permission when no user is signed in", () => {
    mount();
    expect(latest!.user).toBeNull();
    expect(latest!.hasPermission("evidence.view")).toBe(false);
  });

  it("returns true only for permissions actually present on the signed-in user", async () => {
    mockLogin.mockResolvedValue({
      token: "session-token",
      expires_at: "2026-12-31T00:00:00Z",
      user: baseUser(["decisions.view", "evidence.view"]),
    });
    mount();

    await act(async () => {
      await latest!.login("test@example.com", "password");
    });

    expect(latest!.hasPermission("decisions.view")).toBe(true);
    expect(latest!.hasPermission("evidence.view")).toBe(true);
    // Not granted to this user -- must not be true just because some
    // permission is. This is the exact shape of the fixture-drift bug
    // this session found in demoCurrentUser: a stale list that grants
    // more (or less) than the role really has.
    expect(latest!.hasPermission("settings.view")).toBe(false);
    expect(latest!.hasPermission("runtime_policy.publish")).toBe(false);
  });

  it("reflects logout by returning to a fully unpermissioned state", async () => {
    mockLogin.mockResolvedValue({
      token: "session-token",
      expires_at: "2026-12-31T00:00:00Z",
      user: baseUser(["decisions.view"]),
    });
    mount();
    await act(async () => {
      await latest!.login("test@example.com", "password");
    });
    expect(latest!.hasPermission("decisions.view")).toBe(true);

    await act(async () => {
      await latest!.logout();
    });
    expect(latest!.user).toBeNull();
    expect(latest!.hasPermission("decisions.view")).toBe(false);
  });
});

describe("session expiry", () => {
  // Genuine integration test (not a mocked apiClient): AuthProvider
  // registers its handler with the real apiClient module on mount, so
  // a real 401 flowing through a real apiClient.get() call is the only
  // way to prove the registration actually works end to end, not just
  // that the two modules independently do what they claim to.
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("flips sessionExpired true and clears the user when any request hits an expired-credential 401", async () => {
    mockLogin.mockResolvedValue({
      token: "session-token",
      expires_at: "2026-12-31T00:00:00Z",
      user: baseUser(["decisions.view"]),
    });
    mount();
    await act(async () => {
      await latest!.login("test@example.com", "password");
    });
    expect(latest!.user).not.toBeNull();
    expect(latest!.sessionExpired).toBe(false);

    fetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: "invalid_or_expired_credential" }),
    });
    await act(async () => {
      await expect(apiClient.get("/v1/agents")).rejects.toBeInstanceOf(ApiError);
    });

    expect(latest!.sessionExpired).toBe(true);
    expect(latest!.user).toBeNull();
  });

  it("does not flip sessionExpired on an ordinary 403 permission-denied response", async () => {
    mount();
    fetchMock.mockResolvedValue({
      ok: false,
      status: 403,
      json: () => Promise.resolve({ detail: "permission_denied" }),
    });
    await act(async () => {
      await expect(apiClient.get("/v1/agents")).rejects.toBeInstanceOf(ApiError);
    });
    expect(latest!.sessionExpired).toBe(false);
  });

  it("clears sessionExpired on a fresh successful login", async () => {
    mount();
    fetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: "invalid_or_expired_credential" }),
    });
    await act(async () => {
      await expect(apiClient.get("/v1/agents")).rejects.toBeInstanceOf(ApiError);
    });
    expect(latest!.sessionExpired).toBe(true);

    mockLogin.mockResolvedValue({
      token: "session-token-2",
      expires_at: "2026-12-31T00:00:00Z",
      user: baseUser(["decisions.view"]),
    });
    await act(async () => {
      await latest!.login("test@example.com", "password");
    });
    expect(latest!.sessionExpired).toBe(false);
  });
});
