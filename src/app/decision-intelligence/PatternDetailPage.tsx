import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { FileCheck } from "lucide-react";
import { decisionIntelligenceApi } from "./api";
import { PatternReviewStatusBadge } from "./components/StatusBadges";
import { describeApiError, formatStatus } from "../live/format";
import { useResourceSync } from "../services/resourceSync";
import type { Case, Pattern } from "./types";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Select } from "../components/ui/select";
import { ConfirmButton } from "../components/ui/confirm-button";
import { PageHeader } from "../components/ui/page-header";
import { EmptyState } from "../components/ui/empty-state";
import { Skeleton } from "../components/ui/skeleton";

export function PatternDetailPage() {
  const { workflowId, patternId } = useParams();
  const [pattern, setPattern] = useState<Pattern | null>(null);
  const [linkedCases, setLinkedCases] = useState<Case[] | null>(null);
  const [workflowCases, setWorkflowCases] = useState<Case[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [reviewStatus, setReviewStatus] = useState("");
  const [savingReview, setSavingReview] = useState(false);
  const [caseToLink, setCaseToLink] = useState("");
  const [linking, setLinking] = useState(false);

  function load() {
    if (!patternId) return;
    setLoadError(null);
    decisionIntelligenceApi
      .getPattern(patternId)
      .then((p) => {
        setPattern(p);
        setReviewStatus(p.review_status);
      })
      .catch((e) => setLoadError(describeApiError(e, "Loading pattern")));
  }

  function loadLinkedCases() {
    if (!patternId) return;
    decisionIntelligenceApi
      .listPatternCases(patternId)
      .then((caseIds) => Promise.all(caseIds.map((id) => decisionIntelligenceApi.getCase(id).catch(() => null))))
      .then((cases) => setLinkedCases(cases.filter((c): c is Case => c !== null)))
      .catch(() => setLinkedCases([]));
  }

  useEffect(load, [patternId]);
  useEffect(loadLinkedCases, [patternId]);
  useResourceSync(["decision-intelligence"], () => { load(); loadLinkedCases(); });

  useEffect(() => {
    if (!workflowId) return;
    decisionIntelligenceApi.listCases({ workflow_id: workflowId, limit: 200 }).then((p) => setWorkflowCases(p.cases)).catch(() => {});
  }, [workflowId]);

  async function handleUpdateReviewStatus() {
    if (!pattern) return;
    setSavingReview(true);
    setMessage(null);
    try {
      const updated = await decisionIntelligenceApi.updatePattern(pattern.id, { review_status: reviewStatus });
      setPattern(updated);
    } catch (e) {
      setMessage(describeApiError(e, "Update review status"));
    } finally {
      setSavingReview(false);
    }
  }

  async function handleLinkCase() {
    if (!pattern || !caseToLink) return;
    setLinking(true);
    setMessage(null);
    try {
      await decisionIntelligenceApi.linkPatternCase(pattern.id, caseToLink);
      setCaseToLink("");
      loadLinkedCases();
    } catch (e) {
      setMessage(describeApiError(e, "Link case"));
    } finally {
      setLinking(false);
    }
  }

  async function handleUnlinkCase(caseId: string) {
    if (!pattern) return;
    setMessage(null);
    try {
      await decisionIntelligenceApi.unlinkPatternCase(pattern.id, caseId);
      loadLinkedCases();
    } catch (e) {
      setMessage(describeApiError(e, "Unlink case"));
    }
  }

  if (!pattern && loadError) {
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

  if (!pattern) {
    return (
      <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
        <Skeleton height={16} width={160} style={{ marginBottom: 24 }} />
        <Skeleton height={28} width="40%" style={{ marginBottom: 16 }} />
        <Skeleton height={140} />
      </div>
    );
  }

  const linkedCaseIds = new Set((linkedCases ?? []).map((c) => c.id));
  const linkableCases = workflowCases.filter((c) => !linkedCaseIds.has(c.id));

  return (
    <div className="p-8 max-w-3xl" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <Link to={`/decision-intelligence/workflows/${workflowId}/patterns`} style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>
        &lt; Back to Patterns
      </Link>
      <PageHeader title={pattern.name} status={<PatternReviewStatusBadge status={pattern.review_status} />} />

      {message && <Alert severity="error" className="text-sm mb-4">{message}</Alert>}

      <Card className="mb-4">
        <div className="grid grid-cols-2 gap-3 mb-3">
          <div>
            <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Category</p>
            <p style={{ fontSize: 13, color: "var(--pr-text-primary)" }}>{formatStatus(pattern.category)}</p>
          </div>
          <div>
            <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Confidence</p>
            <p style={{ fontSize: 13, color: pattern.confidence ? "var(--pr-text-primary)" : "var(--pr-text-disabled)", fontStyle: pattern.confidence ? "normal" : "italic" }}>
              {pattern.confidence ? formatStatus(pattern.confidence) : "Not set -- a manual judgement, never a fabricated statistic"}
            </p>
          </div>
        </div>
        <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Description</p>
        <p className="mb-3" style={{ fontSize: 13, color: "var(--pr-text-secondary)" }}>{pattern.description}</p>
        <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Proposed explanation</p>
        <p className="mb-3" style={{ fontSize: 13, color: "var(--pr-text-secondary)" }}>{pattern.proposed_explanation}</p>
        {pattern.alternative_explanations && pattern.alternative_explanations.length > 0 && (
          <>
            <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Alternative explanations considered</p>
            <ul className="list-disc list-inside" style={{ fontSize: 13, color: "var(--pr-text-secondary)" }}>
              {pattern.alternative_explanations.map((alt, i) => (
                <li key={i}>{typeof alt === "string" ? alt : JSON.stringify(alt)}</li>
              ))}
            </ul>
          </>
        )}
      </Card>

      <Card className="mb-4">
        <h2 className="text-sm font-medium mb-2" style={{ color: "var(--pr-text-primary)" }}>Review status</h2>
        <div className="flex items-center gap-2">
          <Select
            value={reviewStatus}
            onChange={(e) => setReviewStatus(e.target.value)}
            className="px-3 py-2 rounded-lg border text-sm"
            style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
          >
            <option value="proposed">Proposed</option>
            <option value="reviewed">Reviewed</option>
            <option value="confirmed">Confirmed</option>
            <option value="rejected">Rejected</option>
          </Select>
          <Button
            size="sm"
            disabled={savingReview || reviewStatus === pattern.review_status}
            pending={savingReview}
            onClick={handleUpdateReviewStatus}
          >
            {savingReview ? "Saving..." : "Update"}
          </Button>
        </div>
      </Card>

      <Card>
        <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>Linked cases (evidence)</h2>
        <p className="mb-3" style={{ fontSize: 12, color: "var(--pr-text-disabled)" }}>
          A pattern with no linked cases is an unsupported assertion, not evidence.
        </p>
        {linkedCases === null && <p style={{ fontSize: 13, color: "var(--pr-text-muted)" }}>Loading...</p>}
        {linkedCases?.length === 0 && (
          <EmptyState icon={FileCheck} title="No cases linked yet" description="Link at least one real case to ground this pattern in evidence." />
        )}
        {linkedCases?.map((c) => (
          <div key={c.id} className="flex items-center justify-between py-1.5" style={{ borderTop: "1px solid var(--pr-overlay-05)", fontSize: 13 }}>
            <Link to={`/decision-intelligence/workflows/${workflowId}/cases/${c.id}`} style={{ color: "var(--pr-authority-blue)" }}>
              {c.external_ref || c.id.slice(0, 8)}
            </Link>
            <ConfirmButton size="sm" variant="ghost" confirmLabel="Unlink" onConfirm={() => handleUnlinkCase(c.id)}>
              Unlink
            </ConfirmButton>
          </div>
        ))}

        <div className="flex items-center gap-2 mt-4">
          <Select
            value={caseToLink}
            onChange={(e) => setCaseToLink(e.target.value)}
            aria-label="Select a case to link"
            className="px-3 py-2 rounded-lg border text-sm flex-1"
            style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
          >
            <option value="">Link a case...</option>
            {linkableCases.map((c) => (
              <option key={c.id} value={c.id}>{c.external_ref || c.id.slice(0, 8)}</option>
            ))}
          </Select>
          <Button size="sm" disabled={!caseToLink || linking} pending={linking} onClick={handleLinkCase}>
            {linking ? "Linking..." : "Link"}
          </Button>
        </div>
      </Card>
    </div>
  );
}
