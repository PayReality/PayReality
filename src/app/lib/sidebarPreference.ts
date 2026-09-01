// Product Experience V3.2, section 5: a per-browser display preference,
// not organisational configuration, so it is persisted exactly the way
// theme.ts already persists its own local-only preference -- same
// mechanism, same reasoning, not a new pattern. Deliberately not backend
// state: no existing user-preference storage mechanism exists in this
// codebase for the manual builder or elsewhere to reuse, and section 5
// itself says not to introduce backend persistence just for this.
const STORAGE_KEY = "payreality_sidebar_collapsed";

export function getSidebarCollapsed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "true";
  } catch {
    // Section 5's own spirit: a UI preference should never break the
    // page if storage is unavailable (a private window, a policy that
    // blocks it) -- default to expanded, the safer, more discoverable
    // state for a first-time or storage-denied visitor.
    return false;
  }
}

export function setSidebarCollapsed(collapsed: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, String(collapsed));
  } catch {
    // Nothing to recover: the preference simply will not persist this
    // session, which is the correct degraded behavior for a UI-only
    // preference, not an error worth surfacing to the user.
  }
}
