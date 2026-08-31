import { Building2, ArrowRight, ShieldCheck, Radio, Bot } from "lucide-react";
import { PrototypeShell } from "../PrototypeShell";
import { PageHeader } from "../../components/ui/page-header";
import { Card } from "../../components/ui/card";
import { StatusBadge } from "../../components/ui/status-badge";
import { AuthorityChain } from "../../components/ui/authority-chain";
import { EmptyState } from "../../components/ui/empty-state";
import {
  demoSystems, demoMappings, demoTrustedConnections, demoConnections, demoAllowedAgents, DEMO_SYSTEM_SAP, DEMO_CONNECTION_SAP,
} from "../../demo/fixtures/integrations";

const system = demoSystems.find((s) => s.id === DEMO_SYSTEM_SAP)!;
const mapping = demoMappings.find((m) => m.integration_id === DEMO_SYSTEM_SAP)!;
const connection = demoConnections.find((c) => c.id === DEMO_CONNECTION_SAP)!;
const trustedConnection = demoTrustedConnections.find((t) => t.id === connection.integration_identity_id)!;
const allowedAgents = demoAllowedAgents[DEMO_CONNECTION_SAP] ?? [];

const MAPPING_COLOR: Record<string, string> = { draft: "var(--pr-text-disabled)", validated: "var(--pr-warning-amber)", approved: "var(--pr-trust-green)", retired: "var(--pr-text-disabled)" };
const CONNECTION_COLOR: Record<string, string> = { draft: "var(--pr-text-disabled)", active: "var(--pr-trust-green)", retired: "var(--pr-text-disabled)" };

/**
 * Visual System V3 prototype: Settings -> Integration Detail. Exercises
 * section 16's three-question model applied to the Trusted Integration
 * concepts specifically: System, Action Mapping, Trusted Connection,
 * Runtime Connection, as one AuthorityChain rather than three
 * separate cards each restating the same relationship in prose.
 */
export function IntegrationDetailPrototype() {
  return (
    <PrototypeShell title="Integration Detail">
      <div className="p-8 max-w-4xl mx-auto">
        <PageHeader
          title={system.external_system_label}
          description="What this system's operations mean, and who's allowed to report them."
          breadcrumbs={[{ label: "Integrations", to: "/_design-system" }]}
        />

        <Card padding={24} className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-wide mb-4" style={{ color: "var(--pr-text-muted)" }}>
            How a report from this system reaches an authority decision
          </p>
          <AuthorityChain
            links={[
              { icon: Building2, label: "System", value: system.external_system_label },
              { icon: Radio, label: "Trusted connection", value: trustedConnection.name },
              { icon: ArrowRight, label: "Action mapping", value: `${mapping.source_operation} v${mapping.version}` },
              { icon: Bot, label: "Allowed agents", value: `${allowedAgents.length} named` },
              { icon: ShieldCheck, label: "PayReality decides", value: "Runtime Authority" },
            ]}
          />
        </Card>

        <Card padding={0} className="mb-6">
          <p className="text-sm font-semibold px-5 pt-4 pb-3" style={{ color: "var(--pr-text-primary)" }}>Action mappings</p>
          <div className="flex items-center justify-between gap-3 px-5 py-3" style={{ borderTop: "1px solid var(--pr-overlay-05)" }}>
            <div className="min-w-0">
              <p className="text-sm" style={{ color: "var(--pr-text-primary)" }}>{mapping.source_operation} <span style={{ color: "var(--pr-text-disabled)" }}>v{mapping.version}</span></p>
              <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>means "Update supplier bank details"</p>
            </div>
            <StatusBadge color={MAPPING_COLOR[mapping.status]} label={mapping.status} />
          </div>
        </Card>

        <Card padding={0}>
          <p className="text-sm font-semibold px-5 pt-4 pb-3" style={{ color: "var(--pr-text-primary)" }}>Runtime connections</p>
          <div className="flex items-center justify-between gap-3 px-5 py-3" style={{ borderTop: "1px solid var(--pr-overlay-05)" }}>
            <div className="min-w-0">
              <p className="text-sm" style={{ color: "var(--pr-text-primary)" }}>{connection.environment} <span style={{ color: "var(--pr-text-disabled)" }}>via {trustedConnection.name}</span></p>
              <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>{allowedAgents.map((a) => a.name).join(", ")}</p>
            </div>
            <StatusBadge color={CONNECTION_COLOR[connection.status]} label={connection.status} />
          </div>
        </Card>

        <div className="mt-6">
          <p className="text-sm font-semibold mb-2" style={{ color: "var(--pr-text-primary)" }}>A system with nothing set up yet</p>
          <Card padding={0}>
            <EmptyState
              icon={Building2}
              title="No action mappings yet"
              description="Add one to tell PayReality what an operation in this system means."
            />
          </Card>
        </div>
      </div>
    </PrototypeShell>
  );
}
