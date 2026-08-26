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
  Clock,
  CalendarClock,
} from "lucide-react";
import { apiClient } from "../live/apiClient";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Skeleton } from "../components/ui/skeleton";
import { describeApiError } from "../live/format";
import { useResourceSync } from "../services/resourceSync";
import type { AssuranceSummary } from "../live/types";

// Core Product Experience Redesign, section 7: the destinations this
// page hands off to, presented as connected operational surfaces --
// not a numbered wizard. Order still mirrors the product's real
// dependency chain (an Agent needs Governance to matter; a Decision
// needs both; Evidence and Assurance summarize what already
// happened), but nothing here implies a step must be completed before
// the next is usable.
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
    desc: "The rules that define what authority has actually been delegated -- written by hand or discovered from your documents.",
    path: "/governance",
    color: "var(--pr-evidence-cyan)",
  },
  {
    icon: FlaskConical,
    title: "Decisions",
    desc: "What happened when an agent tried to act: approved, blocked, or sent to a human, and why.",
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
    desc: "The aggregate posture across every agent, policy, decision, and evidence record -- a live rollup, not a projection.",
    path: "/assurance",
    color: "var(--pr-trust-green)",
  },
];

export function PlatformOverview() {
  const [summary, setSummary] = useState<AssuranceSummary | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

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
      // diagnosable cause, not a network outage -- describeApiError says
      // which one instead of steering the very first thing a user sees
      // toward the wrong fix.
      .catch((e) => {
        setLoadError(describeApiError(e, "Loading the overview"));
        return null;
      })
      .then((s) => setSummary(s));
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
      {/* Hero */}
      <div className="mb-14 pt-8">
        <div className="flex items-center gap-2 mb-4">
          <Shield className="w-4 h-4" style={{ color: "var(--pr-authority-blue)" }} />
          <span className="text-xs font-mono uppercase tracking-widest" style={{ color: "var(--pr-authority-blue)" }}>
            Enterprise AI Authority Infrastructure
          </span>
        </div>
        <h1 className="text-4xl font-bold mb-4" style={{ color: "var(--pr-text-primary)" }}>
          Does this AI agent's action fall within the authority your organization already delegated?
        </h1>
        <p className="text-lg max-w-2xl mb-8" style={{ color: "var(--pr-text-secondary)" }}>
          Runtime Authority checks every AI action against the authority your organization has
          already delegated, before it executes. Not a model's judgment call: a rule, evaluated the
          same way every time, fail-closed by default, with evidence you can verify independently.
        </p>
        <div className="flex flex-wrap gap-3">
          <Link
            to="/governance/authority-builder"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium transition-opacity hover:opacity-90"
            style={{ backgroundColor: "var(--pr-authority-blue)", color: "#fff" }}
          >
            See what your organization has already authorized
            <ArrowRight className="w-4 h-4" />
          </Link>
          <Link
            to="/decisions"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium border transition-colors"
            style={{ borderColor: "var(--pr-overlay-12)", color: "var(--pr-text-primary)" }}
          >
            Open Decisions
          </Link>
        </div>
      </div>

      {loadError && (
        <Alert severity="warning" className="mb-10" icon={<ShieldCheck className="w-4 h-4" />}>
          {loadError}
        </Alert>
      )}

      {!summary && !loadError && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-14">
          {Array.from({ length: 5 }, (_, i) => (
            <Card key={i} padding={16} borderColor="var(--pr-overlay-06)">
              <Skeleton height={22} width="50%" style={{ marginBottom: 6 }} />
              <Skeleton height={11} width="80%" />
            </Card>
          ))}
        </div>
      )}

      {/* Orientation strip: what needs a look right now, in real numbers
          only -- section 7's own instruction not to duplicate Assurance
          wholesale. This answers "where should I look," Assurance answers
          "what's the full posture." */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-14">
          <Card padding={16} borderColor="var(--pr-overlay-06)">
            <div className="flex items-center gap-2 mb-1">
              <Bot className="w-3.5 h-3.5" style={{ color: "var(--pr-authority-blue)" }} />
              <span className="text-xl font-semibold" style={{ color: "var(--pr-text-primary)" }}>
                {summary.active_agents}<span className="text-sm font-normal" style={{ color: "var(--pr-text-muted)" }}> / {summary.total_agents}</span>
              </span>
            </div>
            <Link to="/agents" className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Agents active</Link>
          </Card>
          <Card padding={16} borderColor="var(--pr-overlay-06)">
            <div className="flex items-center gap-2 mb-1">
              <FileCheck className="w-3.5 h-3.5" style={{ color: "var(--pr-trust-green)" }} />
              <span className="text-xl font-semibold" style={{ color: "var(--pr-text-primary)" }}>{summary.active_policies}</span>
            </div>
            <Link to="/governance" className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Active policies</Link>
          </Card>
          <Card padding={16} borderColor={summary.pending_review_count > 0 ? "var(--pr-warning-amber)" : "var(--pr-overlay-06)"}>
            <div className="flex items-center gap-2 mb-1">
              <Clock className="w-3.5 h-3.5" style={{ color: summary.pending_review_count > 0 ? "var(--pr-warning-amber)" : "var(--pr-text-muted)" }} />
              <span className="text-xl font-semibold" style={{ color: "var(--pr-text-primary)" }}>{summary.pending_review_count}</span>
            </div>
            <Link to="/decisions/queue" className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Decisions awaiting review</Link>
          </Card>
          <Card padding={16} borderColor="var(--pr-overlay-06)">
            <div className="flex items-center gap-2 mb-1">
              <ShieldCheck className="w-3.5 h-3.5" style={{ color: "var(--pr-verification-purple)" }} />
              <span className="text-xl font-semibold" style={{ color: "var(--pr-text-primary)" }}>
                {summary.evidence_verified}<span className="text-sm font-normal" style={{ color: "var(--pr-text-muted)" }}> / {summary.evidence_total}</span>
              </span>
            </div>
            <Link to="/evidence" className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Evidence verified</Link>
          </Card>
          <Card padding={16} borderColor={attentionCount - summary.pending_review_count > 0 ? "var(--pr-warning-amber)" : "var(--pr-overlay-06)"}>
            <div className="flex items-center gap-2 mb-1">
              <CalendarClock className="w-3.5 h-3.5" style={{ color: (summary.policies_review_due + summary.policies_authority_expired) > 0 ? "var(--pr-warning-amber)" : "var(--pr-text-muted)" }} />
              <span className="text-xl font-semibold" style={{ color: "var(--pr-text-primary)" }}>{summary.policies_review_due + summary.policies_authority_expired}</span>
            </div>
            <Link to="/governance/dashboard" className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Policies needing attention</Link>
          </Card>
        </div>
      )}

      {/* Destinations */}
      <div className="mb-8">
        <h2 className="text-xl font-semibold mb-1" style={{ color: "var(--pr-text-primary)" }}>
          Where to go next
        </h2>
        <p className="text-sm mb-8" style={{ color: "var(--pr-text-muted)" }}>
          Every surface below reads and writes the same underlying authority model -- open whichever one answers your question.
        </p>
      </div>
      <div className="grid gap-4">
        {DESTINATIONS.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.title}
              to={item.path}
              className="flex items-start gap-5 p-6 rounded-xl border transition-colors group"
              style={{ borderColor: "var(--pr-overlay-06)", backgroundColor: "var(--pr-bg-card)" }}
            >
              <div
                className="w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: `${item.color}1A`, border: `1px solid ${item.color}40` }}
              >
                <Icon className="w-5 h-5" style={{ color: item.color }} />
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="font-medium mb-1" style={{ color: "var(--pr-text-primary)" }}>
                  {item.title}
                </h3>
                <p className="text-sm" style={{ color: "var(--pr-text-muted)" }}>{item.desc}</p>
              </div>
              <ArrowRight
                className="w-4 h-4 flex-shrink-0 mt-2 opacity-0 group-hover:opacity-100 transition-opacity"
                style={{ color: item.color }}
              />
            </Link>
          );
        })}
      </div>

      <p className="flex items-center gap-2 mt-8 text-xs" style={{ color: "var(--pr-text-muted)" }}>
        <Lock className="w-3.5 h-3.5" />
        Every decision produces ED25519-signed evidence, verifiable independently of this app.
      </p>
    </div>
  );
}
