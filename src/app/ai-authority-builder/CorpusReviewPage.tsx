import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { aiAuthorityBuilderApi } from "./api";
import { aiPolicyBuilderApi } from "../ai-policy-builder/api";
import type { Candidate } from "../ai-policy-builder/types";
import { CandidateCard } from "../ai-policy-builder/components/CandidateCard";
import { ConfidenceBadge } from "../ai-policy-builder/components/ConfidenceBadge";
import { AiComingSoonBanner } from "../components/AiComingSoonBanner";
import { HelpIcon } from "../help/HelpIcon";
import { useAuth } from "../auth/AuthContext";
import { agentsApi } from "../agents/api";
import { describeApiError } from "../live/format";
import { ResolvePrincipalDialog } from "./components/ResolvePrincipalDialog";
import { SkeletonRows } from "../components/ui/skeleton";
import type {
  Conflict,
  Corpus,
  Coverage,
  ExplainabilityFields,
  Gap,
  GraphApproval,
  GraphDiff,
  GraphSummary,
  MissingInformationItem,
  Operation,
  Principal,
  Question,
  Relationship,
  Resource,
} from "./types";

// This page is deliberately built like a pull request review, not a
// chat transcript: a fixed decision bar, a tab list of what changed,
// and every claim backed by a citation card a reviewer can expand --
// never a paragraph of prose asking them to trust it.

const rowStyle: React.CSSProperties = {
  padding: "12px 20px",
  borderTop: "1px solid var(--pr-overlay-05)",
  fontSize: 13,
};

const TABS = [
  { id: "graph", label: "Authority Graph" },
  { id: "conflicts", label: "Conflicts" },
  { id: "missing", label: "Missing Information" },
  { id: "coverage", label: "Coverage" },
  { id: "diff", label: "Diff" },
  { id: "history", label: "Approval History" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function Citation({ excerpt, location }: { excerpt: string | null; location: string | null }) {
  if (!excerpt) return null;
  return (
    <p style={{ fontSize: 12, fontStyle: "italic", color: "var(--pr-text-muted)", marginTop: 4 }}>
      "{excerpt}"{location ? ` (${location})` : ""}
    </p>
  );
}

// Task 1/2: every extracted item's full explainability bundle, always
// rendered inline and expandable -- never hidden inside a tooltip a
// reviewer has to know to look for, and never collapsed away by
// default when there's something substantive to see (an assumption or
// an ambiguity flag).
function Explainability({ item }: { item: ExplainabilityFields }) {
  const hasAssumptions = item.detected_assumptions.length > 0;
  const hasAmbiguity = item.ambiguity_flags.length > 0;
  const hasAnything = item.clause_reference || item.extraction_reasoning || hasAssumptions || hasAmbiguity;
  if (!hasAnything) return null;
  return (
    <div
      style={{
        marginTop: 6,
        padding: "8px 10px",
        borderRadius: 6,
        backgroundColor: "var(--pr-bg-hover)",
        fontSize: 12,
      }}
    >
      {item.clause_reference && (
        <div style={{ color: "var(--pr-text-secondary)" }}>
          <strong>Clause:</strong> {item.clause_reference}
        </div>
      )}
      {item.extraction_reasoning && (
        <div style={{ color: "var(--pr-text-secondary)", marginTop: item.clause_reference ? 4 : 0 }}>
          <strong>Reasoning:</strong> {item.extraction_reasoning}
        </div>
      )}
      {hasAssumptions && (
        <div style={{ color: "var(--pr-warning-amber)", marginTop: 4 }}>
          <strong>Assumptions:</strong> {item.detected_assumptions.join("; ")}
        </div>
      )}
      {hasAmbiguity && (
        <div style={{ color: "var(--pr-warning-amber)", marginTop: 4 }}>
          <strong>Ambiguity:</strong> {item.ambiguity_flags.join("; ")}
        </div>
      )}
    </div>
  );
}

function Section({
  title,
  count,
  emptyLabel,
  urgent,
  children,
}: {
  title: string;
  count: number | null;
  emptyLabel: string;
  urgent?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);
  const contentId = `section-${title.toLowerCase().replace(/\s+/g, "-")}`;
  const isUrgent = !!urgent;
  return (
    <div
      style={{
        backgroundColor: "var(--pr-bg-card)",
        border: "1px solid var(--pr-overlay-05)",
        borderRadius: 12,
        marginBottom: 16,
        overflow: "hidden",
        borderLeft: isUrgent ? "3px solid var(--pr-warning-amber)" : undefined,
      }}
    >
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={contentId}
        className="w-full flex items-center justify-between"
        style={{ padding: "16px 20px", textAlign: "left" }}
      >
        <span style={{ fontSize: 14, fontWeight: 500, color: isUrgent ? "var(--pr-warning-amber)" : "var(--pr-text-primary)" }}>
          {title} ({count ?? "…"})
        </span>
        <span style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>{open ? "Hide" : "Show"}</span>
      </button>
      {open && (
        <div id={contentId}>
          {count === null ? (
            <div style={rowStyle}>
              <SkeletonRows count={2} height={16} />
            </div>
          ) : count === 0 ? (
            <p style={{ ...rowStyle, color: "var(--pr-text-muted)" }}>{emptyLabel}</p>
          ) : (
            children
          )}
        </div>
      )}
    </div>
  );
}

const CONFLICT_TYPE_LABEL: Record<string, string> = {
  authority: "Authority conflict",
  threshold: "Threshold conflict",
  role: "Role conflict",
  policy: "Policy conflict",
  delegation: "Delegation conflict",
  circular_delegation: "Circular delegation",
};

function ConflictTypeBadge({ type }: { type: string | null }) {
  if (!type) return null;
  const critical = type === "circular_delegation";
  return (
    <span
      style={{
        fontSize: 11,
        textTransform: "uppercase",
        padding: "2px 8px",
        borderRadius: 99,
        color: critical ? "var(--pr-critical-red)" : "var(--pr-warning-amber)",
        backgroundColor: critical ? "rgba(239,68,68,0.1)" : "rgba(245,158,11,0.1)",
        whiteSpace: "nowrap",
      }}
    >
      {CONFLICT_TYPE_LABEL[type] ?? type}
    </span>
  );
}

export function AIAuthorityBuilderCorpusReviewPage() {
  const { corpusId } = useParams();
  const { user, hasPermission } = useAuth();
  const [tab, setTab] = useState<TabId>("graph");
  const [corpus, setCorpus] = useState<Corpus | null>(null);
  const [summary, setSummary] = useState<GraphSummary | null>(null);
  const [policies, setPolicies] = useState<Candidate[] | null>(null);
  const [principals, setPrincipals] = useState<Principal[] | null>(null);
  const [resources, setResources] = useState<Resource[] | null>(null);
  const [operations, setOperations] = useState<Operation[] | null>(null);
  const [relationships, setRelationships] = useState<Relationship[] | null>(null);
  const [conflicts, setConflicts] = useState<Conflict[] | null>(null);
  const [gaps, setGaps] = useState<Gap[] | null>(null);
  const [questions, setQuestions] = useState<Question[] | null>(null);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [missingInfo, setMissingInfo] = useState<MissingInformationItem[] | null>(null);
  const [diff, setDiff] = useState<GraphDiff | null>(null);
  const [approvals, setApprovals] = useState<GraphApproval[] | null>(null);
  const [answerDrafts, setAnswerDrafts] = useState<Record<string, string>>({});
  const [answerErrors, setAnswerErrors] = useState<Record<string, string>>({});
  const [answerBusyId, setAnswerBusyId] = useState<string | null>(null);
  const [aiEnabled, setAiEnabled] = useState(true);

  const [approving, setApproving] = useState(false);
  const [approvalReasonDraft, setApprovalReasonDraft] = useState("");
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [showApprovalPrompt, setShowApprovalPrompt] = useState(false);

  // Stage I.2/I.3: same permissive-when-no-session pattern ReviewQueuePage
  // already uses (Operator Key bypass stays fully usable) -- only disable
  // once we positively know a signed-in user lacks the permission.
  const lacksReviewPermission = !!user && !hasPermission("authority.review");

  // AuthorityPrincipal only carries resolved_principal_id (a bare FK), not
  // the resolved Principal's own name -- resolved separately here via the
  // same real Principal list AgentDirectoryPage.tsx already fetches, so
  // "Resolved -> {name}" is correct for principals resolved in an earlier
  // session too, not just ones resolved through this page just now.
  const [resolvedPrincipalNameById, setResolvedPrincipalNameById] = useState<Record<string, string>>({});
  const [resolvingDiscovery, setResolvingDiscovery] = useState<Principal | null>(null);
  const [relationshipBusyId, setRelationshipBusyId] = useState<string | null>(null);
  const [relationshipError, setRelationshipError] = useState<string | null>(null);

  useEffect(() => {
    aiAuthorityBuilderApi.getStatus().then((s) => setAiEnabled(s.ai_enabled));
  }, []);

  // Milestone 14: these 14 fetches used to have no .catch() at all -- any
  // single failing endpoint left its field's state permanently null,
  // which the shared Section component (below) renders identically to
  // "still loading" forever, with no indication anything failed and no
  // way to retry. Each fetch is now attributed to `sectionLoadErrors` so
  // at least one visible signal exists, with a single retry-everything
  // action rather than 14 separate per-field retry buttons.
  const [sectionLoadErrors, setSectionLoadErrors] = useState<string[]>([]);

  function loadAll() {
    if (!corpusId) return;
    setSectionLoadErrors([]);
    function track<T>(label: string, promise: Promise<T>, setter: (v: T) => void) {
      promise.then(setter).catch((e) =>
        setSectionLoadErrors((prev) => [...prev, describeApiError(e, label)])
      );
    }
    track("Corpus", aiAuthorityBuilderApi.getCorpus(corpusId), setCorpus);
    track("Summary", aiAuthorityBuilderApi.getSummary(corpusId), setSummary);
    track("Rules", aiPolicyBuilderApi.listCandidatesForCorpus(corpusId), setPolicies);
    track("Principals", aiAuthorityBuilderApi.getPrincipals(corpusId), setPrincipals);
    track("Resources", aiAuthorityBuilderApi.getResources(corpusId), setResources);
    track("Operations", aiAuthorityBuilderApi.getOperations(corpusId), setOperations);
    track("Relationships", aiAuthorityBuilderApi.getRelationships(corpusId), setRelationships);
    track("Conflicts", aiAuthorityBuilderApi.getConflicts(corpusId), setConflicts);
    track("Gaps", aiAuthorityBuilderApi.getGaps(corpusId), setGaps);
    track("Questions", aiAuthorityBuilderApi.getQuestions(corpusId), setQuestions);
    track("Coverage", aiAuthorityBuilderApi.getCoverage(corpusId), setCoverage);
    track("Missing information", aiAuthorityBuilderApi.getMissingInformation(corpusId), setMissingInfo);
    track("Diff", aiAuthorityBuilderApi.getDiff(corpusId), setDiff);
    track("Approval history", aiAuthorityBuilderApi.getApprovals(corpusId), setApprovals);
    agentsApi
      .listPrincipals()
      .then((list) => {
        setResolvedPrincipalNameById(Object.fromEntries(list.map((p) => [p.id, p.name])));
      })
      .catch((e) => setSectionLoadErrors((prev) => [...prev, describeApiError(e, "Principal names")]));
  }

  useEffect(loadAll, [corpusId]);

  function refreshRelationships() {
    if (!corpusId) return;
    aiAuthorityBuilderApi.getRelationships(corpusId).then(setRelationships);
  }

  async function handleResolveRelationship(relationshipId: string) {
    setRelationshipError(null);
    setRelationshipBusyId(relationshipId);
    try {
      await aiAuthorityBuilderApi.resolveRelationship(relationshipId);
      refreshRelationships();
    } catch (e) {
      setRelationshipError(describeApiError(e, "Resolve relationship"));
    } finally {
      setRelationshipBusyId(null);
    }
  }

  async function handleActivateRelationship(relationshipId: string) {
    setRelationshipError(null);
    setRelationshipBusyId(relationshipId);
    try {
      await aiAuthorityBuilderApi.activateRelationship(relationshipId);
      refreshRelationships();
    } catch (e) {
      setRelationshipError(describeApiError(e, "Activate relationship"));
    } finally {
      setRelationshipBusyId(null);
    }
  }

  async function submitAnswer(questionId: string) {
    const answer = answerDrafts[questionId];
    if (!answer?.trim()) return;
    setAnswerErrors((prev) => ({ ...prev, [questionId]: "" }));
    setAnswerBusyId(questionId);
    try {
      await aiAuthorityBuilderApi.answerQuestion(questionId, answer);
      aiAuthorityBuilderApi.getQuestions(corpusId!).then(setQuestions);
    } catch (e) {
      setAnswerErrors((prev) => ({ ...prev, [questionId]: describeApiError(e, "Save answer") }));
    } finally {
      setAnswerBusyId(null);
    }
  }

  async function handleApprove() {
    if (!corpusId) return;
    setApprovalError(null);
    setApproving(true);
    try {
      await aiAuthorityBuilderApi.approveGraph(corpusId, approvalReasonDraft.trim() || undefined);
      setShowApprovalPrompt(false);
      setApprovalReasonDraft("");
      aiAuthorityBuilderApi.getApprovals(corpusId).then(setApprovals);
    } catch (e) {
      setApprovalError(describeApiError(e, "Approve graph"));
    } finally {
      setApproving(false);
    }
  }

  const unresolvedConflicts = conflicts?.length ?? 0;
  const openQuestions = questions?.filter((q) => !q.answered).length ?? 0;
  const missingCount = missingInfo?.length ?? 0;

  return (
    <div style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      {/* Decision bar: sticky, always visible -- the one place a reviewer
          takes action, kept separate from the tabs below it, the same way
          a PR's merge box is separate from its file diff. */}
      <div
        style={{
          position: "sticky",
          top: 0,
          zIndex: 10,
          backgroundColor: "var(--pr-bg-card)",
          borderBottom: "1px solid var(--pr-overlay-05)",
          padding: "14px 32px",
        }}
      >
        <Link to="/governance/authority-builder" style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>
          &lt; Back to corpora
        </Link>
        <div className="mt-1 flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-1.5">
            <h1 style={{ color: "var(--pr-text-primary)", margin: 0 }}>{corpus?.name ?? "Authority Graph"}</h1>
            <HelpIcon articleId="authority_graph" />
            {coverage && (
              <span style={{ fontSize: 12, color: "var(--pr-text-muted)", marginLeft: 8 }}>
                {coverage.coverage_percent}% coverage
              </span>
            )}
            {unresolvedConflicts > 0 && (
              <span style={{ fontSize: 12, color: "var(--pr-critical-red)", marginLeft: 8 }}>
                {unresolvedConflicts} conflict{unresolvedConflicts === 1 ? "" : "s"}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {approvals && approvals.length > 0 && (
              <span style={{ fontSize: 12, color: "var(--pr-trust-green)" }}>
                Approved v{approvals[0].version} by {approvals[0].reviewer}
              </span>
            )}
            <button
              onClick={() => setShowApprovalPrompt((s) => !s)}
              disabled={lacksReviewPermission}
              title={lacksReviewPermission ? "Requires Reviewer, Governance Administrator, or Organisation Owner" : undefined}
              className="rounded-lg"
              style={{
                backgroundColor: lacksReviewPermission ? "var(--pr-overlay-10)" : "var(--pr-trust-green)",
                color: lacksReviewPermission ? "var(--pr-text-disabled)" : "white",
                fontSize: 13,
                fontWeight: 500,
                padding: "8px 16px",
              }}
            >
              Approve Graph
            </button>
          </div>
        </div>
        {showApprovalPrompt && (
          <div className="flex items-center gap-2 mt-3">
            <input
              aria-label="Approval reason (optional)"
              placeholder="Approval reason (optional)"
              value={approvalReasonDraft}
              onChange={(e) => setApprovalReasonDraft(e.target.value)}
              style={{
                backgroundColor: "var(--pr-bg-hover)",
                border: "1px solid var(--pr-overlay-10)",
                color: "var(--pr-text-primary)",
                borderRadius: 6,
                padding: "6px 8px",
                fontSize: 13,
                flex: 1,
                maxWidth: 480,
              }}
            />
            <button
              onClick={handleApprove}
              disabled={approving}
              style={{ color: "var(--pr-trust-green)", fontSize: 13, fontWeight: 500, padding: "6px 10px" }}
            >
              {approving ? "Recording approval..." : "Confirm approval"}
            </button>
          </div>
        )}
        {approvalError && (
          <p role="alert" style={{ color: "var(--pr-critical-red)", fontSize: 12, marginTop: 6 }}>{approvalError}</p>
        )}

        {/* Tabs */}
        <div className="flex items-center gap-1 mt-4" style={{ borderBottom: "1px solid var(--pr-overlay-05)" }}>
          {TABS.map((t) => {
            const badge =
              t.id === "conflicts" ? unresolvedConflicts
              : t.id === "missing" ? missingCount
              : t.id === "history" ? (approvals?.length ?? 0)
              : null;
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                style={{
                  padding: "8px 14px",
                  fontSize: 13,
                  fontWeight: 500,
                  color: tab === t.id ? "var(--pr-authority-blue)" : "var(--pr-text-muted)",
                  borderBottom: tab === t.id ? "2px solid var(--pr-authority-blue)" : "2px solid transparent",
                }}
              >
                {t.label}
                {badge !== null && badge > 0 ? ` (${badge})` : ""}
              </button>
            );
          })}
        </div>
      </div>

      <div className="p-8 max-w-3xl">
        <p style={{ color: "var(--pr-text-muted)", fontSize: 12, marginBottom: 20 }}>
          Every finding below is a reviewable claim, cited to its source document and location, with the
          model's own reasoning, assumptions, and ambiguity shown alongside it -- never published
          automatically. Only Rules can be promoted into Governance; approving this graph records that a
          human reviewed it, and does not itself promote or activate anything.
        </p>

        {!aiEnabled && <AiComingSoonBanner />}

        {sectionLoadErrors.length > 0 && (
          <div
            role="alert"
            className="flex items-center justify-between gap-3 mb-4"
            style={{
              padding: "10px 14px",
              borderRadius: 10,
              fontSize: 12,
              backgroundColor: "rgba(245,158,11,0.08)",
              color: "var(--pr-warning-amber)",
              border: "1px solid rgba(245,158,11,0.2)",
            }}
          >
            <span>
              {sectionLoadErrors.length} section{sectionLoadErrors.length > 1 ? "s" : ""} failed to load
              ({sectionLoadErrors.join("; ")}). The sections above may be showing stale or empty data.
            </span>
            <button onClick={loadAll} style={{ color: "var(--pr-authority-blue)", fontWeight: 500, flexShrink: 0 }}>
              Retry all
            </button>
          </div>
        )}

        {summary && tab === "graph" && (
          <div
            className="grid grid-cols-4 gap-px mb-6 rounded-xl overflow-hidden"
            style={{ backgroundColor: "var(--pr-overlay-05)" }}
          >
            {[
              ["Rules", summary.policy_count],
              ["Principals", summary.principal_count],
              ["Resources", summary.resource_count],
              ["Operations", summary.operation_count],
              ["Relationships", summary.relationship_count],
              ["Conflicts", summary.conflict_count],
              ["Gaps", summary.gap_count],
              ["Questions", summary.question_count],
            ].map(([label, value]) => (
              <div key={label as string} className="p-4 text-center" style={{ backgroundColor: "var(--pr-bg-card)" }}>
                <div style={{ fontSize: 20, fontWeight: 600, color: "var(--pr-text-primary)" }}>{value}</div>
                <div style={{ fontSize: 11, color: "var(--pr-text-muted)" }}>{label as string}</div>
              </div>
            ))}
          </div>
        )}

        {tab === "graph" && (
          <>
            <Section title="Rules" count={policies?.length ?? null} emptyLabel="No rules were found in this corpus.">
              <div style={{ padding: 20 }}>
                {policies?.map((c) => (
                  <CandidateCard key={c.candidate_id} candidate={c} onChanged={loadAll} />
                ))}
              </div>
            </Section>

            <Section title="Principals" count={principals?.length ?? null} emptyLabel="No principals were found in this corpus.">
              {principals?.map((p) => (
                <div key={p.id} style={rowStyle}>
                  <div className="flex items-center justify-between">
                    <span style={{ color: "var(--pr-text-primary)" }}>
                      {p.name}{p.role ? `, ${p.role}` : ""}{p.reports_to ? ` (reports to ${p.reports_to})` : ""}
                    </span>
                    <div className="flex items-center gap-2">
                      {p.resolved_principal_id ? (
                        <span style={{ fontSize: 12, color: "var(--pr-trust-green)" }}>
                          Resolved &rarr; {resolvedPrincipalNameById[p.resolved_principal_id] ?? p.resolved_principal_id}
                        </span>
                      ) : (
                        <button
                          onClick={() => setResolvingDiscovery(p)}
                          disabled={lacksReviewPermission}
                          title={lacksReviewPermission ? "Requires Reviewer, Governance Administrator, or Organisation Owner" : undefined}
                          className="rounded-lg border"
                          style={{
                            color: lacksReviewPermission ? "var(--pr-text-disabled)" : "var(--pr-authority-blue)",
                            fontSize: 12,
                            padding: "4px 10px",
                            borderColor: lacksReviewPermission ? "var(--pr-overlay-10)" : "var(--pr-authority-blue)",
                            opacity: lacksReviewPermission ? 0.6 : 1,
                          }}
                        >
                          Resolve
                        </button>
                      )}
                      <ConfidenceBadge confidence={p.confidence} />
                    </div>
                  </div>
                  <Citation excerpt={p.source_excerpt} location={p.source_location} />
                  <Explainability item={p} />
                </div>
              ))}
            </Section>

            <Section title="Resources" count={resources?.length ?? null} emptyLabel="No resources were found in this corpus.">
              {resources?.map((r) => (
                <div key={r.id} style={rowStyle}>
                  <div className="flex items-center justify-between">
                    <span style={{ color: "var(--pr-text-primary)" }}>
                      {r.name}{r.description ? `, ${r.description}` : ""}
                    </span>
                    <ConfidenceBadge confidence={r.confidence} />
                  </div>
                  <Citation excerpt={r.source_excerpt} location={r.source_location} />
                  <Explainability item={r} />
                </div>
              ))}
            </Section>

            <Section title="Operations" count={operations?.length ?? null} emptyLabel="No operations were found in this corpus.">
              {operations?.map((o) => (
                <div key={o.id} style={rowStyle}>
                  <div className="flex items-center justify-between">
                    <span style={{ color: "var(--pr-text-primary)" }}>
                      {o.name}{o.description ? `, ${o.description}` : ""}
                    </span>
                    <ConfidenceBadge confidence={o.confidence} />
                  </div>
                  <Citation excerpt={o.source_excerpt} location={o.source_location} />
                  <Explainability item={o} />
                </div>
              ))}
            </Section>

            <Section title="Relationships" count={relationships?.length ?? null} emptyLabel="No delegation, escalation, or inheritance links were found in this corpus.">
              {relationshipError && (
                <p role="alert" style={{ ...rowStyle, color: "var(--pr-critical-red)" }}>{relationshipError}</p>
              )}
              {relationships?.map((r) => {
                const bothResolved = !!r.from_principal_id && !!r.to_principal_id;
                const busy = relationshipBusyId === r.id;
                return (
                  <div key={r.id} style={rowStyle}>
                    <div className="flex items-center justify-between">
                      <span style={{ color: "var(--pr-text-primary)" }}>
                        <span style={{ textTransform: "uppercase", fontSize: 11, color: "var(--pr-authority-blue)", marginRight: 8 }}>
                          {r.kind}
                        </span>
                        {r.from_principal} &rarr; {r.to_principal}
                      </span>
                      <div className="flex items-center gap-2">
                        <span
                          style={{
                            fontSize: 11,
                            textTransform: "uppercase",
                            padding: "2px 8px",
                            borderRadius: 99,
                            color: r.status === "active" ? "var(--pr-trust-green)" : "var(--pr-warning-amber)",
                            backgroundColor: r.status === "active" ? "rgba(34,197,94,0.1)" : "rgba(245,158,11,0.1)",
                          }}
                        >
                          {r.status === "active" ? "Active" : "Proposed"}
                        </span>
                        {r.status !== "active" && !bothResolved && (
                          <button
                            onClick={() => handleResolveRelationship(r.id)}
                            disabled={lacksReviewPermission || busy}
                            title={lacksReviewPermission ? "Requires Reviewer, Governance Administrator, or Organisation Owner" : undefined}
                            className="rounded-lg border"
                            style={{
                              color: lacksReviewPermission ? "var(--pr-text-disabled)" : "var(--pr-authority-blue)",
                              fontSize: 12,
                              padding: "4px 10px",
                              borderColor: lacksReviewPermission ? "var(--pr-overlay-10)" : "var(--pr-authority-blue)",
                              opacity: lacksReviewPermission || busy ? 0.6 : 1,
                            }}
                          >
                            {busy ? "Resolving..." : "Resolve"}
                          </button>
                        )}
                        {r.status !== "active" && bothResolved && (
                          <button
                            onClick={() => handleActivateRelationship(r.id)}
                            disabled={lacksReviewPermission || busy}
                            title={lacksReviewPermission ? "Requires Reviewer, Governance Administrator, or Organisation Owner" : undefined}
                            className="rounded-lg border"
                            style={{
                              color: lacksReviewPermission ? "var(--pr-text-disabled)" : "var(--pr-trust-green)",
                              fontSize: 12,
                              padding: "4px 10px",
                              borderColor: lacksReviewPermission ? "var(--pr-overlay-10)" : "rgba(34,197,94,0.3)",
                              opacity: lacksReviewPermission || busy ? 0.6 : 1,
                            }}
                          >
                            {busy ? "Activating..." : "Activate"}
                          </button>
                        )}
                        <ConfidenceBadge confidence={r.confidence} />
                      </div>
                    </div>
                    {r.description && <p style={{ fontSize: 13, color: "var(--pr-text-secondary)", marginTop: 4 }}>{r.description}</p>}
                    <Citation excerpt={r.source_excerpt} location={r.source_location} />
                    <Explainability item={r} />
                  </div>
                );
              })}
            </Section>

            <Section title="Questions" count={questions?.length ?? null} emptyLabel="No clarification questions were raised for this corpus." urgent={openQuestions > 0}>
              {questions?.map((q) => (
                <div key={q.id} style={rowStyle}>
                  <p style={{ color: "var(--pr-text-primary)" }}>{q.question}</p>
                  {q.context && <p style={{ fontSize: 12, color: "var(--pr-text-muted)", marginTop: 2 }}>{q.context}</p>}
                  {q.answered ? (
                    <p style={{ fontSize: 13, color: "var(--pr-trust-green)", marginTop: 6 }}>Answered: {q.answer}</p>
                  ) : (
                    <div className="flex gap-2 mt-2">
                      <input
                        aria-label={`Answer: ${q.question}`}
                        placeholder="Answer this question"
                        value={answerDrafts[q.id] ?? ""}
                        onChange={(e) => setAnswerDrafts((prev) => ({ ...prev, [q.id]: e.target.value }))}
                        style={{
                          backgroundColor: "var(--pr-bg-hover)",
                          border: "1px solid var(--pr-overlay-10)",
                          color: "var(--pr-text-primary)",
                          borderRadius: 6,
                          padding: "6px 8px",
                          fontSize: 13,
                          flex: 1,
                        }}
                      />
                      <button
                        onClick={() => submitAnswer(q.id)}
                        disabled={answerBusyId === q.id}
                        style={{ color: "var(--pr-authority-blue)", fontSize: 13, padding: "6px 10px", opacity: answerBusyId === q.id ? 0.5 : 1 }}
                      >
                        {answerBusyId === q.id ? "Saving..." : "Save"}
                      </button>
                    </div>
                  )}
                  {answerErrors[q.id] && (
                    <p role="alert" style={{ color: "var(--pr-critical-red)", fontSize: 12, marginTop: 4 }}>{answerErrors[q.id]}</p>
                  )}
                </div>
              ))}
            </Section>
          </>
        )}

        {tab === "conflicts" && (
          <Section
            title="Conflicts"
            count={conflicts?.length ?? null}
            emptyLabel="No contradictory or duplicate authority was found in this corpus."
            urgent={unresolvedConflicts > 0}
          >
            {conflicts?.map((c) => (
              <div key={c.id} style={rowStyle}>
                <div className="flex items-center justify-between gap-2">
                  <span style={{ color: "var(--pr-critical-red)" }}>{c.description}</span>
                  <div className="flex items-center gap-2" style={{ flexShrink: 0 }}>
                    <ConflictTypeBadge type={c.conflict_type} />
                    <ConfidenceBadge confidence={c.confidence} />
                  </div>
                </div>
                {c.reasoning && <p style={{ fontSize: 12, color: "var(--pr-text-muted)", marginTop: 4 }}>{c.reasoning}</p>}
                {c.reviewer_recommendation && (
                  <p style={{ fontSize: 12, color: "var(--pr-warning-amber)", marginTop: 4, fontWeight: 500 }}>
                    Recommendation: {c.reviewer_recommendation}
                  </p>
                )}
              </div>
            ))}
          </Section>
        )}

        {tab === "missing" && (
          <Section
            title="Missing Information"
            count={(gaps?.length ?? 0) + (missingInfo?.length ?? 0) || null}
            emptyLabel="No missing information was detected in this corpus, by the model or by deterministic analysis."
            urgent={missingCount > 0 || (gaps?.length ?? 0) > 0}
          >
            {missingInfo?.map((m, i) => (
              <div key={`code-${i}`} style={rowStyle}>
                <div className="flex items-center justify-between">
                  <span style={{ color: "var(--pr-warning-amber)" }}>{m.description}</span>
                  <span style={{ fontSize: 11, color: "var(--pr-text-muted)", textTransform: "uppercase" }}>
                    {m.category.replace(/_/g, " ")}
                  </span>
                </div>
              </div>
            ))}
            {gaps?.map((g) => (
              <div key={g.id} style={rowStyle}>
                <div className="flex items-center justify-between">
                  <span style={{ color: "var(--pr-warning-amber)" }}>{g.description}</span>
                  <ConfidenceBadge confidence={g.confidence} />
                </div>
                <Citation excerpt={g.source_excerpt} location={g.source_location} />
              </div>
            ))}
          </Section>
        )}

        {tab === "coverage" && (
          <div
            style={{
              backgroundColor: "var(--pr-bg-card)",
              border: "1px solid var(--pr-overlay-05)",
              borderRadius: 12,
              padding: 24,
            }}
          >
            {!coverage ? (
              <SkeletonRows count={3} height={16} />
            ) : (
              <>
                <div style={{ fontSize: 32, fontWeight: 600, color: "var(--pr-text-primary)" }}>
                  {coverage.coverage_percent}%
                </div>
                <p style={{ fontSize: 12, color: "var(--pr-text-muted)", marginBottom: 20 }}>
                  Deterministic parsing coverage -- computed from what the document parser itself
                  could read, never an estimate from the extraction model.
                </p>
                <div className="grid grid-cols-3 gap-4">
                  {[
                    ["Documents processed", coverage.documents_processed],
                    ["Clauses analysed", coverage.clauses_analysed],
                    ["Clauses ignored", coverage.clauses_ignored],
                    ["Tables extracted", coverage.tables_extracted],
                    ["Images skipped", coverage.images_skipped],
                    ["Sections unsupported", coverage.sections_unsupported],
                  ].map(([label, value]) => (
                    <div key={label as string}>
                      <div style={{ fontSize: 18, fontWeight: 600, color: "var(--pr-text-primary)" }}>{value}</div>
                      <div style={{ fontSize: 11, color: "var(--pr-text-muted)" }}>{label as string}</div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        {tab === "diff" && (
          <>
            {!diff ? (
              <SkeletonRows count={3} height={16} />
            ) : (
              [
                { label: "New authorities", items: diff.new_authorities, render: (a: any) => `${a.name}${a.role ? `, ${a.role}` : ""}` },
                { label: "Removed authorities", items: diff.removed_authorities, render: (a: any) => `${a.name}${a.role ? `, ${a.role}` : ""}` },
                { label: "New thresholds", items: diff.new_thresholds, render: (t: any) => `${t.principal} — ${t.action}: ${t.limit ?? "no limit stated"}` },
                { label: "Changed thresholds", items: diff.changed_thresholds, render: (t: any) => `${t.principal} — ${t.action}: ${t.previous_limit ?? "none"} → ${t.new_limit ?? "none"}` },
                { label: "Changed reporting lines", items: diff.changed_reporting_lines, render: (r: any) => `${r.name}: ${r.previous_reports_to ?? "none"} → ${r.new_reports_to ?? "none"}` },
                { label: "Changed responsibilities", items: diff.changed_responsibilities, render: (r: any) => `${r.name}: ${r.previous_role ?? "none"} → ${r.new_role ?? "none"}` },
              ].map(({ label, items, render }) => (
                <Section key={label} title={label} count={items.length} emptyLabel="No change in this category.">
                  {items.map((item: any, i: number) => (
                    <div key={i} style={rowStyle}>
                      <span style={{ color: "var(--pr-text-primary)" }}>{render(item)}</span>
                    </div>
                  ))}
                </Section>
              ))
            )}
          </>
        )}

        {tab === "history" && (
          <Section
            title="Approval History"
            count={approvals?.length ?? null}
            emptyLabel="This corpus's Authority Graph has not been approved yet."
          >
            {approvals?.map((a) => (
              <div key={a.id} style={rowStyle}>
                <div className="flex items-center justify-between">
                  <span style={{ color: "var(--pr-text-primary)" }}>
                    Version {a.version} approved by {a.reviewer}
                  </span>
                  <span style={{ fontSize: 12, color: "var(--pr-text-muted)" }}>
                    {new Date(a.approved_at).toLocaleString()}
                  </span>
                </div>
                {a.approval_reason && (
                  <p style={{ fontSize: 13, color: "var(--pr-text-secondary)", marginTop: 4 }}>{a.approval_reason}</p>
                )}
                <p style={{ fontSize: 11, color: "var(--pr-text-muted)", marginTop: 4, fontFamily: "monospace" }}>
                  {a.graph_hash}
                </p>
              </div>
            ))}
          </Section>
        )}
      </div>

      {resolvingDiscovery && (
        <ResolvePrincipalDialog
          authorityPrincipalId={resolvingDiscovery.id}
          discoveryName={resolvingDiscovery.name}
          discoveryRole={resolvingDiscovery.role}
          onResolved={loadAll}
          onClose={() => setResolvingDiscovery(null)}
        />
      )}
    </div>
  );
}
