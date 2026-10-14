import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { decisionIntelligenceApi } from "./api";
import { CaseStatusBadge } from "./components/StatusBadges";
import { describeApiError } from "../live/format";
import { useResourceSync } from "../services/resourceSync";
import type { Case, Pattern, Question } from "./types";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Select } from "../components/ui/select";
import { PageHeader } from "../components/ui/page-header";
import { EmptyState } from "../components/ui/empty-state";
import { Skeleton } from "../components/ui/skeleton";
import { HelpCircle, ListTree } from "lucide-react";

function JsonBlock({ value }: { value: unknown }) {
  if (value === null || value === undefined || (typeof value === "object" && Object.keys(value as object).length === 0)) {
    return <span style={{ fontStyle: "italic", color: "var(--pr-text-disabled)" }}>None recorded</span>;
  }
  return (
    <pre
      className="text-xs p-2 rounded-lg overflow-x-auto"
      style={{ backgroundColor: "var(--pr-overlay-04)", color: "var(--pr-text-secondary)", fontFamily: "monospace" }}
    >
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

// Neither Patterns nor Questions expose a reverse "which of these
// reference this case" endpoint -- each only reads forward (a
// Question's own case_ids, or, since this feature's own fix-forward
// commit, a Pattern's own GET .../cases). This page resolves "linked
// to THIS case" the only way the real API allows: list the workflow's
// own patterns/questions (both deliberately meant to be small, curated
// sets by this product's own design) and check each one's own case
// list. Capped to bound the number of requests this makes.
const MAX_TO_CHECK = 50;

export function CaseDetailPage() {
  const { workflowId, caseId } = useParams();
  const [theCase, setTheCase] = useState<Case | null>(null);
  const [linkedQuestions, setLinkedQuestions] = useState<Question[] | null>(null);
  const [linkedPatterns, setLinkedPatterns] = useState<Pattern[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState("");
  const [outcome, setOutcome] = useState("");
  const [outcomeEvidence, setOutcomeEvidence] = useState("");
  const [escalationReason, setEscalationReason] = useState("");
  const [saving, setSaving] = useState(false);

  function load() {
    if (!caseId) return;
    setLoadError(null);
    decisionIntelligenceApi
      .getCase(caseId)
      .then((c) => {
        setTheCase(c);
        setStatus(c.status);
        setOutcome(c.outcome ?? "");
        setOutcomeEvidence(c.outcome_evidence ?? "");
        setEscalationReason(c.escalation_reason ?? "");
      })
      .catch((e) => setLoadError(describeApiError(e, "Loading case")));
  }

  useEffect(load, [caseId]);
  useResourceSync(["decision-intelligence"], load);

  useEffect(() => {
    if (!workflowId || !caseId) return;
    decisionIntelligenceApi
      .listQuestions({ workflow_id: workflowId, limit: MAX_TO_CHECK })
      .then((page) =>
        Promise.all(page.questions.map((q) => decisionIntelligenceApi.getQuestion(q.id).catch(() => null)))
      )
      .then((details) => {
        const matches = details
          .filter((d): d is NonNullable<typeof d> => d !== null && d.case_ids.includes(caseId))
          .map((d) => d.question);
        setLinkedQuestions(matches);
      })
      .catch(() => setLinkedQuestions([]));
  }, [workflowId, caseId]);

  useEffect(() => {
    if (!workflowId || !caseId) return;
    decisionIntelligenceApi
      .listPatterns({ workflow_id: workflowId, limit: MAX_TO_CHECK })
      .then((page) =>
        Promise.all(
          page.patterns.map((p) =>
            decisionIntelligenceApi
              .listPatternCases(p.id)
              .then((caseIds) => (caseIds.includes(caseId) ? p : null))
              .catch(() => null)
          )
        )
      )
      .then((matches) => setLinkedPatterns(matches.filter((p): p is NonNullable<typeof p> => p !== null)))
      .catch(() => setLinkedPatterns([]));
  }, [workflowId, caseId]);

  async function handleSave() {
    if (!theCase) return;
    setSaving(true);
    setMessage(null);
    try {
      const updated = await decisionIntelligenceApi.updateCase(theCase.id, {
        status,
        outcome: outcome || undefined,
        outcome_evidence: outcomeEvidence || undefined,
        escalation_reason: escalationReason || undefined,
      });
      setTheCase(updated);
      setEditing(false);
    } catch (e) {
      setMessage(describeApiError(e, "Update case"));
    } finally {
      setSaving(false);
    }
  }

  if (!theCase && loadError) {
    return (
      <div className="p-8">
        <Alert severity="error" className="text-sm">
          <div className="flex items-center gap-3">
            <span>{loadError}</span>
            <Button variant="ghost" size="sm" onClick={load}>Retry</Button>
          </div>
        </Alert>
      </div>
    );
  }

  if (!theCase) {
    return (
      <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
        <Skeleton height={16} width={160} style={{ marginBottom: 24 }} />
        <Skeleton height={28} width="40%" style={{ marginBottom: 16 }} />
        <Skeleton height={140} style={{ marginBottom: 16 }} />
        <Skeleton height={140} />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-4xl" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <Link to={`/decision-intelligence/workflows/${workflowId}/cases`} style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>
        &lt; Back to Cases
      </Link>
      <PageHeader
        title={theCase.external_ref || `Case ${theCase.id.slice(0, 8)}`}
        status={<CaseStatusBadge status={theCase.status} />}
        secondaryAction={!editing && <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>Edit</Button>}
      />

      {message && <Alert severity="error" className="text-sm mb-4">{message}</Alert>}

      {editing ? (
        <Card className="mb-6">
          <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>Edit case</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Status</label>
              <Select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              >
                <option value="open">Open</option>
                <option value="resolved">Resolved</option>
                <option value="escalated">Escalated</option>
              </Select>
            </div>
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Outcome</label>
              <input
                value={outcome}
                onChange={(e) => setOutcome(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
            </div>
            <div className="sm:col-span-2">
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Outcome evidence</label>
              <input
                value={outcomeEvidence}
                onChange={(e) => setOutcomeEvidence(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
            </div>
            <div className="sm:col-span-2">
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Escalation reason</label>
              <input
                value={escalationReason}
                onChange={(e) => setEscalationReason(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={handleSave} disabled={saving} pending={saving}>{saving ? "Saving..." : "Save changes"}</Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <Card>
            <h2 className="text-sm font-medium mb-2" style={{ color: "var(--pr-text-primary)" }}>Facts</h2>
            <JsonBlock value={theCase.facts} />
          </Card>
          <Card>
            <h2 className="text-sm font-medium mb-2" style={{ color: "var(--pr-text-primary)" }}>Evidence references</h2>
            <JsonBlock value={theCase.evidence_refs} />
          </Card>
          <Card>
            <h2 className="text-sm font-medium mb-2" style={{ color: "var(--pr-text-primary)" }}>AI recommendation</h2>
            <JsonBlock value={theCase.ai_recommendation} />
          </Card>
          <Card>
            <h2 className="text-sm font-medium mb-2" style={{ color: "var(--pr-text-primary)" }}>Human decision</h2>
            <JsonBlock value={theCase.human_decision} />
            <p className="text-xs mt-2" style={{ color: "var(--pr-text-disabled)" }}>
              Kept distinct from the AI recommendation above so a later Replay can compare a proposed rule against what a human actually decided, never the two conflated.
            </p>
          </Card>
          <Card>
            <h2 className="text-sm font-medium mb-2" style={{ color: "var(--pr-text-primary)" }}>Escalation reason</h2>
            <p style={{ fontSize: 13, color: theCase.escalation_reason ? "var(--pr-text-secondary)" : "var(--pr-text-disabled)", fontStyle: theCase.escalation_reason ? "normal" : "italic" }}>
              {theCase.escalation_reason || "Not escalated"}
            </p>
          </Card>
          <Card>
            <h2 className="text-sm font-medium mb-2" style={{ color: "var(--pr-text-primary)" }}>Outcome</h2>
            <p style={{ fontSize: 13, color: theCase.outcome ? "var(--pr-text-secondary)" : "var(--pr-text-disabled)", fontStyle: theCase.outcome ? "normal" : "italic" }}>
              {theCase.outcome || "No recorded outcome"}
            </p>
            {theCase.outcome_evidence && (
              <p className="mt-1" style={{ fontSize: 12, color: "var(--pr-text-muted)" }}>{theCase.outcome_evidence}</p>
            )}
          </Card>
        </div>
      )}

      <Card className="mb-6">
        <div className="flex items-center gap-1.5 mb-3">
          <h2 className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>Linked priority questions</h2>
        </div>
        {linkedQuestions === null && <p style={{ fontSize: 13, color: "var(--pr-text-muted)" }}>Checking linked questions...</p>}
        {linkedQuestions?.length === 0 && (
          <EmptyState icon={HelpCircle} title="No priority questions cite this case yet" description="A reviewer can link this case as evidence from the question's own detail page." />
        )}
        {linkedQuestions?.map((q) => (
          <div key={q.id} className="py-1.5" style={{ borderTop: "1px solid var(--pr-overlay-05)", fontSize: 13 }}>
            <Link to={`/decision-intelligence/workflows/${workflowId}/questions/${q.id}`} style={{ color: "var(--pr-authority-blue)" }}>
              {q.title}
            </Link>
          </div>
        ))}
      </Card>

      <Card>
        <div className="flex items-center gap-1.5 mb-3">
          <h2 className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>Linked patterns</h2>
        </div>
        {linkedPatterns === null && <p style={{ fontSize: 13, color: "var(--pr-text-muted)" }}>Checking linked patterns...</p>}
        {linkedPatterns?.length === 0 && (
          <EmptyState icon={ListTree} title="No pattern cites this case yet" description="A reviewer can link this case as evidence from the pattern's own detail page." />
        )}
        {linkedPatterns?.map((p) => (
          <div key={p.id} className="py-1.5" style={{ borderTop: "1px solid var(--pr-overlay-05)", fontSize: 13 }}>
            <Link to={`/decision-intelligence/workflows/${workflowId}/patterns/${p.id}`} style={{ color: "var(--pr-authority-blue)" }}>
              {p.name}
            </Link>
          </div>
        ))}
      </Card>
    </div>
  );
}
