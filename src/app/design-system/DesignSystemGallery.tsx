import { Link } from "react-router";
import { LayoutDashboard, Bot, FlaskConical, Building2, FileCheck } from "lucide-react";
import { Card } from "../components/ui/card";

const PROTOTYPES = [
  { path: "/_design-system/overview", icon: LayoutDashboard, title: "Overview", desc: "The whole product's own sequence, as a chain, plus a real-data activity list." },
  { path: "/_design-system/agent-detail", icon: Bot, title: "Agent Detail", desc: "AgentIdentity, a narrowed Authority chain, and the honest empty state for no Trusted Connections." },
  { path: "/_design-system/decision-detail", icon: FlaskConical, title: "Decision Detail", desc: "The three-question model as a chain; Decisions as first-class, not a log row." },
  { path: "/_design-system/integration-detail", icon: Building2, title: "Integration Detail", desc: "System / Trusted Connection / Action Mapping / Runtime Connection as one legible chain." },
  { path: "/_design-system/receipt", icon: FileCheck, title: "Authorization Receipt", desc: "The permanent-record Evidence surface, principle 6." },
];

/**
 * Visual System V3 (this milestone): an index for the five representative
 * prototypes, reachable only by direct URL (never linked from the real
 * app nav in Layout.tsx). Not a shipped product surface: a working
 * gallery for reviewing the new visual language against real demo data,
 * in both themes (each prototype has its own light/dark toggle).
 */
export function DesignSystemGallery() {
  return (
    <div className="p-8 max-w-3xl mx-auto" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <p className="text-xs font-mono uppercase tracking-widest mb-2" style={{ color: "var(--pr-authority-blue)" }}>
        Visual System V3 &middot; Design foundation, not shipped product
      </p>
      <h1 className="mb-2" style={{ color: "var(--pr-text-primary)", fontSize: 28, fontWeight: 600 }}>Prototypes</h1>
      <p className="text-sm mb-8" style={{ color: "var(--pr-text-muted)" }}>
        Five representative pages exercising the new tokens and components against real demo data. See{" "}
        <span style={{ color: "var(--pr-text-secondary)" }}>DESIGN_SYSTEM.md</span> for the full specification.
      </p>
      <div className="grid gap-3">
        {PROTOTYPES.map((p) => {
          const Icon = p.icon;
          return (
            <Link key={p.path} to={p.path}>
              <Card padding={16} className="flex items-center gap-4 hover:opacity-90">
                <div
                  className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                  style={{ backgroundColor: "color-mix(in srgb, var(--pr-authority-blue) 14%, transparent)" }}
                >
                  <Icon className="w-4 h-4" style={{ color: "var(--pr-authority-blue)" }} />
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>{p.title}</p>
                  <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>{p.desc}</p>
                </div>
              </Card>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
