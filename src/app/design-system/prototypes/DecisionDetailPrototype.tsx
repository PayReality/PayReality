import { Bot, FlaskConical, ShieldCheck, Building2, FileCheck, Radio } from "lucide-react";
import { PrototypeShell } from "../PrototypeShell";
import { PageHeader } from "../../components/ui/page-header";
import { Card } from "../../components/ui/card";
import { AuthorityChain } from "../../components/ui/authority-chain";
import { DecisionOutcomeBadge } from "../../components/ui/decision-outcome-badge";
import { AgentIdentity } from "../../components/ui/agent-identity";
import { EvidenceCard } from "../../components/ui/evidence-card";
import { demoDecisions, DECISION_HERO_ADAPTER_REVIEW } from "../../demo/fixtures/decisions";
import { findDemoAgent } from "../../demo/fixtures/agents";
import { demoSystems, demoTrustedConnections } from "../../demo/fixtures/integrations";

// Section 28: the Adapter-mediated HUMAN_REVIEW decision, real
// provenance included, deliberately not the plain ALLOW case, since
// that's the one Decision Detail already handles well; this is where a
// distinctive presentation actually earns its place.
const decision = demoDecisions.find((d) => d.id === DECISION_HERO_ADAPTER_REVIEW)!;
const agent = findDemoAgent(decision.agent_id)!;
const system = demoSystems.find((s) => s.id === decision.integration?.integration_id);
const trustedConnection = demoTrustedConnections.find((t) => t.id === decision.integration?.integration_identity_id);

/**
 * Visual System V3 prototype: Decision Detail. The central test of
 * section 7 ("Decisions are first-class... do not make Decision Detail
 * resemble an application log") and section 16 (the three-question
 * model made visually legible): the outcome is the largest thing on the
 * page, the Agent/Trusted Adapter/PayReality distinction is a labeled
 * chain rather than a paragraph, and Evidence gets the distinct
 * permanent-record surface instead of another plain Card.
 */
export function DecisionDetailPrototype() {
  return (
    <PrototypeShell title="Decision Detail">
      <div className="p-8 max-w-4xl mx-auto">
        <PageHeader title="Decision" breadcrumbs={[{ label: "Decisions", to: "/_design-system" }, { label: decision.id.slice(0, 18) + "…" }]} />

        <Card padding={24} className="mb-4">
          <div className="flex items-start justify-between gap-4 mb-4">
            <div>
              <DecisionOutcomeBadge outcome={decision.outcome} />
              <p className="text-sm mt-2" style={{ color: "var(--pr-text-secondary)" }}>{decision.reason}</p>
            </div>
            <AgentIdentity name={agent.name} status={agent.status} />
          </div>

          <div className="pt-4" style={{ borderTop: "1px solid var(--pr-overlay-05)" }}>
            <p className="text-xs font-semibold uppercase tracking-wide mb-3" style={{ color: "var(--pr-text-muted)" }}>
              Three questions, in order
            </p>
            <AuthorityChain
              links={[
                { icon: Bot, label: "Agent: who's acting", value: agent.name },
                { icon: Radio, label: "Trusted Adapter: what's reported", value: trustedConnection?.name ?? "Not applicable (agent-direct)", inactive: !decision.integration },
                { icon: ShieldCheck, label: "PayReality: is it authorized", value: decision.outcome === "ALLOW" ? "Allowed" : decision.outcome === "DENY" ? "Not allowed" : "Needs human approval" },
              ]}
            />
          </div>
        </Card>

        {decision.integration && (
          <Card padding={20} className="mb-4">
            <p className="text-sm font-semibold mb-3" style={{ color: "var(--pr-text-primary)" }}>Reported through a trusted connection</p>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div><p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>System</p><p style={{ color: "var(--pr-text-primary)" }}>{system?.external_system_label}</p></div>
              <div><p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Trusted connection</p><p style={{ color: "var(--pr-text-primary)" }}>{trustedConnection?.name}</p></div>
              <div><p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>External action</p><p style={{ color: "var(--pr-text-primary)" }}>{decision.integration.source_operation}</p></div>
              <div><p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>External operation ID</p><p className="font-mono" style={{ color: "var(--pr-text-primary)" }}>{decision.integration.external_operation_id}</p></div>
            </div>
            <p className="text-[11px] mt-3 pt-3" style={{ color: "var(--pr-text-disabled)", borderTop: "1px solid var(--pr-overlay-05)" }}>
              An authenticated trusted connection attested it observed this operation, not proof the external system actually executed it.
            </p>
          </Card>
        )}

        <EvidenceCard label="Evidence" timestamp={new Date(decision.created_at).toLocaleString()}>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div><p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Action</p><p style={{ color: "var(--pr-text-primary)" }}>{decision.action}</p></div>
            <div><p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Resource</p><p className="truncate" style={{ color: "var(--pr-text-primary)" }}>{decision.resource ?? "Not set"}</p></div>
          </div>
          <p className="text-xs mt-3" style={{ color: "var(--pr-text-muted)" }}>
            <FlaskConical className="w-3 h-3 inline mr-1" style={{ verticalAlign: -2 }} />
            Signed and hash-chained; independently verifiable against PayReality's published key.
          </p>
        </EvidenceCard>
      </div>
    </PrototypeShell>
  );
}
