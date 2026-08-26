import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient, ApiError, setSessionExpiredHandler } from "./apiClient";
import { setOperatorKey } from "./operatorKey";
import { setOrganizationId } from "./organizationId";
import { setSessionToken } from "./sessionToken";

// DEMO_MODE reads import.meta.env.VITE_PUBLIC_DEMO_MODE, unset under
// vitest, so every request here takes the real fetch path, not the mock
// router. This exercises the exact auth-header precedence rules
// Milestone 2/3 and Phase 10 introduced (Operator Key needs an explicit
// organization id attached to it; a session token is independent and
// never gets one) -- a regression here means the platform-admin key
// either fails every org-scoped request, or a real user's session token
// stops being sent at all.

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.clear();
  fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  setSessionExpiredHandler(null);
});

function headersFromLastCall(): Headers {
  const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return init.headers as Headers;
}

describe("apiClient request auth headers", () => {
  it("sends no auth headers at all when no key or session is set", async () => {
    await apiClient.get("/v1/agents");
    const headers = headersFromLastCall();
    expect(headers.has("X-PayReality-Operator-Key")).toBe(false);
    expect(headers.has("Authorization")).toBe(false);
  });

  it("attaches the organization id alongside the Operator Key when both are set", async () => {
    setOperatorKey("op-secret-key");
    setOrganizationId("org-123");
    await apiClient.get("/v1/agents");
    const headers = headersFromLastCall();
    expect(headers.get("X-PayReality-Operator-Key")).toBe("op-secret-key");
    expect(headers.get("X-PayReality-Organization-Id")).toBe("org-123");
  });

  it("sends the Operator Key with no organization header when none is stored", async () => {
    setOperatorKey("op-secret-key");
    await apiClient.get("/v1/agents");
    const headers = headersFromLastCall();
    expect(headers.get("X-PayReality-Operator-Key")).toBe("op-secret-key");
    expect(headers.has("X-PayReality-Organization-Id")).toBe(false);
  });

  it("never attaches an organization id for a session-token caller (server resolves it from the account)", async () => {
    setSessionToken("session-abc");
    setOrganizationId("org-should-be-ignored");
    await apiClient.get("/v1/agents");
    const headers = headersFromLastCall();
    expect(headers.get("Authorization")).toBe("Bearer session-abc");
    expect(headers.has("X-PayReality-Organization-Id")).toBe(false);
  });

  it("sends both the Operator Key and a session token together when both are present", async () => {
    setOperatorKey("op-secret-key");
    setSessionToken("session-abc");
    await apiClient.get("/v1/agents");
    const headers = headersFromLastCall();
    expect(headers.get("X-PayReality-Operator-Key")).toBe("op-secret-key");
    expect(headers.get("Authorization")).toBe("Bearer session-abc");
  });
});

describe("apiClient response handling", () => {
  it("throws ApiError with the parsed body on a non-ok response", async () => {
    fetchMock.mockResolvedValue(jsonResponse(403, { detail: "permission_denied" }));
    await expect(apiClient.get("/v1/agents")).rejects.toBeInstanceOf(ApiError);
    try {
      await apiClient.get("/v1/agents");
      throw new Error("expected apiClient.get to reject");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).status).toBe(403);
      expect((e as ApiError).body).toEqual({ detail: "permission_denied" });
    }
  });

  it("returns undefined for a 204 with no body, without attempting to parse JSON", async () => {
    const res = { ok: true, status: 204, json: vi.fn() } as unknown as Response;
    fetchMock.mockResolvedValue(res);
    const result = await apiClient.delete("/v1/agents/some-id");
    expect(result).toBeUndefined();
    expect((res.json as ReturnType<typeof vi.fn>)).not.toHaveBeenCalled();
  });

  it("JSON-encodes a plain object body but passes FormData through untouched", async () => {
    await apiClient.post("/v1/agents", { name: "test" });
    const [, jsonInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(jsonInit.body).toBe(JSON.stringify({ name: "test" }));

    fetchMock.mockClear();
    const form = new FormData();
    await apiClient.post("/v1/documents", form);
    const [, formInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(formInit.body).toBe(form);
  });
});

describe("apiClient session-expiry handler", () => {
  it("fires the registered handler on a 401 with invalid_or_expired_credential", async () => {
    const handler = vi.fn();
    setSessionExpiredHandler(handler);
    fetchMock.mockResolvedValue(jsonResponse(401, { detail: "invalid_or_expired_credential" }));
    await expect(apiClient.get("/v1/agents")).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("fires the registered handler on a 401 with authentication_required", async () => {
    const handler = vi.fn();
    setSessionExpiredHandler(handler);
    fetchMock.mockResolvedValue(jsonResponse(401, { detail: "authentication_required" }));
    await expect(apiClient.get("/v1/agents")).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("does not fire on a 401 for a wrong-password login rejection (a different, non-session detail code)", async () => {
    const handler = vi.fn();
    setSessionExpiredHandler(handler);
    fetchMock.mockResolvedValue(jsonResponse(401, { detail: "invalid_credentials" }));
    await expect(apiClient.get("/v1/agents")).rejects.toBeInstanceOf(ApiError);
    expect(handler).not.toHaveBeenCalled();
  });

  it("does not fire on a 403 (authorization failure, never treated as a session problem)", async () => {
    const handler = vi.fn();
    setSessionExpiredHandler(handler);
    fetchMock.mockResolvedValue(jsonResponse(403, { detail: "permission_denied" }));
    await expect(apiClient.get("/v1/agents")).rejects.toBeInstanceOf(ApiError);
    expect(handler).not.toHaveBeenCalled();
  });

  it("still throws ApiError normally when no handler is registered", async () => {
    setSessionExpiredHandler(null);
    fetchMock.mockResolvedValue(jsonResponse(401, { detail: "invalid_or_expired_credential" }));
    await expect(apiClient.get("/v1/agents")).rejects.toBeInstanceOf(ApiError);
  });
});
