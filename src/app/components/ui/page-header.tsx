import type { ReactNode } from "react";
import { Link } from "react-router";

interface Breadcrumb {
  label: string;
  to?: string;
}

interface PageHeaderProps {
  title: string;
  /** A short explanatory sentence, section 13: what this page is,
   * never restating the title. Optional: a few pages (Overview) already
   * carry a longer hero sentence of their own and don't need a second. */
  description?: string;
  status?: ReactNode;
  primaryAction?: ReactNode;
  secondaryAction?: ReactNode;
  breadcrumbs?: Breadcrumb[];
}

/**
 * Visual System V3, section 13: one consistent header shape for every
 * "regular" page (the 17 pages theme.css's own h1 rule already targets),
 * replacing the ad hoc flex/heading markup each currently hand-builds.
 * Deliberately compact: a title row plus one optional description
 * line, not the oversized multi-line hero treatment PlatformOverview.tsx
 * keeps for its own, deliberately different, landing-page role (see
 * theme.css's own documented exception for that page). Breadcrumbs are
 * opt-in and expected to be rare: most of this app's navigation is one
 * level deep from the sidebar, so a breadcrumb only earns its place on
 * a genuinely nested page (a mapping inside a System, a version inside
 * a policy).
 */
export function PageHeader({ title, description, status, primaryAction, secondaryAction, breadcrumbs }: PageHeaderProps) {
  return (
    <div className="mb-6">
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 mb-2 text-xs" style={{ color: "var(--pr-text-muted)" }}>
          {breadcrumbs.map((b, i) => (
            <span key={i} className="flex items-center gap-1.5">
              {i > 0 && <span aria-hidden="true">/</span>}
              {b.to ? (
                <Link to={b.to} style={{ color: "var(--pr-text-muted)" }} className="hover:underline">{b.label}</Link>
              ) : (
                <span>{b.label}</span>
              )}
            </span>
          ))}
        </nav>
      )}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5 flex-wrap">
            <h1 style={{ color: "var(--pr-text-primary)" }}>{title}</h1>
            {status}
          </div>
          {description && (
            <p className="text-sm mt-1" style={{ color: "var(--pr-text-muted)" }}>{description}</p>
          )}
        </div>
        {(primaryAction || secondaryAction) && (
          <div className="flex items-center gap-2 flex-shrink-0">
            {secondaryAction}
            {primaryAction}
          </div>
        )}
      </div>
    </div>
  );
}
