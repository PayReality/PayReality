import { useEffect, useState } from "react"
import { Badge, Button, EmptyPanel, ErrorNote, PageTitle, TableToolbar } from "../components/ui"
import { decisionIntelligenceApi } from "../di/api"
import type { Pattern, PatternReviewStatus } from "../di/types"
import { useFetch, errorMessage } from "../lib/useAsync"
import type { Page } from "../types"
import { useAuth } from "../auth/AuthContext"

// review_status -> this design's "Observed pattern" / "Candidate pattern"
// labels. `confirmed` is the only status a human has actually signed off
// on as real, so it alone reads as "Observed"; everything earlier in the
// lifecycle (and `rejected`, shown plainly) stays a candidate.
function stateLabel(status: PatternReviewStatus): string {
  if (status === "confirmed") return "Observed pattern"
  if (status === "rejected") return "Rejected pattern"
  return "Candidate pattern"
}
function stateTone(status: PatternReviewStatus): string {
  if (status === "confirmed") return "success"
  if (status === "rejected") return "neutral"
  return "warning"
}

export function Patterns({ workflowId, setPage }: { workflowId: string | null; setPage: (p: Page) => void }) {
  const { hasPermission } = useAuth()
  const [search, setSearch] = useState("")
  const [caseCounts, setCaseCounts] = useState<Record<string, number>>({})
  const [totalCases, setTotalCases] = useState<number | null>(null)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ name: "", description: "", category: "unclear_policy", proposed_explanation: "" })
  const [createError, setCreateError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const { data, loading, error, reload } = useFetch(
    () => (workflowId ? decisionIntelligenceApi.listPatterns({ workflow_id: workflowId, limit: 200 }) : Promise.resolve(null)),
    [workflowId],
  )

  useEffect(() => {
    if (!workflowId) return
    decisionIntelligenceApi.getWorkflowOverview(workflowId).then((o) => setTotalCases(o.case_count)).catch(() => {})
  }, [workflowId])

  useEffect(() => {
    if (!data) return
    let cancelled = false
    Promise.all(
      data.patterns.map((p) =>
        decisionIntelligenceApi
          .listPatternCases(p.id)
          .then((ids) => [p.id, ids.length] as const)
          .catch(() => [p.id, 0] as const),
      ),
    ).then((results) => {
      if (cancelled) return
      const next: Record<string, number> = {}
      for (const [id, count] of results) next[id] = count
      setCaseCounts(next)
    })
    return () => {
      cancelled = true
    }
  }, [data])

  async function handleCreate() {
    if (!workflowId || !form.name.trim() || !form.description.trim() || !form.proposed_explanation.trim()) return
    setSubmitting(true)
    setCreateError(null)
    try {
      await decisionIntelligenceApi.createPattern({ workflow_id: workflowId, ...form })
      setCreating(false)
      setForm({ name: "", description: "", category: "unclear_policy", proposed_explanation: "" })
      reload()
    } catch (err) {
      setCreateError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  async function markReviewed(p: Pattern) {
    try {
      await decisionIntelligenceApi.updatePattern(p.id, { review_status: "reviewed" })
      reload()
    } catch {
      // surfaced via the page-level error banner on next reload if it recurs
    }
  }

  if (!workflowId) {
    return (
      <>
        <PageTitle title="Recurring patterns" description="See what emerges across cases." />
        <EmptyPanel title="No workflow selected" body="Choose or create a workflow first." />
      </>
    )
  }

  const patterns = data?.patterns.filter((p) => p.name.toLowerCase().includes(search.toLowerCase())) ?? []

  return (
    <>
      <PageTitle
        title="Recurring patterns"
        description="See what emerges across cases: repeated uncertainty, its evidence, and the questions that could resolve it."
        actions={
          <>
            {hasPermission("di_pattern.manage") && (
              <Button kind="primary" onClick={() => setCreating(!creating)}>
                {creating ? "Cancel" : "New pattern"}
              </Button>
            )}
            <Button kind="primary" onClick={() => setPage("Questions")}>
              Explore candidate questions
            </Button>
          </>
        }
      />
      {creating && (
        <section className="panel" style={{ marginBottom: 16 }}>
          <div className="form-body">
            <label>
              Pattern name *
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <div className="form-grid">
              <label>
                Category
                <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                  <option value="missing_facts">Missing facts</option>
                  <option value="unclear_policy">Unclear policy</option>
                  <option value="conflicting_rules">Conflicting rules</option>
                  <option value="authority_gap">Authority gap</option>
                  <option value="context_interpretation">Context interpretation</option>
                  <option value="human_judgement">Human judgement</option>
                  <option value="other">Other</option>
                </select>
              </label>
            </div>
            <label>
              Description *
              <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </label>
            <label>
              Proposed explanation *
              <textarea
                value={form.proposed_explanation}
                onChange={(e) => setForm({ ...form, proposed_explanation: e.target.value })}
              />
            </label>
            {createError && <ErrorNote message={createError} />}
            <Button kind="primary" onClick={handleCreate} disabled={submitting}>
              {submitting ? "Creating…" : "Create pattern"}
            </Button>
          </div>
        </section>
      )}
      {error && <ErrorNote message={error} />}
      <section className="panel table-panel">
        <TableToolbar search={search} setSearch={setSearch} resultsLabel={loading ? "Loading…" : `${patterns.length} patterns`} />
        <div className="pattern-list">
          {patterns.map((p, i) => (
            <article className="pattern-item" key={p.id}>
              <div className="pattern-index">0{i + 1}</div>
              <div className="pattern-copy">
                <div className="pattern-title">
                  <h3>{p.name}</h3>
                  <Badge tone={stateTone(p.review_status)}>{stateLabel(p.review_status)}</Badge>
                </div>
                <p>{p.description}</p>
                <div className="pattern-facts">
                  <span>
                    <strong>{caseCounts[p.id] ?? 0}</strong> linked cases
                  </span>
                  <span>
                    <strong>
                      {totalCases && totalCases > 0 ? `${(((caseCounts[p.id] ?? 0) / totalCases) * 100).toFixed(1)}%` : "—"}
                    </strong>{" "}
                    of case set
                  </span>
                  <span>{p.confidence ? `${p.confidence} confidence` : "Confidence not yet assessed"}</span>
                </div>
              </div>
              <div className="pattern-actions">
                <Button onClick={() => setPage("Cases")}>View cases</Button>
                <Button kind="ghost" onClick={() => setPage("Questions")}>
                  Related questions
                </Button>
                {hasPermission("di_pattern.manage") && p.review_status === "proposed" && (
                  <Button kind="ghost" onClick={() => markReviewed(p)}>
                    Mark for review
                  </Button>
                )}
              </div>
            </article>
          ))}
          {!loading && patterns.length === 0 && (
            <div style={{ padding: 24, textAlign: "center", color: "var(--muted)" }}>No patterns recorded yet.</div>
          )}
        </div>
      </section>
    </>
  )
}
