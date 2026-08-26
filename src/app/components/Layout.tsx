import { useEffect, useRef, useState } from "react";
import { Outlet, Link, useLocation } from "react-router";
import {
  Bot,
  FlaskConical,
  Database,
  Building2,
  Compass,
  Activity,
  Menu,
  ScrollText,
  Settings,
  LogOut,
} from "lucide-react";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "./ui/sheet";
import { useIsMobile } from "./ui/use-mobile";
import { OperatorKeyField } from "../live/components/OperatorKeyField";
import { useAuth } from "../auth/AuthContext";
import { ROLE_LABELS, type CurrentUser } from "../auth/types";
import { HelpButton } from "../help/HelpButton";
import { HelpPanel } from "../help/HelpPanel";
import { page as trackPage } from "../services/analytics";
import { DEMO_MODE } from "../demo/config";
import { DemoBanner } from "./DemoBanner";
import { TourProvider } from "../demo/tour/TourProvider";

// One workflow, in order: Agents -> Governance -> Decisions -> Evidence
// -> Assurance. No department-shaped groups, no duplicate "real" vs
// "demo" sections: see audit/EXECUTION_REPORT.md. Renamed from
// Authority/Policy Studio/Runtime Decisions per the product simplification
// review (PAYREALITY_UX_REVIEW.md): "Authority" collided with three other
// unrelated uses of the same word elsewhere in the product.
// Milestone 15: `permission` names the exact backend Permission this
// destination's own page depends on to show real content (cross-checked
// against server/app/domain/rbac/permissions.py's actual route gates,
// not guessed) -- a real-session RBAC audit found every one of these
// items rendered unconditionally, so a Reviewer/Executive/Agent Admin
// routinely saw a nav entry that always dead-ended on "you don't have
// permission." `undefined` means genuinely no permission is required
// (Overview is a general landing page).
export const navItems: { path: string; label: string; icon: typeof Bot; permission?: string }[] = [
  // In the public demo, "/" is the dedicated landing page (DemoLanding),
  // not the real dashboard -- Overview points at the always-present
  // /overview alias instead so the sidebar still reaches it.
  { path: DEMO_MODE ? "/overview" : "/", label: "Overview", icon: Compass },
  { path: "/agents", label: "Agents", icon: Bot, permission: "agent.view" },
  { path: "/governance", label: "Governance", icon: ScrollText, permission: "runtime_policy.view" },
  { path: "/decisions", label: "Decisions", icon: FlaskConical, permission: "decisions.view" },
  { path: "/evidence", label: "Evidence", icon: Database, permission: "evidence.view" },
  { path: "/assurance", label: "Assurance", icon: Building2, permission: "assurance.view" },
  { path: "/organization", label: "Organisation Settings", icon: Settings, permission: "settings.view" },
];

// Extracted so the exact production filter -- not a re-typed copy of it --
// is what nav-visibility tests exercise (Layout.test.ts). Same
// permissive-when-unknown rule every other permission gate in this app
// already follows (ReviewQueuePage.tsx, AgentDetailPage.tsx): with no
// session (Operator Key bypass still active), show everything rather
// than guessing; only hide once a real signed-in user is positively
// known to lack the permission.
export function selectVisibleNavItems<T extends { permission?: string }>(
  items: readonly T[],
  user: CurrentUser | null,
  hasPermission: (permission: string) => boolean
): T[] {
  return items.filter((item) => !item.permission || !user || hasPermission(item.permission));
}

function SidebarBody({ onNavigate }: { onNavigate?: () => void }) {
  const location = useLocation();
  const { user, hasPermission } = useAuth();
  const visibleNavItems = selectVisibleNavItems(navItems, user, hasPermission);

  const isActive = (path: string) => {
    if (path === "/") return location.pathname === "/";
    return location.pathname === path || location.pathname.startsWith(`${path}/`);
  };

  return (
    <>
      {/* Logo */}
      <div className="px-5 py-5 border-b" style={{ borderColor: "var(--pr-overlay-05)" }}>
        <div className="flex items-center gap-2.5">
          <img src="/payreality-logo.png" alt="" className="w-7 h-7 rounded-lg flex-shrink-0" />
          <div>
            <h1
              className="text-sm font-semibold leading-none mb-0.5"
              style={{ color: "var(--pr-text-primary)" }}
            >
              Pay<span style={{ color: "var(--pr-warning-amber)" }}>Reality</span>
            </h1>
            <p className="text-[10px] leading-none" style={{ color: "var(--pr-text-muted)" }}>
              Runtime Authority
            </p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-3 py-3" style={{ scrollbarWidth: "none" }}>
        <div className="mb-4">
          <p
            className="px-2 mb-1 text-[10px] font-semibold uppercase tracking-widest"
            style={{ color: "var(--pr-text-muted)" }}
          >
            The Workflow
          </p>
          <div className="space-y-0.5">
            {visibleNavItems.map((item) => {
              const Icon = item.icon;
              const active = isActive(item.path);
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg transition-all duration-100 group relative"
                  style={{
                    backgroundColor: active ? "color-mix(in srgb, var(--pr-authority-blue) 12%, transparent)" : "transparent",
                    color: active ? "var(--pr-text-primary)" : "var(--pr-text-muted)",
                  }}
                  onMouseEnter={(e) => {
                    if (!active) e.currentTarget.style.backgroundColor = "var(--pr-overlay-04)";
                  }}
                  onMouseLeave={(e) => {
                    if (!active) e.currentTarget.style.backgroundColor = "transparent";
                  }}
                >
                  {active && (
                    <div
                      className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 rounded-full"
                      style={{ backgroundColor: "var(--pr-authority-blue)" }}
                    />
                  )}
                  <Icon
                    className="w-4 h-4 flex-shrink-0 transition-all"
                    style={{
                      color: active ? "var(--pr-authority-blue)" : "var(--pr-text-disabled)",
                    }}
                  />
                  <span
                    className="text-[13px] font-medium truncate flex-1"
                    style={{
                      color: active ? "var(--pr-text-primary)" : "var(--pr-text-muted)",
                    }}
                  >
                    {item.label}
                  </span>
                </Link>
              );
            })}
          </div>
        </div>
      </nav>

      {/* Bottom section */}
      <div className="px-3 pb-4 border-t pt-3" style={{ borderColor: "var(--pr-overlay-05)" }}>
        <div
          className="px-3 py-2.5 rounded-xl"
          style={{ backgroundColor: "var(--pr-overlay-03)", border: "1px solid var(--pr-overlay-04)" }}
        >
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-1.5">
              <Activity className="w-3 h-3" style={{ color: "var(--pr-trust-green)" }} />
              <span className="text-[11px] font-medium" style={{ color: "var(--pr-text-secondary)" }}>
                Runtime Authority Engine
              </span>
            </div>
          </div>
          <p className="text-[10px]" style={{ color: "var(--pr-text-muted)" }}>
            Deterministic. Fail-closed. Every decision signed.
          </p>
        </div>
        <OperatorKeyField />
        <CurrentUserWidget />
      </div>
    </>
  );
}

function CurrentUserWidget() {
  const { user, logout } = useAuth();

  if (!user) {
    return (
      <Link
        to="/login"
        className="block mt-2 px-3 py-2 text-[11px] font-medium text-center rounded-xl"
        style={{ border: "1px solid var(--pr-overlay-06)", color: "var(--pr-text-muted)" }}
      >
        Sign in
      </Link>
    );
  }

  return (
    <div
      className="px-3 py-2.5 rounded-xl mt-2 flex items-center justify-between gap-2"
      style={{ backgroundColor: "var(--pr-overlay-03)", border: "1px solid var(--pr-overlay-04)" }}
    >
      <div className="min-w-0">
        <p className="text-[11px] font-medium truncate" style={{ color: "var(--pr-text-secondary)" }}>
          {user.name}
        </p>
        <p className="text-[10px] truncate" style={{ color: "var(--pr-text-muted)" }}>
          {ROLE_LABELS[user.role] ?? user.role}
        </p>
      </div>
      <button
        type="button"
        onClick={() => logout()}
        aria-label="Sign out"
        className="flex-shrink-0 p-1.5 rounded-lg"
        style={{ color: "var(--pr-text-disabled)" }}
      >
        <LogOut className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

function LayoutInner() {
  const location = useLocation();
  const isMobile = useIsMobile();
  const [drawerOpen, setDrawerOpen] = useState(false);
  // Final Product Polish (found via real keyboard/focus QA): Radix's
  // default open-autofocus landed on the Operator Key input -- the
  // first form control after the nav links in the sidebar's own DOM
  // order, not the first meaningful destination -- and close-autofocus
  // landed on <body> instead of back on the button that opened the
  // drawer. Both are now explicit rather than left to the default,
  // regardless of why the default picked those targets.
  const navDrawerContentRef = useRef<HTMLDivElement>(null);
  const navDrawerTriggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    trackPage(location.pathname);
  }, [location.pathname]);

  const content = (
    <div className="flex flex-col h-screen">
      {DEMO_MODE && <DemoBanner />}
      <div className="flex flex-1 min-h-0" style={{ backgroundColor: "var(--pr-bg-primary)" }}>
      <a href="#pr-main-content" className="pr-skip-link">
        Skip to main content
      </a>
      {/* Sidebar (desktop) */}
      {!isMobile && (
        <aside
          className="w-[220px] flex-shrink-0 flex flex-col border-r"
          style={{
            backgroundColor: "var(--pr-bg-secondary)",
            borderColor: "var(--pr-overlay-05)",
          }}
        >
          <SidebarBody />
        </aside>
      )}

      {/* Sidebar (mobile drawer) */}
      {isMobile && (
        <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
          <SheetContent
            ref={navDrawerContentRef}
            side="left"
            className="w-[260px] max-w-[80vw] flex flex-col p-0 gap-0 border-r"
            style={{
              backgroundColor: "var(--pr-bg-secondary)",
              borderColor: "var(--pr-overlay-05)",
            }}
            onOpenAutoFocus={(e) => {
              e.preventDefault();
              navDrawerContentRef.current?.querySelector<HTMLElement>("nav a[href]")?.focus();
            }}
            onCloseAutoFocus={(e) => {
              e.preventDefault();
              navDrawerTriggerRef.current?.focus();
            }}
          >
            <SheetTitle className="sr-only">Navigation</SheetTitle>
            <SheetDescription className="sr-only">
              Jump to another section of PayReality.
            </SheetDescription>
            <SidebarBody onNavigate={() => setDrawerOpen(false)} />
          </SheetContent>
        </Sheet>
      )}

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Mobile top bar */}
        {isMobile && (
          <header
            className="flex items-center gap-3 px-4 py-3 border-b flex-shrink-0"
            style={{
              backgroundColor: "var(--pr-bg-secondary)",
              borderColor: "var(--pr-overlay-05)",
            }}
          >
            <button
              ref={navDrawerTriggerRef}
              type="button"
              onClick={() => setDrawerOpen(true)}
              aria-label="Open navigation"
              className="p-2 -ml-2 rounded-lg"
              style={{ color: "var(--pr-text-primary)" }}
            >
              <Menu className="w-5 h-5" />
            </button>
            <img src="/payreality-logo.png" alt="" className="w-6 h-6 rounded-md flex-shrink-0" />
            <h1 className="text-sm font-semibold" style={{ color: "var(--pr-text-primary)" }}>
              Pay<span style={{ color: "var(--pr-warning-amber)" }}>Reality</span>
            </h1>
            <div className="ml-auto">
              <HelpButton />
            </div>
          </header>
        )}
        {/* Desktop top bar: minimal, exists only to hold the Help entry
            point top-right (spec: "Add a Help button to the top-right
            navigation") -- everything else stays in the sidebar. */}
        {!isMobile && (
          <header
            className="flex items-center justify-end px-4 flex-shrink-0 border-b"
            style={{ height: 44, borderColor: "var(--pr-overlay-05)" }}
          >
            <HelpButton />
          </header>
        )}
        <main id="pr-main-content" className="flex-1 overflow-auto" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
      <HelpPanel />
      </div>
    </div>
  );

  return DEMO_MODE ? <TourProvider>{content}</TourProvider> : content;
}

export function Layout() {
  return <LayoutInner />;
}
