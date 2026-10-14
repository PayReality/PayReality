// Session token storage for this standalone dashboard. Deliberately its
// own tiny module (not shared with src/app/live/sessionToken.ts -- this
// product is a separate app, see AGENTS.md) but the same storage
// convention: localStorage, so a page reload keeps the user signed in
// until they explicitly log out or the token itself expires server-side.
const STORAGE_KEY = "payreality_di_dashboard_session_token";

export function getSessionToken(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setSessionToken(token: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, token);
  } catch {
    // Storage can throw (private browsing, quota); losing persistence
    // across reloads is a degraded experience, not a crash.
  }
}

export function clearSessionToken(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // see above
  }
}
