import { useEffect, useState } from "react";
import { Link } from "react-router";
import {
  Shield,
  FileText,
  FlaskConical,
  Database,
  Building2,
  ArrowRight,
  Lock,
  ShieldCheck,
  Bot,
  FileCheck,
  CalendarClock,
  CheckCircle2,
} from "lucide-react";
import { apiClient } from "../live/apiClient";
import { decisionsApi } from "../live/decisionsApi";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Skeleton, SkeletonRows } from "../components/ui/skeleton";
import { DecisionOutcomeBadge } from "../components/ui/decision-outcome-badge";
import { AgentIdentity } from "../components/ui/agent-identity";
import { EmptyState } from "../components/ui/empty-state";
import { describeApiError } from "../live/format";
import { useResourceSync } from "../services/resourceSync";
import type { AssuranceSummary, DecisionHistoryItem } from "../live/types";

// Core Product Experience Redesign, section 7 / Visual System V3, section 7:
// the destinations this page hands off to, presented as connected
// operational surfaces, not a numbered wizard. Order still mirrors the
// product's real dependency chain, but nothing here implies a step must
// be completed before the next is usable.
const DESTINATIONS = [
  {
    icon: Shield,
    title: "Agents",
    desc: "The AI agents operating in your enterprise, and the identity each one acts under.",
    path: "/agents",
    color: "var(--pr-authority-blue)",
  },
  {
    icon: FileText,
    title: "Governance",
    desc: "The rules that define what authority has actually been delegated: written by hand or discovered from your documents.",
    path: "/governance",
    color: "var(--pr-evidence-cyan)",
  },
  {
    icon: FlaskConical,
    title: "Decisions",
    desc: "What happened when an agent tried to act: allowed, not allowed, or sent to a human, and why.",
    path: "/decisions",
    color: "var(--pr-warning-amber)",
  },
  {
    icon: Database,
    title: "Evidence",
    desc: "The cryptographically signed record every decision produces. Verify any record's signature independently.",
    path: "/evidence",
    color: "var(--pr-verification-purple)",
  },
  {
    icon: Building2,
    title: "Assurance",
    desc: "The aggregate posture across every agent, policy, decision, and evidence record: a live rollup, not a projection.",
    path: "/assurance",
    color: "var(--pr-trust-green)",
  },
];

export function PlatformOverview() {
  const [summary, setSummary] = useState<AssuranceSummary | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [recent, setRecent] = useState<DecisionHistoryItem[] | null>(null);

  function load() {
    setLoadError(null);
    // Product Experience Remediation Milestone 1 built this real,
    // organisation-scoped aggregate endpoint for Assurance; reused here
    // rather than a second bespoke query, so Overview's numbers are
    // never a second, independently-computed source of truth for the
    // same facts.
    apiClient
      .get<AssuranceSummary>("/v1/assurance/summary")
      // A 401/403/400 here (an expired session, a missing permission, a
      // stray Operator Key with no Organization Id) is a real,
      // diagnosable cause, not a network outage: describeApiError says
      // which one instead of steering the very first thing a user sees
      // toward the wrong fix.
      .catch((e) => {
        setLoadError(describeApiError(e, "Loading the overview"));
        return null;
      })
      .then((s) => setSummary(s));
    // Visual System V3, section 7/8: "what has AI attempted recently"
    // is one of the four questions this page must answer within
    // seconds. Reuses the same GET /v1/decisions/history the Decisions
    // page itself calls, not a second, bespoke recent-activity feed.
    decisionsApi
      .history({ limit: 5 })
      .then((r) => setRecent(r.decisions))
      .catch(() => setRecent([]));
  }

  useEffect(load, []);
  // Milestone 14: this strip depends on agents, policies, decisions, and
  // evidence but had no way to learn any of them changed while it stayed
  // mounted.
  useResourceSync(["agents", "policies", "decisions", "evidence"], load);

  const attentionCount = summary
    ? summary.pending_review_count + summary.policies_review_due + summary.policies_authority_expired
    : 0;

  return (
    <div className="p-8 max-w-5xl mx-auto" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      {/* Hero: kept deliberately (theme.css's own documented exception
          for this page), tightened so it earns the space rather than
          pushing the operating picture below the fold. */}
      <div className="mb-8 pt-6">
        <div className="flex items-center gap-2 mb-3">
          <Shield className="w-4 h-4" style={{ color: "var(--pr-authority-blue)" }} />
          <span className="text-xs font-mono uppercase tracking-widest" style={{ color: "var(--pr-authority-blue)" }}>
            Enterprise AI Authority Infrastructure
          </span>
        </div>
        <h1 className="text-3xl font-bold mb-3" style={{ color: "var(--pr-text-primary)" }}>
          Does this AI agent's action fall within the authority your organization already delegated?
        </h1>
        <p className="text-base max-w-2xl" style={{ color: "var(--pr-text-secondary)" }}>
          Runtime Authority checks every AI action against delegated authority before it executes: not a
          model's judgment call, a rule evaluated the same way every time, fail-closed by default.
        </p>
      </div>

      {loadError && (
        <Alert severity="warning" className="mb-8" icon={<ShieldCheck className="w-4 h-4" />}>
          {loadError}
        </Alert>
      )}

      {/* Tier 1: what needs attention right now. The single highest-
          priority question this page answers, given real weight, not
          one card among six equal ones. */}
      <section className="mb-6">
        {!summary && !loadError && <Skeleton height={72} />}
        {summary && attentionCount > 0 && (
          <Card padding={20} borderColor="var(--pr-warning-amber)">
            <div className="flex items-center gap-3">
              <div
                className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: "rgba(245,158,11,0.12)" }}
              >
                <CalendarClock className="w-5 h-5" style={{ color: "var(--pr-warning-amber)" }} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold" style={{ color: "var(--pr-text-primary)" }}>
                  {attentionCount} item{attentionCount === 1 ? "" : "s"} need{attentionCount === 1 ? "s" : ""} attention
                </p>
                <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>
                  {summary.pending_review_count > 0 && (
                    <Link to="/decisions/queue" style={{ color: "var(--pr-authority-blue)" }}>
                      {summary.pending_review_count} decision{summary.pending_review_count === 1 ? "" : "s"} awaiting human review
                    </Link>
                  )}
                  {summary.pending_review_count > 0 && (summary.policies_review_due + summary.policies_authority_expired) > 0 && " · "}
                  {(summary.policies_review_due + summary.policies_authority_expired) > 0 && (
                    <Link to="/governance/dashboard" style={{ color: "var(--pr-authority-blue)" }}>
                      {summary.policies_review_due + summary.policies_authority_expired} polic{(summary.policies_review_due + summary.policies_authority_expired) === 1 ? "y" : "ies"} needing review
                    </Link>
                  )}
                </p>
              </div>
            </div>
          </Card>
        )}
        {summary && attentionCount === 0 && (
          <Card padding={20} borderColor="var(--pr-overlay-06)">
            <div className="flex items-center gap-3">
              <div
                className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: "rgba(34,197,94,0.1)" }}
              >
                <CheckCircle2 className="w-5 h-5" style={{ color: "var(--pr-trust-green)" }} />
              </div>
              <div>
                <p className="text-sm font-semibold" style={{ color: "var(--pr-text-primary)" }}>Nothing needs attention</p>
                <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>No decisions awaiting review, no policies overdue for re-attestation.</p>
              </div>
            </div>
          </Card>
        )}
      </section>

      {/* Tier 2: what has AI attempted recently. */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold mb-3" style={{ color: "var(--pr-text-primary)" }}>Recent activity</h2>
        <Card padding={0}>
          {recent === null && <div className="p-4"><SkeletonRows count={3} height={16} /></div>}
          {recent && recent.length === 0 && (
            <EmptyState icon={FlaskConical} title="No decisions yet" description="Once an agent attempts an action, it appears here." />
          )}
          {recent && recent.length > 0 && recent.map((d) => (
            <Link
              key={d.id}
              to={`/decisions/${d.id}`}
              className="flex items-center gap-3 px-4 py-2.5 hover:opacity-90"
              style={{ borderTop: "1px solid var(--pr-overlay-05)" }}
            >
              <AgentIdentity name={d.agent_name ?? "Unknown agent"} size="sm" />
              <div className="min-w-0 flex-1">
                <p className="text-sm truncate" style={{ color: "var(--pr-text-primary)" }}>{d.agent_name ?? "Unknown agent"}</p>
                <p className="text-xs truncate" style={{ color: "var(--pr-text-muted)" }}>{d.action}{d.resource ? ` on ${d.resource}` : ""}</p>
              </div>
              <DecisionOutcomeBadge outcome={d.outcome} size="sm" />
            </Link>
          ))}
          {recent && recent.length > 0 && (
            <div className="px-4 py-2.5" style={{ borderTop: "1px solid var(--pr-overlay-05)" }}>
              <Link to="/decisions" className="text-xs" style={{ color: "var(--pr-authority-blue)" }}>View all Decisions &rarr;</Link>
            </div>
          )}
        </Card>
      </section>

      {/* Tier 3: what authority infrastructure is configured. De-emphasized
          relative to tiers 1/2 -- these are configuration facts, not
          things requiring action. */}
      <section className="mb-10">
        <h2 className="text-sm font-semibold mb-3" style={{ color: "var(--pr-text-primary)" }}>Authority infrastructure</h2>
        {!summary && !loadError && (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {Array.from({ length: 3 }, (_, i) => <Skeleton key={i} height={56} />)}
          </div>
        )}
        {summary && (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <Card padding={14} borderColor="var(--pr-overlay-06)">
              <div className="flex items-center gap-2 mb-0.5">
                <Bot className="w-3.5 h-3.5" style={{ color: "var(--pr-text-muted)" }} />
                <span className="text-lg font-semibold" style={{ color: "var(--pr-text-primary)" }}>
                  {summary.active_agents}<span className="text-xs font-normal" style={{ color: "var(--pr-text-muted)" }}> / {summary.total_agents}</span>
                </span>
              </div>
              <Link to="/agents" className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Agents active</Link>
            </Card>
            <Card padding={14} borderColor="var(--pr-overlay-06)">
              <div className="flex items-center gap-2 mb-0.5">
                <FileCheck className="w-3.5 h-3.5" style={{ color: "var(--pr-text-muted)" }} />
                <span className="text-lg font-semibold" style={{ color: "var(--pr-text-primary)" }}>{summary.active_policies}</span>
              </div>
              <Link to="/governance" className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Active policies</Link>
            </Card>
            <Card padding={14} borderColor="var(--pr-overlay-06)">
              <div className="flex items-center gap-2 mb-0.5">
                <ShieldCheck className="w-3.5 h-3.5" style={{ color: "var(--pr-text-muted)" }} />
                <span className="text-lg font-semibold" style={{ color: "var(--pr-text-primary)" }}>
                  {summary.evidence_verified}<span className="text-xs font-normal" style={{ color: "var(--pr-text-muted)" }}> / {summary.evidence_total}</span>
                </span>
              </div>
              <Link to="/evidence" className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Evidence verified</Link>
            </Card>
          </div>
        )}
      </section>

      {/* Destinations */}
      <section>
        <h2 className="text-sm font-semibold mb-1" style={{ color: "var(--pr-text-primary)" }}>Where to go next</h2>
        <p className="text-xs mb-4" style={{ color: "var(--pr-text-muted)" }}>
          Every surface below reads and writes the same underlying authority model.
        </p>
        <div className="grid gap-3">
          {DESTINATIONS.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.title}
                to={item.path}
                className="flex items-start gap-4 p-4 rounded-xl border transition-colors group"
                style={{ borderColor: "var(--pr-overlay-06)", backgroundColor: "var(--pr-bg-card)" }}
              >
                <div
                  className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                  style={{ backgroundColor: `color-mix(in srgb, ${item.color} 12%, transparent)`, border: `1px solid color-mix(in srgb, ${item.color} 30%, transparent)` }}
                >
                  <Icon className="w-4 h-4" style={{ color: item.color }} />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-medium mb-0.5" style={{ color: "var(--pr-text-primary)" }}>
                    {item.title}
                  </h3>
                  <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>{item.desc}</p>
                </div>
                <ArrowRight
                  className="w-4 h-4 flex-shrink-0 mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity"
                  style={{ color: item.color }}
                />
              </Link>
            );
          })}
        </div>
      </section>

      <p className="flex items-center gap-2 mt-8 text-xs" style={{ color: "var(--pr-text-muted)" }}>
        <Lock className="w-3.5 h-3.5" />
        Every decision produces ED25519-signed evidence, verifiable independently of this app.
      </p>
    </div>
  );
}
