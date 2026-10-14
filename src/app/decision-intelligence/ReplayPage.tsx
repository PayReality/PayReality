import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { decisionIntelligenceApi } from "./api";
import { OutcomeCategoryBadge, OUTCOME_CATEGORY_LABEL, ReplayRunStatusBadge, outcomeCategoryColor } from "./components/StatusBadges";
import { describeApiError } from "../live/format";
import type { Case, OutcomeCategory, ReplayCaseResult, ReplayRun } from "./types";
import { OUTCOME_CATEGORIES } from "./types";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Select } from "../components/ui/select";
import { PageHeader } from "../components/ui/page-header";
import { Skeleton } from "../components/ui/skeleton";
import { Table, TableHead, TableBody, TableRow, TableHeaderCell, TableCell } from "../components/ui/table";

function decisionLabel(value: Record<string, unknown> | null): string {
  if (!value) return "-";
  if (typeof value.decision === "string") return value.decision;
  return JSON.stringify(value);
}

// Configuration form: picks which cases a replay runs against, either an
// explicit list or a status filter, both of which createReplay (replays.py)
// actually accepts.
function ReplayConfigureForm() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const workflowId = searchParams.get("workflowId") ?? "";
  const ruleVersionId = searchParams.get("ruleVersionId") ?? "";
  const ruleId = searchParams.get("ruleId") ?? "";

  const [cases, setCases] = useState<Case[]>([]);
  const [selectionMode, setSelectionMode] = useState<"all" | "status" | "explicit">("all");
  const [filterStatus, setFilterStatus] = useState("");
  const [selectedCaseIds, setSelectedCaseIds] = useState<Set<string>>(new Set());
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!workflowId) return;
    decisionIntelligenceApi.listCases({ workflow_id: workflowId, limit: 200 }).then((p) => setCases(p.cases)).catch(() => {});
  }, [workflowId]);

  function toggleCase(id: string) {
    setSelectedCaseIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleRun() {
    if (!workflowId || !ruleVersionId) {
      setError("Missing workflow or rule version -- configure a replay from a validated rule's own page.");
      return;
    }
    setRunning(true);
    setError(null);
    try {
      const run = await decisionIntelligenceApi.createReplay({
        workflow_id: workflowId,
        rule_version_id: ruleVersionId,
        case_ids: selectionMode === "explicit" ? Array.from(selectedCaseIds) : undefined,
        filter_status: selectionMode === "status" ? filterStatus || undefined : undefined,
      });
      navigate(`/decision-intelligence/replays/${run.id}`);
    } catch (e) {
      setError(describeApiError(e, "Run replay"));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="p-8 max-w-3xl" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      {ruleId && (
        <Link to={`/decision-intelligence/rules/${ruleId}`} style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>
          &lt; Back to rule
        </Link>
      )}
      <PageHeader
        title="Configure a replay"
        description="Runs this rule version against a chosen set of real historical cases and reports how its proposed decision compares to each case's own recorded baseline. Agreement with that baseline is not a claim that the baseline, or the rule, was correct -- only that they match."
      />

      {!workflowId || !ruleVersionId ? (
        <Alert severity="warning" className="text-sm">
          This page needs a workflow and a validated rule version to configure against -- start from a rule's own detail page instead.
        </Alert>
      ) : (
        <Card>
          <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>Which cases?</h2>
          <div className="flex flex-col gap-2 mb-4">
            <label className="flex items-center gap-1.5 text-sm" style={{ color: "var(--pr-text-secondary)" }}>
              <input type="radio" checked={selectionMode === "all"} onChange={() => setSelectionMode("all")} /> Every case in this workflow
            </label>
            <label className="flex items-center gap-1.5 text-sm" style={{ color: "var(--pr-text-secondary)" }}>
              <input type="radio" checked={selectionMode === "status"} onChange={() => setSelectionMode("status")} /> Cases with a specific status
            </label>
            {selectionMode === "status" && (
              <Select
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value)}
                className="px-3 py-2 rounded-lg border text-sm ml-6"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)", maxWidth: 220 }}
              >
                <option value="">Select a status...</option>
                <option value="open">Open</option>
                <option value="resolved">Resolved</option>
                <option value="escalated">Escalated</option>
              </Select>
            )}
            <label className="flex items-center gap-1.5 text-sm" style={{ color: "var(--pr-text-secondary)" }}>
              <input type="radio" checked={selectionMode === "explicit"} onChange={() => setSelectionMode("explicit")} /> Pick specific cases ({selectedCaseIds.size} selected)
            </label>
            {selectionMode === "explicit" && (
              <div className="ml-6 max-h-56 overflow-y-auto border rounded-lg p-2" style={{ borderColor: "var(--pr-overlay-10)" }}>
                {cases.length === 0 && <p style={{ fontSize: 12, color: "var(--pr-text-disabled)" }}>No cases in this workflow yet.</p>}
                {cases.map((c) => (
                  <label key={c.id} className="flex items-center gap-1.5 text-xs py-1" style={{ color: "var(--pr-text-secondary)" }}>
                    <input type="checkbox" checked={selectedCaseIds.has(c.id)} onChange={() => toggleCase(c.id)} />
                    {c.external_ref || c.id.slice(0, 8)}
                  </label>
                ))}
              </div>
            )}
          </div>
          <Button onClick={handleRun} disabled={running} pending={running}>{running ? "Running replay..." : "Run replay"}</Button>
          {error && <Alert severity="error" className="text-sm mt-3">{error}</Alert>}
        </Card>
      )}
    </div>
  );
}

const PAGE_SIZE = 25;

// Results view: a completed (or in-flight) ReplayRun's summary and
// per-case results. Runs synchronously server-side (replays.py's own
// docstring), so by the time this page can fetch it, `summary` is
// already the real, final aggregate.
function ReplayResultsView({ replayId }: { replayId: string }) {
  const [run, setRun] = useState<ReplayRun | null>(null);
  const [results, setResults] = useState<ReplayCaseResult[] | null>(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);

  function load() {
    setLoadError(null);
    decisionIntelligenceApi.getReplay(replayId).then(setRun).catch((e) => setLoadError(describeApiError(e, "Loading replay")));
  }

  function loadResults() {
    decisionIntelligenceApi
      .listReplayResults(replayId, { limit: PAGE_SIZE, offset })
      .then((p) => {
        setResults(p.results);
        setTotal(p.total);
      })
      .catch(() => setResults([]));
  }

  useEffect(load, [replayId]);
  useEffect(loadResults, [replayId, offset]);

  if (!run && loadError) {
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

  if (!run) {
    return (
      <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
        <Skeleton height={28} width="40%" style={{ marginBottom: 16 }} />
        <Skeleton height={100} style={{ marginBottom: 16 }} />
        <Skeleton height={200} />
      </div>
    );
  }

  const summary = run.summary ?? {};
  const summaryTotal = Object.values(summary).reduce((sum, n) => sum + n, 0);

  return (
    <div className="p-8 max-w-5xl" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <Link to={`/decision-intelligence/workflows/${run.workflow_id}`} style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>
        &lt; Back to workflow
      </Link>
      <PageHeader title="Replay results" status={<ReplayRunStatusBadge status={run.status} />} />

      <Alert severity="neutral" className="text-sm mb-6" style={{ border: "1px solid var(--pr-overlay-10)", padding: 12, borderRadius: 10 }}>
        <strong>Agreement is not correctness.</strong> Every category below measures whether this rule's proposed
        decision matches the human decision already recorded for that case -- it is never a claim that the human
        decision, or the rule, was actually right.
      </Alert>

      <Card className="mb-6">
        <h2 className="text-sm font-medium mb-4" style={{ color: "var(--pr-text-primary)" }}>Summary</h2>
        {summaryTotal === 0 ? (
          <p style={{ fontSize: 13, color: "var(--pr-text-disabled)", fontStyle: "italic" }}>No case results yet.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {/* Real visual weight per category, not a flat list: each row's
                bar width is proportional to its share of this run's cases. */}
            {OUTCOME_CATEGORIES.filter((cat) => (summary[cat] ?? 0) > 0).map((cat) => {
              const count = summary[cat] ?? 0;
              const pct = summaryTotal > 0 ? (count / summaryTotal) * 100 : 0;
              return (
                <div key={cat} className="flex items-center gap-3">
                  <div style={{ width: 170, flexShrink: 0 }}>
                    <OutcomeCategoryBadge category={cat as OutcomeCategory} />
                  </div>
                  <div className="flex-1 rounded-full overflow-hidden" style={{ backgroundColor: "var(--pr-overlay-06)", height: 10 }}>
                    <div style={{ width: `${pct}%`, height: "100%", backgroundColor: outcomeCategoryColor(cat as OutcomeCategory) }} />
                  </div>
                  <span style={{ width: 70, textAlign: "right", fontSize: 13, color: "var(--pr-text-primary)", flexShrink: 0 }}>
                    <strong>{count}</strong> <span style={{ color: "var(--pr-text-muted)" }}>({pct.toFixed(0)}%)</span>
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <Card padding={0} style={{ overflow: "hidden" }}>
        <div className="px-4 pt-4">
          <h2 className="text-sm font-medium mb-1" style={{ color: "var(--pr-text-primary)" }}>Per-case results</h2>
          <p className="mb-3" style={{ fontSize: 12, color: "var(--pr-text-disabled)" }}>Baseline is the human decision already on record; proposed is what this rule's version would have decided.</p>
        </div>
        <div className="overflow-x-auto">
          <Table>
            <TableHead>
              <TableRow style={{ color: "var(--pr-text-muted)", textAlign: "left", fontSize: 12, borderTop: "none", borderBottom: "1px solid var(--pr-overlay-05)" }}>
                <TableHeaderCell>Case</TableHeaderCell>
                <TableHeaderCell>Baseline decision</TableHeaderCell>
                <TableHeaderCell>Proposed decision</TableHeaderCell>
                <TableHeaderCell>Category</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {results === null && (
                <TableRow><TableCell colSpan={4} truncate={false}>Loading...</TableCell></TableRow>
              )}
              {results?.map((r) => (
                <TableRow key={r.id}>
                  <TableCell truncate={false}>
                    <Link to={`/decision-intelligence/workflows/${run.workflow_id}/cases/${r.case_id}`} style={{ color: "var(--pr-authority-blue)" }}>
                      {r.case_id.slice(0, 8)}
                    </Link>
                  </TableCell>
                  <TableCell style={{ color: "var(--pr-text-secondary)" }}>{decisionLabel(r.baseline_decision)}</TableCell>
                  <TableCell style={{ color: "var(--pr-text-secondary)" }}>{decisionLabel(r.proposed_decision)}</TableCell>
                  <TableCell truncate={false}><OutcomeCategoryBadge category={r.outcome_category} /></TableCell>
                </TableRow>
              ))}
              {results?.length === 0 && (
                <TableRow><TableCell colSpan={4} truncate={false}>No results recorded.</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </Card>

      <div className="flex items-center justify-between mt-3" style={{ fontSize: 12, color: "var(--pr-text-muted)" }}>
        <span>{total} case result{total === 1 ? "" : "s"} total</span>
        <div className="flex gap-2">
          <button onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))} disabled={offset === 0} className="px-3 py-1.5 rounded-lg disabled:opacity-30" style={{ backgroundColor: "var(--pr-overlay-05)", color: "var(--pr-text-secondary)" }}>Previous</button>
          <button onClick={() => setOffset((o) => o + PAGE_SIZE)} disabled={offset + PAGE_SIZE >= total} className="px-3 py-1.5 rounded-lg disabled:opacity-30" style={{ backgroundColor: "var(--pr-overlay-05)", color: "var(--pr-text-secondary)" }}>Next</button>
        </div>
      </div>
      <p className="mt-2" style={{ fontSize: 12, color: "var(--pr-text-disabled)" }}>{OUTCOME_CATEGORY_LABEL.agrees_with_baseline} and every other category above describe agreement, never correctness.</p>
    </div>
  );
}

export function ReplayPage() {
  const { replayId } = useParams();
  if (!replayId) return <ReplayConfigureForm />;
  return <ReplayResultsView replayId={replayId} />;
}
