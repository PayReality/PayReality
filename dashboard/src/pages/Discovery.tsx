import { useState } from "react"
import { Badge, Button, EmptyPanel, ErrorNote, PageTitle } from "../components/ui"
import { decisionIntelligenceApi } from "../di/api"
import type { AcceptSuggestionResult, DiscoveryRun, DiscoverySuggestion } from "../di/types"
import { useFetch, errorMessage } from "../lib/useAsync"
import { useAuth } from "../auth/AuthContext"
import type { Page } from "../types"

// Feature: AI-assisted discovery review UI. A suggestion from a
// DIDiscoveryRun is NEVER authoritative on its own (di_discovery_service.py's
// own docstring); it only becomes a real Pattern/Question through an
// explicit Accept here. The `.ai-label` badge below is reused everywhere a
// suggestion renders, specifically so a reviewer can never confuse a
// pending suggestion with an accepted, authoritative Pattern/Question
// shown elsewhere in this app (neither Patterns.tsx nor Questions.tsx ever
// renders that badge).

function statusTone(status: DiscoverySuggestion["status"]): string {
  if (status === "accepted") return "success"
  if (status === "dismissed") return "neutral"
  return "warning"
}

function runStatusTone(status: DiscoveryRun["status"]): string {
  if (status === "completed") return "success"
  if (status === "failed") return "warning"
  return "neutral"
}

// The backend's internal provider_used value ("fake"/"claude") is an
// implementation detail, never a user-facing label: "fake" would wrongly
// read as "this analysis is fabricated" when it is real, deterministic
// heuristic analysis; the inverse risk (a reviewer mistaking a real Claude
// call for something more authoritative than a suggestion) matters just as
// much, so both get a plain, accurate, equally-weighted label.
function providerLabel(providerUsed: string): string {
  if (providerUsed === "claude") return "Claude-assisted analysis"
  if (providerUsed === "fake") return "Heuristic analysis (no AI model)"
  return providerUsed
}

export function Discovery({
  workflowId,
  setPage,
  openCase,
}: {
  workflowId: string | null
  setPage: (p: Page) => void
  openCase: (id: string) => void
}) {
  const { hasPermission } = useAuth()
  const canRunDiscovery = hasPermission("di_pattern.manage")
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [detail, setDetail] = useState<{ discovery_run: DiscoveryRun; suggestions: DiscoverySuggestion[] } | null>(null)

  const runs = useFetch(
    () => (workflowId ? decisionIntelligenceApi.listDiscoveryRuns(workflowId, { limit: 100 }) : Promise.resolve(null)),
    [workflowId],
  )

  async function loadRun(runId: string) {
    if (!workflowId) return
    setSelectedRunId(runId)
    try {
      const d = await decisionIntelligenceApi.getDiscoveryRun(workflowId, runId)
      setDetail(d)
    } catch (err) {
      setRunError(errorMessage(err))
    }
  }

  async function runDiscovery() {
    if (!workflowId) return
    setRunning(true)
    setRunError(null)
    try {
      const result = await decisionIntelligenceApi.runDiscovery(workflowId)
      setDetail(result)
      setSelectedRunId(result.discovery_run.id)
      runs.reload()
    } catch (err) {
      setRunError(errorMessage(err))
    } finally {
      setRunning(false)
    }
  }

  function updateSuggestion(id: string, next: DiscoverySuggestion) {
    setDetail((d) => (d ? { ...d, suggestions: d.suggestions.map((s) => (s.id === id ? next : s)) } : d))
  }

  if (!workflowId) {
    return (
      <>
        <PageTitle title="Discovery" description="Let AI propose candidate patterns and questions for a human to review." />
        <EmptyPanel title="No workflow selected" body="Choose or create a workflow first." />
      </>
    )
  }

  return (
    <>
      <PageTitle
        title="Discovery"
        description="AI-assisted discovery proposes candidate patterns and questions from this workflow's cases. Nothing becomes real until a human reviews and accepts it."
        actions={
          canRunDiscovery ? (
            <Button kind="primary" icon="play" onClick={runDiscovery} disabled={running}>
              {running ? "Analysing cases…" : "Discover"}
            </Button>
          ) : undefined
        }
      />
      {!canRunDiscovery && (
        <div className="permission-note" style={{ marginBottom: 16 }}>
          Running discovery requires the <code>di_pattern.manage</code> permission. Your current role doesn't hold it,
          so the Discover action is hidden. This is the real backend's own access rule, not a missing feature. You
          can still review past runs below if you hold <code>di_case.view</code>.
        </div>
      )}
      <div className="explain-strip">
        <div>
          <strong>Suggestions are never authoritative on their own</strong>
          <span>
            Every suggestion below is labelled "AI suggested: awaiting review." A real Pattern or Question only
            exists once you explicitly Accept it; Dismiss discards it with no further effect.
          </span>
        </div>
      </div>
      {runError && <ErrorNote message={runError} />}

      <div className="logic-layout">
        <section className="panel logic-list">
          <div className="panel-heading">
            <div>
              <h2>Discovery runs</h2>
              <p>{runs.loading ? "Loading…" : `${runs.data?.discovery_runs.length ?? 0} run(s)`}</p>
            </div>
          </div>
          {(runs.data?.discovery_runs ?? []).map((r) => (
            <button
              className={`logic-item ${selectedRunId === r.id ? "active" : ""}`}
              key={r.id}
              onClick={() => loadRun(r.id)}
            >
              <div>
                <strong>Run {r.id.slice(0, 8)}</strong>
                <span>
                  {new Date(r.created_at).toLocaleString()} · {providerLabel(r.provider_used)} · {r.cases_analyzed_count} cases
                </span>
              </div>
              <Badge tone={runStatusTone(r.status)}>{r.status}</Badge>
            </button>
          ))}
          {!runs.loading && (runs.data?.discovery_runs.length ?? 0) === 0 && (
            <div style={{ padding: 20, color: "var(--muted)", fontSize: 11 }}>
              No discovery runs yet. Run Discover to analyse this workflow's cases.
            </div>
          )}
        </section>

        {detail && (
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>Run {detail.discovery_run.id.slice(0, 8)}</h2>
                <p>
                  {providerLabel(detail.discovery_run.provider_used)} · {detail.discovery_run.cases_analyzed_count} cases
                  analysed
                </p>
              </div>
              <Badge tone={runStatusTone(detail.discovery_run.status)}>{detail.discovery_run.status}</Badge>
            </div>
            {detail.discovery_run.error_message && (
              <div style={{ padding: "0 17px 17px" }}>
                <ErrorNote message={detail.discovery_run.error_message} />
              </div>
            )}
            <div className="pattern-list">
              {detail.suggestions.map((s) => (
                <SuggestionCard
                  key={s.id}
                  suggestion={s}
                  canAct={hasPermission(s.kind === "question" ? "di_question.manage" : "di_pattern.manage")}
                  openCase={openCase}
                  setPage={setPage}
                  onUpdated={(next) => updateSuggestion(s.id, next)}
                />
              ))}
              {detail.suggestions.length === 0 && (
                <div style={{ padding: 24, textAlign: "center", color: "var(--muted)" }}>
                  This run produced no suggestions.
                </div>
              )}
            </div>
          </section>
        )}
      </div>
    </>
  )
}

export function SuggestionCard({
  suggestion,
  canAct,
  openCase,
  setPage,
  onUpdated,
}: {
  suggestion: DiscoverySuggestion
  canAct: boolean
  openCase: (id: string) => void
  setPage: (p: Page) => void
  onUpdated: (next: DiscoverySuggestion) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [accepted, setAccepted] = useState<AcceptSuggestionResult | null>(null)

  async function accept() {
    setBusy(true)
    setError(null)
    try {
      const result = await decisionIntelligenceApi.acceptSuggestion(suggestion.id)
      setAccepted(result)
      onUpdated({ ...suggestion, status: "accepted" })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function dismiss() {
    setBusy(true)
    setError(null)
    try {
      const updated = await decisionIntelligenceApi.dismissSuggestion(suggestion.id)
      onUpdated(updated)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const isPending = suggestion.status === "suggested"

  return (
    <article className="pattern-item" style={{ gridTemplateColumns: "1fr auto" }}>
      <div className="pattern-copy">
        {isPending && <div className="ai-label">AI suggested: awaiting review</div>}
        <div className="pattern-title">
          <h3>{suggestion.title}</h3>
          <Badge tone={suggestion.kind === "pattern" ? "info" : "neutral"}>{suggestion.kind}</Badge>
          <Badge tone={statusTone(suggestion.status)}>{suggestion.status}</Badge>
        </div>
        <p>{suggestion.description}</p>
        <div className="content-block" style={{ padding: "8px 0" }}>
          <strong style={{ fontSize: 10, color: "var(--text-2)" }}>Rationale</strong>
          <p>{suggestion.rationale}</p>
        </div>
        {suggestion.candidate_explanation && (
          <div className="content-block" style={{ padding: "8px 0" }}>
            <strong style={{ fontSize: 10, color: "var(--text-2)" }}>AI-proposed hypothesis, not a conclusion</strong>
            <p>{suggestion.candidate_explanation}</p>
          </div>
        )}
        {suggestion.alternative_explanations && suggestion.alternative_explanations.length > 0 && (
          <div className="content-block" style={{ padding: "8px 0" }}>
            <strong style={{ fontSize: 10, color: "var(--text-2)" }}>Alternative explanations considered</strong>
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {suggestion.alternative_explanations.map((alt, i) => (
                <li key={i}>{String(alt)}</li>
              ))}
            </ul>
          </div>
        )}
        {suggestion.missing_evidence && suggestion.missing_evidence.length > 0 && (
          <div className="content-block" style={{ padding: "8px 0" }}>
            <strong style={{ fontSize: 10, color: "var(--text-2)" }}>Missing evidence</strong>
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {suggestion.missing_evidence.map((item, i) => (
                <li key={i}>{String(item)}</li>
              ))}
            </ul>
          </div>
        )}
        {suggestion.potential_impact && (
          <div className="content-block" style={{ padding: "8px 0" }}>
            <strong style={{ fontSize: 10, color: "var(--text-2)" }}>Potential impact</strong>
            <p>{suggestion.potential_impact}</p>
          </div>
        )}
        <div className="pattern-facts">
          <span>
            <strong>{suggestion.supporting_case_ids.length}</strong> supporting case(s)
          </span>
          <span>{suggestion.confidence ? `${suggestion.confidence} confidence` : "No confidence score"}</span>
          {suggestion.category && <span>{suggestion.category.replaceAll("_", " ")}</span>}
        </div>
        {suggestion.supporting_case_ids.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
            {suggestion.supporting_case_ids.map((caseId) => (
              <button key={caseId} className="btn ghost" onClick={() => openCase(caseId)}>
                View case {caseId.slice(0, 8)}
              </button>
            ))}
          </div>
        )}
        {error && <ErrorNote message={error} />}
        {accepted && (
          <div className="success" style={{ marginTop: 10 }}>
            <span>
              <strong>
                Created {accepted.entity_type} "{accepted.pattern?.name ?? accepted.question?.title}" (id{" "}
                {(accepted.pattern?.id ?? accepted.question?.id ?? "").slice(0, 8)})
              </strong>
              <button
                className="btn ghost"
                style={{ marginTop: 6 }}
                onClick={() => setPage(accepted.entity_type === "pattern" ? "Patterns" : "Questions")}
              >
                View {accepted.entity_type === "pattern" ? "Patterns" : "Questions"}
              </button>
            </span>
          </div>
        )}
      </div>
      {isPending && canAct && (
        <div className="pattern-actions">
          <Button kind="primary" onClick={accept} disabled={busy}>
            Accept
          </Button>
          <Button kind="ghost" onClick={dismiss} disabled={busy}>
            Dismiss
          </Button>
        </div>
      )}
      {isPending && !canAct && (
        <div className="pattern-actions">
          <span style={{ fontSize: 10, color: "var(--muted)" }}>
            Requires {suggestion.kind === "question" ? "di_question.manage" : "di_pattern.manage"}
          </span>
        </div>
      )}
    </article>
  )
}
