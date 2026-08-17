import { useEffect, useRef } from "react";

// This app has no data-fetching/caching library (no React Query/SWR/
// Redux) -- every page independently fetches its own data in a
// mount-time useEffect via apiClient. That already means ordinary
// in-app navigation (clicking to a different route) gets fresh data:
// react-router's routes are lazy-loaded, so navigating to a different
// page unmounts the previous route and mounts a brand new component
// instance, which runs its own fetch again from scratch. There is no
// stale in-memory cache anywhere for a fresh mount to accidentally read.
//
// The real gap this module closes is narrower, and different, than
// "any navigation": a page that is ALREADY mounted has no way to learn
// that a resource it depends on changed somewhere else -- either in a
// second open browser tab/window, or simply because the user has left
// this tab sitting open (backgrounded or just idle) while a mutation
// happened and is now looking at it again. Both are ordinary operator
// workflows for a dashboard app, not edge cases.
//
// This is deliberately NOT a general cache-invalidation framework: it
// carries no cached data of its own, has no query keys, and does not
// intercept requests. It is a small, targeted "something changed, you
// may want to refetch" signal that a page opts into for exactly the
// resources it actually depends on, and reacts to however it already
// knows how to (calling its own existing load function).

export type ResourceKind =
  | "agents"
  | "certificates"
  | "policies"
  | "decisions"
  | "evidence"
  | "organization";

const STORAGE_KEY_PREFIX = "pr:resource-changed:";

// Call this immediately after a mutation succeeds (an agent registered/
// activated/suspended/retired/revoked, a certificate rotated, a policy
// deployed/activated/retired, a decision resolved, an evidence record
// created, an organisation or its structure updated). Writing to
// localStorage is what makes this cross-TAB: the browser's own
// `storage` event fires in every OTHER open tab/window automatically
// (never in the tab that wrote it), which is exactly the signal a page
// in a different tab needs. The page that performed the mutation
// itself should keep updating its own local state directly, exactly as
// it already does -- this is additive, not a replacement for that.
export function notifyResourceChanged(kind: ResourceKind): void {
  try {
    localStorage.setItem(STORAGE_KEY_PREFIX + kind, String(Date.now()));
  } catch {
    // Some private-browsing modes throw on localStorage access. This is
    // a best-effort freshness signal, never a condition the mutation
    // itself should be considered to depend on.
  }
}

const MIN_REFRESH_INTERVAL_MS = 3000;

// Subscribe a page to be told when any of `kinds` may have changed,
// either in another tab (the storage event) or because this tab was
// just brought back into focus/visibility after being backgrounded --
// the other real staleness scenario a fetch-on-mount-only architecture
// can't cover by itself. `onStale` should re-run whatever load function
// this component already uses on mount; deciding what "stale" means is
// the caller's responsibility, not this hook's. Debounced to avoid a
// refetch storm from rapid alt-tabbing.
export function useResourceSync(kinds: ResourceKind[], onStale: () => void): void {
  const lastRefreshRef = useRef(Date.now());
  const onStaleRef = useRef(onStale);
  onStaleRef.current = onStale;
  const kindsKey = kinds.join(",");

  useEffect(() => {
    const keys = new Set(kindsKey.split(",").filter(Boolean).map((k) => STORAGE_KEY_PREFIX + k));
    if (keys.size === 0) return;

    function trigger() {
      const now = Date.now();
      if (now - lastRefreshRef.current < MIN_REFRESH_INTERVAL_MS) return;
      lastRefreshRef.current = now;
      onStaleRef.current();
    }

    function handleStorage(e: StorageEvent) {
      if (e.key && keys.has(e.key)) trigger();
    }
    function handleVisibility() {
      if (document.visibilityState === "visible") trigger();
    }

    window.addEventListener("storage", handleStorage);
    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("focus", handleVisibility);
    return () => {
      window.removeEventListener("storage", handleStorage);
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("focus", handleVisibility);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kindsKey]);
}
