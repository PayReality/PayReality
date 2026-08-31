import { ShieldCheck, Lock } from "lucide-react";
import { PrototypeShell } from "../PrototypeShell";
import { PageHeader } from "../../components/ui/page-header";
import { EvidenceCard } from "../../components/ui/evidence-card";
import { DecisionOutcomeBadge } from "../../components/ui/decision-outcome-badge";
import { AgentIdentity } from "../../components/ui/agent-identity";
import { demoDecisions, DECISION_HERO_ADAPTER_REVIEW } from "../../demo/fixtures/decisions";
import { findDemoAgent } from "../../demo/fixtures/agents";
import { demoSystems, demoTrustedConnections, demoMappings } from "../../demo/fixtures/integrations";

const decision = demoDecisions.find((d) => d.id === DECISION_HERO_ADAPTER_REVIEW)!;
const agent = findDemoAgent(decision.agent_id)!;
const system = demoSystems.find((s) => s.id === decision.integration?.integration_id);
const trustedConnection = demoTrustedConnections.find((t) => t.id === decision.integration?.integration_identity_id);
const mapping = demoMappings.find((m) => m.id === decision.integration?.integration_contract_version_id);

/**
 * Visual System V3 prototype: Authorization Receipt. The clearest test
 * of section 6 ("Evidence should feel permanent"): the whole page is
 * one EvidenceCard, not a stack of ordinary Cards with one Evidence
 * section buried partway down. Deliberately restrained: no ledger/
 * block-chain imagery, one signature-verified indicator, one corner
 * mark, everything else is the same information the real page already
 * shows.
 */
export function ReceiptPrototype() {
  return (
    <PrototypeShell title="Authorization Receipt">
      <div className="p-8 max-w-3xl mx-auto">
        <PageHeader title="Authorization Receipt" breadcrumbs={[{ label: "Decision", to: "/_design-system" }]} />

        <EvidenceCard label="Authorization Receipt" timestamp={new Date(decision.created_at).toLocaleString()} padding={24}>
          <div className="flex items-center justify-between gap-4 mb-4">
            <DecisionOutcomeBadge outcome={decision.outcome} />
            <AgentIdentity name={agent.name} status={agent.status} />
          </div>
          <p className="text-sm mb-4" style={{ color: "var(--pr-text-secondary)" }}>
            {agent.name} requested <strong>{decision.action}</strong>{decision.resource ? <> on <strong>{decision.resource}</strong></> : null}.
          </p>

          <div
            className="flex items-center gap-2 mb-4 pb-4"
            style={{ borderBottom: "1px solid var(--pr-overlay-05)" }}
          >
            <ShieldCheck className="w-4 h-4" style={{ color: "var(--pr-trust-green)" }} />
            <span className="text-sm" style={{ color: "var(--pr-trust-green)" }}>Signature verified, this record has not been altered.</span>
          </div>

          {decision.integration && (
            <div className="grid grid-cols-2 gap-3 text-sm mb-4">
              <div><p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Reported through</p><p style={{ color: "var(--pr-text-primary)" }}>{trustedConnection?.name}</p></div>
              <div><p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>System</p><p style={{ color: "var(--pr-text-primary)" }}>{system?.external_system_label}</p></div>
              <div><p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Mapping</p><p style={{ color: "var(--pr-text-primary)" }}>{mapping?.source_operation}</p></div>
              <div><p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>External operation</p><p className="font-mono" style={{ color: "var(--pr-text-primary)" }}>{decision.integration.external_operation_id}</p></div>
            </div>
          )}

          <p className="text-[11px] flex items-center gap-1.5" style={{ color: "var(--pr-text-disabled)" }}>
            <Lock className="w-3 h-3" />
            This receipt packages the same signed Evidence shown on Decision Detail. It is not a stronger or
            separate proof, and never confirms a downstream action executed.
          </p>
        </EvidenceCard>
      </div>
    </PrototypeShell>
  );
}
