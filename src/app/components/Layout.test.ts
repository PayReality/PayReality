import { describe, expect, it } from "vitest";
import { navItems, selectVisibleNavItems } from "./Layout";
import { demoCurrentUser } from "../demo/fixtures/users";
import type { CurrentUser } from "../auth/types";

// This is the exact bug class Milestone 15 hit twice in one session: a
// permission-gated nav item silently disappears whenever a user's (or a
// demo fixture's) permission list drifts from what the role actually
// grants, with no build error and no visible symptom besides "the page
// is just gone." These tests exercise the real, exported filter
// (selectVisibleNavItems) against the real navItems list, not a
// re-typed copy of either.

function userWith(permissions: string[]): CurrentUser {
  return { ...demoCurrentUser, permissions };
}

describe("selectVisibleNavItems", () => {
  it("shows every item when there is no signed-in user (Operator Key bypass)", () => {
    const visible = selectVisibleNavItems(navItems, null, () => false);
    expect(visible).toHaveLength(navItems.length);
  });

  it("shows an item with no permission requirement regardless of role", () => {
    const overview = navItems.find((item) => item.label === "Overview")!;
    const visible = selectVisibleNavItems([overview], userWith([]), () => false);
    expect(visible).toEqual([overview]);
  });

  it("hides an item when the signed-in user lacks its required permission", () => {
    const evidence = navItems.find((item) => item.label === "Evidence")!;
    const withoutEvidence = userWith(demoCurrentUser.permissions.filter((p) => p !== "evidence.view"));
    const visible = selectVisibleNavItems(navItems, withoutEvidence, (p) =>
      withoutEvidence.permissions.includes(p)
    );
    expect(visible.map((i) => i.path)).not.toContain("/evidence");
  });

  it("matches the known-correct owner nav set (real fixture, real permission strings)", () => {
    const hasPermission = (permission: string) => demoCurrentUser.permissions.includes(permission);
    const visible = selectVisibleNavItems(navItems, demoCurrentUser, hasPermission);
    const paths = visible.map((item) => item.path).sort();

    // A real Owner has every permission in the system (ROLE_PERMISSIONS[OWNER]
    // = the full Permission enum), so every gated nav item -- including
    // Organisation Settings -- must be visible. If this ever fails, either
    // the demoCurrentUser fixture has drifted from
    // server/app/domain/rbac/permissions.py's real OWNER entry again, or
    // navItems' permission requirements changed -- both are worth catching
    // before they ship.
    // Overview's own path is DEMO_MODE ? "/overview" : "/" -- read the
    // real value from navItems rather than hard-coding either, so this
    // test passes the same way under both the demo and production builds.
    const overviewPath = navItems.find((item) => item.label === "Overview")!.path;
    expect(paths).toEqual(
      ["/agents", "/assurance", "/decisions", "/evidence", "/governance", "/organization", overviewPath].sort()
    );
  });
});
