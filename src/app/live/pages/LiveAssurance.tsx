import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router";
import {
  Building2,
  Bot,
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  FileCheck,
  Clock,
  CalendarClock,
  CheckCircle2,
} from "lucide-react";
import { apiClient } from "../apiClient";
import { Card } from "../../components/ui/card";
import { Alert } from "../../components/ui/alert";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import { describeApiError } from "../format";
import { useResourceSync } from "../../services/resourceSync";
import type { AssuranceSummary } from "../types";

// "2h 14m" / "3d 4h" -- the exact granularity section 8's own example
// phrasing calls for ("Oldest review waiting 2h 14m"), not a vague
// relative string.
function formatWaitDuration(fromIso: string, now: number): string {
  const ms = Math.max(0, now - new Date(fromIso).getTime());
  const minutes = Math.floor(ms / 60000);
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const mins = minutes % 60;
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m`;
}

interface Metric {
  icon: typeof Bot;
  label: string;
  value: number;
  total?: number;
  attention: boolean;
}

function MetricCard({ m }: { m: Metric }) {
  const Icon = m.icon;
  const color = m.attention ? "var(--pr-warning-amber)" : "var(--pr-trust-green)";
  return (
    <Card padding={16} borderColor={m.attention ? "var(--pr-warning-amber)" : "var(--pr-overlay-06)"}>
      <div className="w-8 h-8 rounded-lg flex items-center justify-center mb-2" style={{ backgroundColor: `${color}1A` }}>
        <Icon className="w-4 h-4" style={{ color }} />
      </div>
      <div className="text-xl font-semibold mb-0.5" style={{ color: "var(--pr-text-primary)" }}>
        {m.value}
        {m.total !== undefined && <span className="text-sm font-normal" style={{ color: "var(--pr-text-muted)" }}> / {m.total}</span>}
      </div>
      <div className="text-xs" style={{ color: "var(--pr-text-muted)" }}>{m.label}</div>
    </Card>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mb-8">
      <p className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: "var(--pr-text-disabled)" }}>{title}</p>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">{children}</div>
    </div>
  );
}

// Core Product Experience Redesign, section 8: real hierarchy, not
// fourteen flat KPI cards. A "needs attention" callout leads (only the
// items that are actually true render), then the same 14 real,
// server-computed aggregates (assurance_service.py) are grouped into
// the five sections an operator actually reasons in: Agents, Authority
// Health, Human Oversight, Runtime Outcomes, Evidence Integrity. No
// invented Trust/Risk/Compliance score anywhere on this page.
export function LiveAssurance() {
  const [summary, setSummary] = useState<AssuranceSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  function load() {
    setError(null);
    apiClient
      .get<AssuranceSummary>("/v1/assurance/summary")
      .then(setSummary)
      .catch((e) => setError(describeApiError(e, "Loading Assurance")));
  }

  useEffect(load, []);
  useEffect(() => {
    setNow(Date.now());
  }, [summary]);
  // Milestone 14: this rollup depends on agents, policies, and evidence
  // but had no way to learn any of them changed while it stayed mounted.
  useResourceSync(["agents", "policies", "decisions", "evidence"], load);

  const attentionItems: string[] = [];
  if (summary) {
    if (summary.policies_review_due > 0) {
      attentionItems.push(`${summary.policies_review_due} polic${summary.policies_review_due === 1 ? "y requires" : "ies require"} re-attestation`);
    }
    if (summary.policies_authority_expired > 0) {
      attentionItems.push(`${summary.policies_authority_expired} polic${summary.policies_authority_expired === 1 ? "y has" : "ies have"} expired authority`);
    }
    if (summary.pending_review_count > 0 && summary.oldest_pending_review_at) {
      attentionItems.push(`Oldest pending review waiting ${formatWaitDuration(summary.oldest_pending_review_at, now)}`);
    } else if (summary.pending_review_count > 0) {
      attentionItems.push(`${summary.pending_review_count} decision${summary.pending_review_count === 1 ? "" : "s"} awaiting human review`);
    }
    if (summary.evidence_pending > 0) {
      attentionItems.push(`${summary.evidence_pending} evidence record${summary.evidence_pending === 1 ? "" : "s"} pending verification`);
    }
    if (summary.evidence_rejected > 0) {
      attentionItems.push(`${summary.evidence_rejected} evidence record${summary.evidence_rejected === 1 ? "" : "s"} rejected`);
    }
  }

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
          The aggregate posture across every agent, policy, decision, and evidence record in your
          organisation. Every number here is computed server-side -- never a projection.
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

      {!summary && !error && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-10">
          {Array.from({ length: 5 }, (_, i) => (
            <Card key={i} padding={20} borderColor="var(--pr-overlay-06)">
              <Skeleton height={32} width={32} radius={8} style={{ marginBottom: 12 }} />
              <Skeleton height={22} width="60%" style={{ marginBottom: 6 }} />
              <Skeleton height={11} width="80%" />
            </Card>
          ))}
        </div>
      )}

      {summary && (
        <>
          {/* Needs attention: leads the page, but never invents alarm --
              a genuinely clean org sees a calm confirmation, not an
              empty gap where a warning "should" be. */}
          <Card
            padding={16}
            borderColor={attentionItems.length > 0 ? "var(--pr-warning-amber)" : "var(--pr-overlay-06)"}
            className="flex items-start gap-3 mb-8 pr-enter"
          >
            {attentionItems.length > 0 ? (
              <ShieldAlert className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: "var(--pr-warning-amber)" }} />
            ) : (
              <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: "var(--pr-trust-green)" }} />
            )}
            <div>
              <p className="text-sm font-medium mb-1" style={{ color: "var(--pr-text-primary)" }}>
                {attentionItems.length > 0 ? "Needs attention" : "Nothing needs attention right now"}
              </p>
              {attentionItems.length > 0 ? (
                <ul className="text-sm" style={{ color: "var(--pr-text-secondary)" }}>
                  {attentionItems.map((item, i) => <li key={i}>{item}</li>)}
                </ul>
              ) : (
                <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>
                  No policies overdue for review, no expired authority, no evidence pending or rejected.
                </p>
              )}
            </div>
          </Card>

          <Section title="Agents">
            <MetricCard m={{ icon: Bot, label: "Active", value: summary.active_agents, total: summary.total_agents, attention: false }} />
          </Section>

          <Section title="Authority health">
            <MetricCard m={{ icon: FileCheck, label: "Active policies", value: summary.active_policies, attention: summary.active_policies === 0 }} />
            <MetricCard m={{ icon: CalendarClock, label: "Review due", value: summary.policies_review_due, attention: summary.policies_review_due > 0 }} />
            <MetricCard m={{ icon: ShieldAlert, label: "Expired authority", value: summary.policies_authority_expired, attention: summary.policies_authority_expired > 0 }} />
          </Section>

          <Section title="Human oversight">
            <MetricCard m={{ icon: Clock, label: "Pending review", value: summary.pending_review_count, attention: summary.pending_review_count > 0 }} />
            <MetricCard m={{ icon: CheckCircle2, label: "Resolved", value: summary.resolved_review_count, attention: false }} />
          </Section>

          <Section title="Runtime outcomes">
            <MetricCard m={{ icon: ShieldCheck, label: "Within delegated authority", value: summary.allow_count, attention: false }} />
            <MetricCard m={{ icon: ShieldAlert, label: "Escalated to a human", value: summary.human_review_count, attention: false }} />
            <MetricCard m={{ icon: ShieldX, label: "Outside delegated authority", value: summary.deny_count, attention: false }} />
          </Section>

          <Section title="Evidence integrity">
            <MetricCard m={{ icon: ShieldCheck, label: "Verified", value: summary.evidence_verified, total: summary.evidence_total, attention: false }} />
            <MetricCard m={{ icon: Clock, label: "Pending verification", value: summary.evidence_pending, attention: summary.evidence_pending > 0 }} />
            <MetricCard m={{ icon: ShieldX, label: "Rejected", value: summary.evidence_rejected, attention: summary.evidence_rejected > 0 }} />
          </Section>

          <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>
            Verify any individual record, or the full hash chain, on the{" "}
            <Link to="/evidence" style={{ color: "var(--pr-authority-blue)" }}>Evidence page</Link>.
          </p>
        </>
      )}
    </div>
  );
}
