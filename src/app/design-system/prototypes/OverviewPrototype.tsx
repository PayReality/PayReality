import { Bot, FlaskConical, ShieldCheck, FileCheck, Building2, ArrowRight } from "lucide-react";
import { PrototypeShell } from "../PrototypeShell";
import { PageHeader } from "../../components/ui/page-header";
import { Card } from "../../components/ui/card";
import { AuthorityChain } from "../../components/ui/authority-chain";
import { DecisionOutcomeBadge } from "../../components/ui/decision-outcome-badge";
import { AgentIdentity } from "../../components/ui/agent-identity";
import { demoDecisions, DECISION_HERO_ADAPTER_REVIEW, DECISION_HERO_ALLOW, DECISION_HERO_DENY } from "../../demo/fixtures/decisions";
import { findDemoAgent } from "../../demo/fixtures/agents";

const RECENT = [DECISION_HERO_ADAPTER_REVIEW, DECISION_HERO_ALLOW, DECISION_HERO_DENY]
  .map((id) => demoDecisions.find((d) => d.id === id))
  .filter((d): d is NonNullable<typeof d> => !!d);

/**
 * Visual System V3 prototype: Overview. Exercises PageHeader, the
 * AuthorityChain sequence as a plain-language explainer of the whole
 * product (section 2's own "who's acting -> attempting what -> what
 * authority -> what decision -> what proves it" sequence), and
 * DecisionOutcomeBadge/AgentIdentity in a compact activity list,
 * using the three real hero decisions (Adapter-mediated HUMAN_REVIEW,
 * agent-direct ALLOW, agent-direct DENY), not placeholder rows.
 */
export function OverviewPrototype() {
  return (
    <PrototypeShell title="Overview">
      <div className="p-8 max-w-5xl mx-auto">
        <PageHeader
          title="Overview"
          description="Every AI-initiated action, checked against organizational authority, before it executes."
        />

        <Card padding={24} className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-wide mb-4" style={{ color: "var(--pr-text-muted)" }}>
            How PayReality reasons about every action
          </p>
          <AuthorityChain
            links={[
              { icon: Bot, label: "Agent", value: "Who is acting" },
              { icon: FlaskConical, label: "Action", value: "What's attempted" },
              { icon: ShieldCheck, label: "Authority", value: "What's delegated" },
              { icon: Building2, label: "Decision", value: "Allow / Deny / Review" },
              { icon: FileCheck, label: "Evidence", value: "What proves it" },
            ]}
          />
        </Card>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <Card padding={16}>
            <p className="text-2xl font-semibold" style={{ color: "var(--pr-text-primary)", fontVariantNumeric: "tabular-nums" }}>9</p>
            <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Agents active</p>
          </Card>
          <Card padding={16}>
            <p className="text-2xl font-semibold" style={{ color: "var(--pr-text-primary)", fontVariantNumeric: "tabular-nums" }}>{demoDecisions.length}</p>
            <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Decisions recorded</p>
          </Card>
          <Card padding={16}>
            <p className="text-2xl font-semibold" style={{ color: "var(--pr-warning-amber)", fontVariantNumeric: "tabular-nums" }}>
              {demoDecisions.filter((d) => d.outcome === "HUMAN_REVIEW" && d.status === "PENDING").length}
            </p>
            <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Awaiting review</p>
          </Card>
          <Card padding={16}>
            <p className="text-2xl font-semibold" style={{ color: "var(--pr-text-primary)", fontVariantNumeric: "tabular-nums" }}>1</p>
            <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Trusted connections</p>
          </Card>
        </div>

        <Card padding={0}>
          <p className="text-sm font-semibold px-5 pt-4 pb-3" style={{ color: "var(--pr-text-primary)" }}>Recent decisions</p>
          {RECENT.map((d) => {
            const agent = findDemoAgent(d.agent_id);
            return (
              <div
                key={d.id}
                className="flex items-center gap-3 px-5 py-3"
                style={{ borderTop: "1px solid var(--pr-overlay-05)" }}
              >
                <AgentIdentity name={agent?.name ?? "Unknown agent"} status={agent?.status} size="sm" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm truncate" style={{ color: "var(--pr-text-primary)" }}>{agent?.name ?? "Unknown agent"}</p>
                  <p className="text-xs truncate" style={{ color: "var(--pr-text-muted)" }}>{d.action}{d.resource ? ` on ${d.resource}` : ""}</p>
                </div>
                {d.integration && (
                  <span className="text-[11px] flex-shrink-0" style={{ color: "var(--pr-evidence-cyan)" }}>via Trusted Adapter</span>
                )}
                <DecisionOutcomeBadge outcome={d.outcome} size="sm" />
                <ArrowRight className="w-3.5 h-3.5 flex-shrink-0" style={{ color: "var(--pr-text-disabled)" }} />
              </div>
            );
          })}
        </Card>
      </div>
    </PrototypeShell>
  );
}
