import { Bot, FlaskConical, ShieldCheck, Building2 } from "lucide-react";
import { PrototypeShell } from "../PrototypeShell";
import { PageHeader } from "../../components/ui/page-header";
import { Card } from "../../components/ui/card";
import { StatusBadge } from "../../components/ui/status-badge";
import { AgentIdentity } from "../../components/ui/agent-identity";
import { AuthorityChain } from "../../components/ui/authority-chain";
import { DecisionOutcomeBadge } from "../../components/ui/decision-outcome-badge";
import { EmptyState } from "../../components/ui/empty-state";
import { AGENT_TREASURY_RECON, findDemoAgent } from "../../demo/fixtures/agents";
import { demoDecisions } from "../../demo/fixtures/decisions";
import { demoPrincipals } from "../../demo/fixtures/principals";

// Section 28: deliberately the longest real agent name in the fixture
// set ("Treasury-Reconciliation-Agent"), not a short placeholder;
// this is the actual stress case a long Agent/Action/Resource name
// needs to survive without breaking the header or the chain layout.
const agent = findDemoAgent(AGENT_TREASURY_RECON)!;
const principal = demoPrincipals.find((p) => p.id === agent.acting_for_principal_id);
const decisions = demoDecisions.filter((d) => d.agent_id === AGENT_TREASURY_RECON);

const STATUS_COLOR: Record<string, string> = {
  active: "var(--pr-trust-green)",
  registered: "var(--pr-text-disabled)",
  suspended: "var(--pr-warning-amber)",
  revoked: "var(--pr-critical-red)",
  retired: "var(--pr-text-disabled)",
};

/**
 * Visual System V3 prototype: Agent Detail. Exercises AgentIdentity at
 * "lg" size in a header context, the Authority chain narrowed to this
 * one agent's own delegation, a Decisions list using
 * DecisionOutcomeBadge, and EmptyState for the "no Trusted Connections"
 * case (section 28: missing data, not just the happy path); this
 * fixture agent has none.
 */
export function AgentDetailPrototype() {
  return (
    <PrototypeShell title="Agent Detail">
      <div className="p-8 max-w-4xl mx-auto">
        <PageHeader
          title={agent.name}
          description={`Acting for ${principal?.name ?? "an unresolved principal"}`}
          status={<StatusBadge color={STATUS_COLOR[agent.status]} label={agent.status} />}
        />

        <div className="flex items-center gap-4 mb-6">
          <AgentIdentity name={agent.name} status={agent.status} size="lg" />
          <AuthorityChain
            links={[
              { icon: Bot, label: "Agent", value: agent.name },
              { icon: ShieldCheck, label: "Delegated by", value: principal?.name ?? "Unresolved" },
              { icon: FlaskConical, label: "Environment", value: agent.environment ?? "Not set" },
            ]}
          />
        </div>

        <Card padding={0} className="mb-6">
          <p className="text-sm font-semibold px-5 pt-4 pb-3" style={{ color: "var(--pr-text-primary)" }}>Decisions</p>
          {decisions.length === 0 ? (
            <EmptyState icon={FlaskConical} title="No decisions yet" description="This agent hasn't submitted a request PayReality has evaluated." />
          ) : (
            decisions.map((d) => (
              <div key={d.id} className="flex items-center gap-3 px-5 py-3" style={{ borderTop: "1px solid var(--pr-overlay-05)" }}>
                <div className="min-w-0 flex-1">
                  <p className="text-sm truncate" style={{ color: "var(--pr-text-primary)" }}>
                    {d.action}{d.resource ? ` on ${d.resource}` : ""}
                  </p>
                  <p className="text-xs truncate" style={{ color: "var(--pr-text-muted)" }}>{d.reason}</p>
                </div>
                <DecisionOutcomeBadge outcome={d.outcome} size="sm" />
              </div>
            ))
          )}
        </Card>

        <Card padding={0}>
          <p className="text-sm font-semibold px-5 pt-4 pb-3" style={{ color: "var(--pr-text-primary)" }}>Trusted connections</p>
          <EmptyState
            icon={Building2}
            title="No runtime connection currently allows this agent"
            description="This agent can still act directly, with its own signed request; a Trusted Connection would let a customer-controlled Adapter corroborate what it reports."
          />
        </Card>
      </div>
    </PrototypeShell>
  );
}
