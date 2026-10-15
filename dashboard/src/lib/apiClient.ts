import { clearSessionToken, getSessionToken } from "./session";

// Real backend base URL. No deployed URL is ever hardcoded here --
// VITE_API_URL is read at build/dev time (see .env.example) with a
// sensible local-dev default matching the backend's own default dev
// port (server/app/main.py runs uvicorn on :8000 in local development).
const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
  ) {
    super(`API error ${status}`);
  }
}

export function errorDetail(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  if (error.body && typeof error.body === "object" && "detail" in error.body) {
    const detail = (error.body as { detail?: unknown }).detail;
    return typeof detail === "string" ? detail : null;
  }
  return null;
}

// A real, invalid/expired session (never a permission problem -- a 403
// never reaches here) routes the whole app back to the login screen
// instead of leaving a page stuck on a silently-failed fetch. A single
// callback, registered once by AuthProvider, exactly mirrors the
// existing Runtime Authority app's own apiClient convention.
const SESSION_EXPIRED_DETAILS = new Set(["authentication_required", "invalid_or_expired_credential"]);
let onSessionExpired: (() => void) | null = null;
export function setSessionExpiredHandler(handler: (() => void) | null) {
  onSessionExpired = handler;
}

// Shared by every call below: attaches auth, and on a non-2xx response
// parses the real error body (so ApiError.body/errorDetail/errorMessage
// keep working identically for JSON and non-JSON success responses) and
// handles the global session-expiry signal exactly once, in one place.
async function rawRequest(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  // FormData (the CSV import upload) must never get an explicit
  // Content-Type here -- the browser sets its own, with the correct
  // multipart boundary, only when it stays unset.
  if (!headers.has("Content-Type") && init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const token = getSessionToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    if (res.status === 401) {
      const detail = body && typeof body === "object" ? (body as { detail?: string }).detail : undefined;
      if (detail && SESSION_EXPIRED_DETAILS.has(detail)) {
        clearSessionToken();
        onSessionExpired?.();
      }
    }
    throw new ApiError(res.status, body);
  }
  return res;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await rawRequest(path, init);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return text ? JSON.parse(text) : (undefined as T);
}

// Extracts the real filename the backend's own `Content-Disposition:
// attachment; filename="..."` header carries, for a real export download
// (CSV import, Reports exports). Never fabricates one when the header is
// missing -- callers supply their own fallback in that case.
function filenameFromContentDisposition(value: string | null): string | null {
  if (!value) return null;
  const match = /filename\*?=(?:UTF-8''|")?([^";]+)"?/i.exec(value);
  return match ? decodeURIComponent(match[1]) : null;
}

export const apiClient = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }),
  patch: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body !== undefined ? JSON.stringify(body) : undefined }),
  put: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body !== undefined ? JSON.stringify(body) : undefined }),
  delete: <T,>(path: string) => request<T>(path, { method: "DELETE" }),
  // Multipart upload (the CSV import's `file` + `workflow_id` +
  // `column_mapping` form fields) -- never JSON-serialised.
  postForm: <T,>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form }),
  // A real file download: returns the response's own bytes and real
  // filename, for a caller to hand to the browser's own save mechanism
  // (see lib/download.ts) -- never text read as if it were JSON.
  downloadGet: async (path: string): Promise<{ blob: Blob; filename: string | null }> => {
    const res = await rawRequest(path);
    const blob = await res.blob();
    return { blob, filename: filenameFromContentDisposition(res.headers.get("Content-Disposition")) };
  },
};
