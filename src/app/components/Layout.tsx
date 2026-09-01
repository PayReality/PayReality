import { useEffect, useRef, useState, type ReactNode } from "react";
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
  Moon,
  Sun,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "./ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";
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
import { getTheme, setTheme, type Theme } from "../lib/theme";
import { getSidebarCollapsed, setSidebarCollapsed } from "../lib/sidebarPreference";

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
//
// Product Experience V3.2, section 1/8: the locked top-level IA
// (Overview/Agents/Governance/Decisions/Evidence/Assurance/Settings) is
// completely unchanged -- `group` below is a purely visual label used
// only to add a small heading above "Workspace" items in expanded mode
// (section 8's own suggested grouping), never a route, never a new
// concept, never rendered anywhere permission logic reads. Settings is
// deliberately ungrouped: it renders anchored at the bottom of the nav
// list instead (see SidebarBody below), matching section 8's "Settings
// anchored lower in the shell."
export const navItems: { path: string; label: string; icon: typeof Bot; permission?: string; group?: "workspace" | "trust" }[] = [
  // In the public demo, "/" is the dedicated landing page (DemoLanding),
  // not the real dashboard -- Overview points at the always-present
  // /overview alias instead so the sidebar still reaches it.
  { path: DEMO_MODE ? "/overview" : "/", label: "Overview", icon: Compass, group: "workspace" },
  { path: "/agents", label: "Agents", icon: Bot, permission: "agent.view", group: "workspace" },
  { path: "/governance", label: "Governance", icon: ScrollText, permission: "runtime_policy.view", group: "workspace" },
  { path: "/decisions", label: "Decisions", icon: FlaskConical, permission: "decisions.view", group: "workspace" },
  { path: "/evidence", label: "Evidence", icon: Database, permission: "evidence.view", group: "trust" },
  { path: "/assurance", label: "Assurance", icon: Building2, permission: "assurance.view", group: "trust" },
  { path: "/organization", label: "Organisation Settings", icon: Settings, permission: "settings.view" },
];

const GROUP_LABEL: Record<string, string> = {
  workspace: "Workspace",
  trust: "Trust",
};

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

function NavLink({ item, active, collapsed }: { item: (typeof navItems)[number]; active: boolean; collapsed: boolean }) {
  const Icon = item.icon;
  const link = (
    <Link
      to={item.path}
      aria-current={active ? "page" : undefined}
      aria-label={collapsed ? item.label : undefined}
      className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg transition-all group relative"
      style={{
        backgroundColor: active ? "color-mix(in srgb, var(--pr-authority-blue) 14%, transparent)" : "transparent",
        color: active ? "var(--pr-text-primary)" : "var(--pr-text-muted)",
        justifyContent: collapsed ? "center" : "flex-start",
        transitionDuration: "var(--pr-motion-fast)",
        transitionTimingFunction: "var(--pr-motion-ease)",
      }}
      onMouseEnter={(e) => {
        if (!active) e.currentTarget.style.backgroundColor = "var(--pr-overlay-04)";
      }}
      onMouseLeave={(e) => {
        if (!active) e.currentTarget.style.backgroundColor = "transparent";
      }}
    >
      {/* Product Experience V3.2, section 7: the active indicator is now
          background tint + a left edge bar + icon emphasis together,
          never text color alone (already true before this milestone) --
          strengthened so it survives collapsed mode too, where the edge
          bar and icon color are the ONLY signal left once the label and
          its own color disappear. */}
      {active && (
        <div
          className="absolute left-0 top-1/2 -translate-y-1/2 rounded-full"
          style={{ width: 3, height: 18, backgroundColor: "var(--pr-authority-blue)" }}
        />
      )}
      <Icon
        className="w-4 h-4 flex-shrink-0 transition-all"
        style={{
          color: active ? "var(--pr-authority-blue)" : "var(--pr-text-disabled)",
          transitionDuration: "var(--pr-motion-fast)",
        }}
      />
      {!collapsed && (
        <span
          className="text-[13px] font-medium truncate flex-1"
          style={{ color: active ? "var(--pr-text-primary)" : "var(--pr-text-muted)" }}
        >
          {item.label}
        </span>
      )}
    </Link>
  );

  // Section 4: "Every icon must have an accessible tooltip on hover and
  // keyboard focus" -- only meaningful (and only mounted) once the label
  // itself is gone; in expanded mode the visible text already names the
  // destination, so wrapping every link in a Tooltip there would be
  // redundant noise, not an accessibility improvement.
  if (!collapsed) return link;

  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right">{item.label}</TooltipContent>
    </Tooltip>
  );
}

function SidebarBody({
  onNavigate,
  collapsed,
  onToggleCollapsed,
}: {
  onNavigate?: () => void;
  collapsed: boolean;
  onToggleCollapsed?: () => void;
}) {
  const location = useLocation();
  const { user, hasPermission } = useAuth();
  const visibleNavItems = selectVisibleNavItems(navItems, user, hasPermission);
  const workspaceItems = visibleNavItems.filter((i) => i.group === "workspace");
  const trustItems = visibleNavItems.filter((i) => i.group === "trust");
  const ungroupedItems = visibleNavItems.filter((i) => !i.group);

  const isActive = (path: string) => {
    if (path === "/") return location.pathname === "/";
    return location.pathname === path || location.pathname.startsWith(`${path}/`);
  };

  function renderGroup(label: string | null, items: typeof visibleNavItems) {
    if (items.length === 0) return null;
    return (
      <div className="mb-4" key={label ?? "ungrouped"}>
        {label && !collapsed && (
          <p
            className="px-2 mb-1 text-[10px] font-semibold uppercase tracking-widest"
            style={{ color: "var(--pr-text-muted)" }}
          >
            {label}
          </p>
        )}
        <div className="space-y-0.5">
          {items.map((item) => (
            <div key={item.path} onClick={onNavigate}>
              <NavLink item={item} active={isActive(item.path)} collapsed={collapsed} />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <>
      {/* Logo + collapse control */}
      <div
        className="px-5 py-5 border-b flex items-center gap-2"
        style={{ borderColor: "var(--pr-overlay-05)", justifyContent: collapsed ? "center" : "space-between" }}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <img src="/payreality-logo.png" alt="" className="w-7 h-7 rounded-lg flex-shrink-0" />
          {!collapsed && (
            <div className="min-w-0">
              <h1
                className="text-sm font-semibold leading-none mb-0.5 truncate"
                style={{ color: "var(--pr-text-primary)" }}
              >
                Pay<span style={{ color: "var(--pr-warning-amber)" }}>Reality</span>
              </h1>
              <p className="text-[10px] leading-none" style={{ color: "var(--pr-text-muted)" }}>
                Runtime Authority
              </p>
            </div>
          )}
        </div>
        {/* Section 6: a real, discoverable, keyboard-accessible control in
            BOTH states -- never a tiny invisible chevron. Placed in the
            header (not floating on the sidebar's edge) so it is exactly
            as easy to find collapsed as expanded. */}
        {onToggleCollapsed && !collapsed && (
          <button
            type="button"
            onClick={onToggleCollapsed}
            aria-label="Collapse navigation"
            className="flex-shrink-0 p-1.5 rounded-lg"
            style={{ color: "var(--pr-text-muted)" }}
          >
            <PanelLeftClose className="w-4 h-4" />
          </button>
        )}
      </div>
      {onToggleCollapsed && collapsed && (
        <div className="px-3 pt-3 flex justify-center">
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={onToggleCollapsed}
                aria-label="Expand navigation"
                className="p-2 rounded-lg"
                style={{ color: "var(--pr-text-muted)" }}
              >
                <PanelLeftOpen className="w-4 h-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="right">Expand navigation</TooltipContent>
          </Tooltip>
        </div>
      )}

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-3 py-3" style={{ scrollbarWidth: "none" }}>
        {renderGroup(GROUP_LABEL.workspace, workspaceItems)}
        {renderGroup(GROUP_LABEL.trust, trustItems)}
      </nav>

      {/* Bottom section: Settings anchored lower (section 8), then the
          secondary utility widgets, which only render as full labeled
          panels in expanded mode -- section 4's own collapsed-mode
          content list ("compact mark, navigation icons, active state,
          badges, collapse control") does not include the Runtime
          Authority status card or the Operator Key field, so both are
          hidden rather than compressed into something illegible.
          Theme toggle and sign-out remain reachable, as small tooltipped
          icon buttons, rather than trapping a collapsed user into
          expanding just to sign out. */}
      <div className="px-3 pb-4 border-t pt-3" style={{ borderColor: "var(--pr-overlay-05)" }}>
        {ungroupedItems.length > 0 && (
          <div className="space-y-0.5 mb-3">
            {ungroupedItems.map((item) => (
              <div key={item.path} onClick={onNavigate}>
                <NavLink item={item} active={isActive(item.path)} collapsed={collapsed} />
              </div>
            ))}
          </div>
        )}
        {!collapsed && (
          <>
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
            <ThemeToggle collapsed={false} />
            <CurrentUserWidget collapsed={false} />
          </>
        )}
        {collapsed && (
          <div className="flex flex-col items-center gap-1">
            <ThemeToggle collapsed />
            <CurrentUserWidget collapsed />
          </div>
        )}
      </div>
    </>
  );
}

// Visual System V3, section 5: the shell had a real, working per-browser
// theme preference (lib/theme.ts, applied before first paint) but no
// visible control to change it -- only Organisation Settings -> General
// exposed one, one navigation away from every other page. Same
// mechanism, just reachable from the shell itself now.
function ThemeToggle({ collapsed }: { collapsed: boolean }) {
  const [theme, setThemeState] = useState<Theme>(() => getTheme());

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    setThemeState(next);
  }

  const label = `Switch to ${theme === "dark" ? "light" : "dark"} mode`;

  if (collapsed) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={toggle}
            aria-label={label}
            className="p-2 rounded-lg"
            style={{ color: "var(--pr-text-muted)" }}
          >
            {theme === "dark" ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
          </button>
        </TooltipTrigger>
        <TooltipContent side="right">{label}</TooltipContent>
      </Tooltip>
    );
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={label}
      className="w-full mt-2 flex items-center justify-between gap-2 px-3 py-2 rounded-xl"
      style={{ backgroundColor: "var(--pr-overlay-03)", border: "1px solid var(--pr-overlay-04)" }}
    >
      <span className="flex items-center gap-1.5 text-[11px] font-medium" style={{ color: "var(--pr-text-secondary)" }}>
        {theme === "dark" ? <Moon className="w-3.5 h-3.5" /> : <Sun className="w-3.5 h-3.5" />}
        {theme === "dark" ? "Dark" : "Light"} mode
      </span>
      <span
        aria-hidden="true"
        className="relative rounded-full flex-shrink-0"
        style={{ width: 28, height: 16, backgroundColor: theme === "dark" ? "var(--pr-authority-blue)" : "var(--pr-overlay-10)" }}
      >
        <span
          className="absolute rounded-full transition-all"
          style={{
            width: 12, height: 12, top: 2, backgroundColor: "#fff",
            left: theme === "dark" ? 14 : 2,
            transitionDuration: "var(--pr-motion-fast)",
          }}
        />
      </span>
    </button>
  );
}

function CurrentUserWidget({ collapsed }: { collapsed: boolean }) {
  const { user, logout } = useAuth();

  if (!user) {
    if (collapsed) {
      return (
        <Tooltip>
          <TooltipTrigger asChild>
            <Link
              to="/login"
              aria-label="Sign in"
              className="p-2 rounded-lg flex items-center justify-center"
              style={{ color: "var(--pr-text-muted)" }}
            >
              <LogOut className="w-4 h-4" style={{ transform: "scaleX(-1)" }} />
            </Link>
          </TooltipTrigger>
          <TooltipContent side="right">Sign in</TooltipContent>
        </Tooltip>
      );
    }
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

  if (collapsed) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={() => logout()}
            aria-label={`Sign out (${user.name})`}
            className="p-2 rounded-lg"
            style={{ color: "var(--pr-text-disabled)" }}
          >
            <LogOut className="w-4 h-4" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="right">Sign out ({user.name})</TooltipContent>
      </Tooltip>
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

// Product Experience V3.2, Part D: replays .pr-enter's fade-and-rise on
// every route change without unmounting Outlet's subtree. Toggling the
// class off then back on (rather than leaving it on permanently) is
// necessary: a CSS animation only plays once per class application, so
// simply keeping "pr-enter" in className would animate the very first
// page load and then never again. Forcing a reflow (`offsetHeight`)
// between the removal and the re-add is the standard way to make the
// browser actually notice the class left and came back, rather than
// coalescing both changes into one no-op paint.
function PageTransition({ pathname, children }: { pathname: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.classList.remove("pr-enter");
    void el.offsetHeight;
    el.classList.add("pr-enter");
  }, [pathname]);

  return (
    <div ref={ref} className="pr-enter">
      {children}
    </div>
  );
}

function LayoutInner() {
  const location = useLocation();
  const isMobile = useIsMobile();
  const [drawerOpen, setDrawerOpen] = useState(false);
  // Product Experience V3.2, section 5: initialized synchronously from
  // localStorage (not in an effect) so the sidebar never visibly flashes
  // expanded-then-collapses on a reload for a user who collapsed it last
  // session -- the same "read before first paint" discipline lib/theme.ts
  // already established for the theme preference.
  const [collapsed, setCollapsed] = useState<boolean>(() => getSidebarCollapsed());

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev;
      setSidebarCollapsed(next);
      return next;
    });
  }

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
      {/* Live-QA fix: the skip link must be the first focusable element in
          the document so a keyboard user can bypass the banner and nav
          before reaching it, per its own purpose. It previously sat after
          DemoBanner in DOM order, so on the live demo the very first Tab
          stop was the banner's "Start Guided Demo" button instead. The
          link is position:absolute (theme.css .pr-skip-link), so moving
          it here changes only tab/DOM order, not visual layout. */}
      <a href="#pr-main-content" className="pr-skip-link">
        Skip to main content
      </a>
      {DEMO_MODE && <DemoBanner />}
      <div className="flex flex-1 min-h-0" style={{ backgroundColor: "var(--pr-bg-primary)" }}>
      {/* Sidebar (desktop). Section 12: collapse is a desktop-only
          concept -- isMobile already routes to a completely separate
          Sheet drawer below, so a collapsed preference set on desktop
          can never reach, or break, the mobile pattern. Section 56:
          width is the one thing that animates; flex layout already
          reflows the content area to match without its own separate
          transition. */}
      {!isMobile && (
        <aside
          className="flex-shrink-0 flex flex-col border-r overflow-hidden"
          style={{
            width: collapsed ? "var(--pr-sidebar-width-collapsed)" : "var(--pr-sidebar-width-expanded)",
            transitionProperty: "width",
            transitionDuration: "var(--pr-motion-base)",
            transitionTimingFunction: "var(--pr-motion-ease)",
            backgroundColor: "var(--pr-bg-secondary)",
            borderColor: "var(--pr-overlay-05)",
          }}
        >
          <SidebarBody collapsed={collapsed} onToggleCollapsed={toggleCollapsed} />
        </aside>
      )}

      {/* Sidebar (mobile drawer): always fully expanded, its own
          separate pattern, entirely unaffected by desktop collapse
          state (section 12). */}
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
            <SidebarBody collapsed={false} onNavigate={() => setDrawerOpen(false)} />
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
          {/* Product Experience V3.2, Part D: a route change gets a
              small, deliberate entrance rather than an abrupt cut --
              main content only, the sidebar next to it never moves.
              Deliberately NOT a React `key` remount: that would tear
              down and rebuild whatever Outlet renders on every
              navigation, resetting a route component's own state even
              between two params of the same route (e.g. one Runtime
              Policy to another) -- a behavioural change this milestone
              has no reason to make. Instead the animation class itself
              is replayed in place via PageTransition below, which never
              unmounts Outlet's subtree. */}
          <PageTransition pathname={location.pathname}>
            <Outlet />
          </PageTransition>
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
