import { useEffect, useState } from "react";
import { Building2, Bot, ShieldCheck, ShieldAlert, ShieldX, FileCheck } from "lucide-react";
import { apiClient } from "../apiClient";
import { Card } from "../../components/ui/card";
import { Alert } from "../../components/ui/alert";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import { describeApiError } from "../format";
import { useResourceSync } from "../../services/resourceSync";
import { policyLifecycleApi } from "../../policy-studio/lifecycleApi";
import type { LiveEvidence } from "../types";

interface EvidencePayload {
  authority_outcome?: "ALLOW" | "DENY" | "HUMAN_REVIEW";
  risk_classification?: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
}

export function LiveAssurance() {
  const [agentTotal, setAgentTotal] = useState(0);
  const [activeAgentTotal, setActiveAgentTotal] = useState(0);
  const [activePolicyCount, setActivePolicyCount] = useState(0);
  const [evidence, setEvidence] = useState<LiveEvidence[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  function load() {
    setError(null);
    // Two separate totals, not a client-side filter over one page: at
    // Phase 9 scale (AGENT_DIRECTORY.md, "10,000+ agents") a single page
    // of /v1/agents no longer represents every agent, so this rollup
    // reads each count directly from the paginated envelope's `total`.
    Promise.all([
      apiClient.get<{ total: number }>("/v1/agents?limit=1"),
      apiClient.get<{ total: number }>("/v1/agents?status=active&limit=1"),
      policyLifecycleApi.dashboard(),
      apiClient.get<LiveEvidence[]>("/v1/evidence"),
    ])
      .then(([agentPage, activeAgentPage, dashboard, e]) => {
        setAgentTotal(agentPage.total);
        setActiveAgentTotal(activeAgentPage.total);
        setActivePolicyCount(dashboard.counts_by_state["active"] ?? 0);
        setEvidence(e);
        setLoaded(true);
      })
      // A 401/403/400 here (an expired session, a missing permission, a
      // stray Operator Key with no Organization Id) is a real,
      // diagnosable cause, not a network outage; describeApiError says
      // which one instead of steering the user toward the wrong fix.
      .catch((e) => setError(describeApiError(e, "Loading Assurance")));
  }

  useEffect(load, []);
  // Milestone 14: this rollup depends on agents, policies, and evidence
  // but had no way to learn any of them changed while it stayed mounted.
  useResourceSync(["agents", "policies", "evidence"], load);

  const activeAgents = activeAgentTotal;

  const outcomeCounts = evidence.reduce(
    (acc, e) => {
      const outcome = (e.payload as EvidencePayload)?.authority_outcome;
      if (outcome) acc[outcome] = (acc[outcome] ?? 0) + 1;
      return acc;
    },
    {} as Record<string, number>
  );

  const verifiedCount = evidence.filter((e) => e.status === "VERIFIED").length;

  const cards = [
    { icon: Bot, label: "Active agents", value: activeAgents, total: agentTotal, color: "var(--pr-authority-blue)" },
    {
      icon: FileCheck,
      label: "Active policies",
      value: activePolicyCount,
      color: activePolicyCount > 0 ? "var(--pr-trust-green)" : "var(--pr-warning-amber)",
    },
    { icon: ShieldCheck, label: "Within delegated authority", value: outcomeCounts.ALLOW ?? 0, color: "var(--pr-trust-green)" },
    { icon: ShieldAlert, label: "Escalated to a human", value: outcomeCounts.HUMAN_REVIEW ?? 0, color: "var(--pr-warning-amber)" },
    { icon: ShieldX, label: "Outside delegated authority", value: outcomeCounts.DENY ?? 0, color: "var(--pr-critical-red)" },
  ];

  return (
    <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <Building2 className="w-5 h-5" style={{ color: "var(--pr-trust-green)" }} />
          <span className="text-xs font-mono uppercase tracking-widest" style={{ color: "var(--pr-trust-green)" }}>
            Assurance
          </span>
        </div>
        <h1 className="mb-2" style={{ color: "var(--pr-text-primary)" }}>Enterprise Assurance</h1>
        <p style={{ color: "var(--pr-text-muted)" }}>
          A live rollup of what has actually been authorized, decided, and evidenced. Every number
          here is pulled directly from your agents, policies, and signed Evidence records.
        </p>
      </div>

      {error && (
        <Alert severity="warning" className="text-sm mb-6">
          <div className="flex items-center gap-3">
            <span>{error}</span>
            <Button variant="ghost" size="sm" onClick={load}>Retry</Button>
          </div>
        </Alert>
      )}

      {!loaded && !error && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-10">
          {Array.from({ length: 5 }, (_, i) => (
            <Card key={i} padding={20} borderColor="var(--pr-overlay-06)">
              <Skeleton height={36} width={36} radius={8} style={{ marginBottom: 12 }} />
              <Skeleton height={24} width="60%" style={{ marginBottom: 6 }} />
              <Skeleton height={12} width="80%" />
            </Card>
          ))}
        </div>
      )}

      {loaded && (
      <>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-10">
        {cards.map((c) => {
          const Icon = c.icon;
          return (
            <Card key={c.label} padding={20} borderColor="var(--pr-overlay-06)">
              <div
                className="w-9 h-9 rounded-lg flex items-center justify-center mb-3"
                style={{ backgroundColor: `${c.color}1A` }}
              >
                <Icon className="w-4 h-4" style={{ color: c.color }} />
              </div>
              <div className="text-2xl font-semibold mb-1" style={{ color: "var(--pr-text-primary)" }}>
                {c.value}
                {c.total !== undefined && (
                  <span className="text-sm font-normal" style={{ color: "var(--pr-text-muted)" }}>
                    {" "}
                    / {c.total}
                  </span>
                )}
              </div>
              <div className="text-xs" style={{ color: "var(--pr-text-muted)" }}>{c.label}</div>
            </Card>
          );
        })}
      </div>

      <Card padding={20} borderColor="var(--pr-overlay-06)" className="flex items-center gap-3">
        <ShieldCheck className="w-4 h-4 flex-shrink-0" style={{ color: "var(--pr-verification-purple)" }} />
        <p className="text-sm" style={{ color: "var(--pr-text-secondary)" }}>
          <strong style={{ color: "var(--pr-text-primary)" }}>{verifiedCount}</strong> of{" "}
          <strong style={{ color: "var(--pr-text-primary)" }}>{evidence.length}</strong> evidence
          records currently carry cryptographic verified status. Verify any individual record on
          the Evidence page.
        </p>
      </Card>
      </>
      )}
    </div>
  );
}
