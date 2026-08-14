import { getOperatorKey } from "./operatorKey";
import { getOrganizationId } from "./organizationId";
import { getSessionToken } from "./sessionToken";
import { DEMO_MODE } from "../demo/config";
import { resolveMockResponse } from "../demo/mockRouter";

const API_BASE = import.meta.env.VITE_API_URL ?? "/api";

export class ApiError extends Error {
  constructor(public status: number, public body: unknown) {
    super(`API error ${status}`);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  // Every requirement of the public demo (mock data, no real backend
  // reachable, disabled destructive actions) lives entirely behind this
  // one branch -- production's path below it is completely untouched.
  if (DEMO_MODE) {
    return resolveMockResponse<T>(init.method ?? "GET", path, init.body);
  }

  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const operatorKey = getOperatorKey();
  if (operatorKey && !headers.has("X-PayReality-Operator-Key")) {
    headers.set("X-PayReality-Operator-Key", operatorKey);
    // Milestone 3 (Enterprise Surface Isolation): the Operator Key is
    // platform-admin-only (Milestone 2) and has no organization of its
    // own -- every org-scoped request it makes must now name one
    // explicitly. Only attached alongside the Operator Key itself,
    // since a session-token caller's organization is already resolved
    // server-side from their own account and never needs this header.
    const organizationId = getOrganizationId();
    if (organizationId && !headers.has("X-PayReality-Organization-Id")) {
      headers.set("X-PayReality-Organization-Id", organizationId);
    }
  }
  // Phase 10 (RBAC.md): a logged-in human user's session token, sent
  // alongside the Operator Key above. The backend always checks the
  // Operator Key first (require_permission), so this only takes effect
  // for someone who hasn't set one -- the normal case for a real user.
  const sessionToken = getSessionToken();
  if (sessionToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${sessionToken}`);
  }

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const apiClient = {
  get: <T,>(path: string, init: RequestInit = {}) => request<T>(path, init),
  post: <T,>(path: string, body?: unknown, init: RequestInit = {}) =>
    request<T>(path, {
      ...init,
      method: "POST",
      body: body instanceof FormData ? body : body !== undefined ? JSON.stringify(body) : undefined,
    }),
  postSigned: <T,>(path: string, rawBody: string, headers: Record<string, string>) =>
    request<T>(path, { method: "POST", body: rawBody, headers }),
  patch: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body !== undefined ? JSON.stringify(body) : undefined }),
  put: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body !== undefined ? JSON.stringify(body) : undefined }),
  delete: <T,>(path: string) => request<T>(path, { method: "DELETE" }),
};
