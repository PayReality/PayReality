import type { ComponentType, ReactNode } from "react";

interface EmptyStateProps {
  icon: ComponentType<{ className?: string; style?: React.CSSProperties }>;
  title: string;
  /** What belongs here and why it matters: section 20's own two-part
   * requirement, kept as one prop (a single sentence answers both, a
   * second sentence answering "why" separately reads as padding). */
  description: string;
  action?: ReactNode;
}

/**
 * Visual System V3, section 20: one shared shape for "there is nothing
 * here yet" across Agents, Decisions, Evidence, Integrations, Action
 * Mappings, Runtime Connections, replacing five-plus hand-written
 * per-page versions found in this milestone's audit (AgentDirectoryPage,
 * AgentDetailPage's two, DecisionDetailPage, IntegrationsListPage each
 * built their own). Deliberately quiet: a muted icon, one explanatory
 * sentence, an optional single action, never a marketing banner, never
 * more than one CTA.
 */
export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center text-center py-12 px-6">
      <div
        className="w-10 h-10 rounded-xl flex items-center justify-center mb-3"
        style={{ backgroundColor: "var(--pr-overlay-06)" }}
      >
        <Icon className="w-5 h-5" style={{ color: "var(--pr-text-disabled)" }} />
      </div>
      <p className="text-sm font-medium mb-1" style={{ color: "var(--pr-text-primary)" }}>{title}</p>
      <p className="text-sm max-w-sm" style={{ color: "var(--pr-text-muted)" }}>{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
