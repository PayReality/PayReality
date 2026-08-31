import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { Moon, Sun, ArrowLeft } from "lucide-react";

/**
 * Visual System V3, section 27/29: the shared chrome every prototype
 * route mounts inside. Not part of the production app shell (Layout.tsx
 * is untouched); these routes are reachable only by direct URL from
 * /_design-system, never linked from the real nav, so a visitor can
 * never land here by accident.
 *
 * The real app already has a working per-browser theme preference
 * (src/app/lib/theme.ts, exposed in Organisation Settings > General):
 * light is the actual default a first-time visitor gets, dark is
 * opt-in; theme.css's own "dark theme is the default" comment describes
 * only the CSS's fallback when no data-theme is set, which never
 * happens in the real app since initTheme() always sets one explicitly
 * before first paint. The toggle here is a prototype-only convenience
 * for flipping between both quickly while reviewing (section 29), built
 * the same way (`document.documentElement.dataset.theme`), not a
 * second, competing theme system.
 */
export function PrototypeShell({ title, children }: { title: string; children: ReactNode }) {
  const [theme, setTheme] = useState<"dark" | "light">(() => (document.documentElement.dataset.theme === "light" ? "light" : "dark"));

  useEffect(() => {
    if (theme === "light") document.documentElement.dataset.theme = "light";
    else delete document.documentElement.dataset.theme;
    return () => {
      delete document.documentElement.dataset.theme;
    };
  }, [theme]);

  return (
    <div style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <div
        className="sticky top-0 z-10 flex items-center justify-between gap-3 px-6 py-3"
        style={{ backgroundColor: "var(--pr-bg-secondary)", borderBottom: "1px solid var(--pr-overlay-08)" }}
      >
        <div className="flex items-center gap-3">
          <Link to="/_design-system" className="inline-flex items-center gap-1.5 text-xs" style={{ color: "var(--pr-text-muted)" }}>
            <ArrowLeft className="w-3.5 h-3.5" /> Visual System V3
          </Link>
          <span style={{ color: "var(--pr-overlay-12)" }}>/</span>
          <span className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>{title}</span>
        </div>
        <button
          type="button"
          aria-label="Toggle theme"
          data-testid="prototype-theme-toggle"
          onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
          className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg"
          style={{ border: "1px solid var(--pr-overlay-10)", color: "var(--pr-text-secondary)" }}
        >
          {theme === "dark" ? <Moon className="w-3.5 h-3.5" /> : <Sun className="w-3.5 h-3.5" />}
          {theme === "dark" ? "Dark" : "Light"}
        </button>
      </div>
      {children}
    </div>
  );
}
