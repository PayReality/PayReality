// Milestone 3 (Enterprise Surface Isolation): PayReality Enterprise v1.0's
// Operator Key became platform-admin-only (Milestone 2) -- it no longer
// belongs to, or defaults to, any single organization. Every operator-key
// request must now name its target organization explicitly
// (X-PayReality-Operator-Id... X-PayReality-Organization-Id, see
// server/app/dependencies.py::get_current_organization). This mirrors
// operatorKey.ts exactly: one browser-local value, read by apiClient.ts,
// set from OperatorKeyField.tsx alongside the key itself.
const STORAGE_KEY = "payreality_organization_id";

export function getOrganizationId(): string {
  return localStorage.getItem(STORAGE_KEY) ?? "";
}

export function setOrganizationId(id: string): void {
  const trimmed = id.trim();
  if (trimmed) localStorage.setItem(STORAGE_KEY, trimmed);
  else localStorage.removeItem(STORAGE_KEY);
}
