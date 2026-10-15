import { useEffect, useState } from "react"
import { Badge, Button, EmptyPanel, ErrorNote, PageTitle, TableToolbar } from "../components/ui"
import { decisionIntelligenceApi } from "../di/api"
import type { CaseLink, CaseLinkKind, Pattern, PatternReviewStatus } from "../di/types"
import { CASE_LINK_KINDS, CASE_LINK_KIND_LABELS } from "../di/types"
import { useFetch, errorMessage } from "../lib/useAsync"
import type { Page } from "../types"
import { useAuth } from "../auth/AuthContext"

function caseLinkTone(kind: CaseLinkKind): string {
  if (kind === "supporting") return "success"
  if (kind === "excluded") return "neutral"
  if (kind === "potentially_affected") return "warning"
  return "neutral"
}

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
  const [expandedEvidence, setExpandedEvidence] = useState<string | null>(null)

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
                {p.alternative_explanations && p.alternative_explanations.length > 0 && (
                  <div className="content-block" style={{ padding: "8px 0" }}>
                    <strong style={{ fontSize: 10, color: "var(--text-2)" }}>Alternative explanations considered</strong>
                    <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                      {p.alternative_explanations.map((alt, i) => (
                        <li key={i}>{String(alt)}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="pattern-facts">
                  <span>
                    <strong>{caseCounts[p.id] ?? 0}</strong> linked cases
                  </span>
                  <span>
                    <strong>
                      {totalCases && totalCases > 0 ? `${(((caseCounts[p.id] ?? 0) / totalCases) * 100).toFixed(1)}%` : "N/A"}
                    </strong>{" "}
                    of case set
                  </span>
                  <span>{p.confidence ? `${p.confidence} confidence` : "Confidence not yet assessed"}</span>
                </div>
                <button
                  className="btn ghost"
                  style={{ marginTop: 8 }}
                  onClick={() => setExpandedEvidence(expandedEvidence === p.id ? null : p.id)}
                >
                  {expandedEvidence === p.id ? "Hide evidence detail" : "Show evidence detail (why each case is linked)"}
                </button>
                {expandedEvidence === p.id && <PatternCaseLinks patternId={p.id} canManage={hasPermission("di_pattern.manage")} />}
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

function PatternCaseLinks({ patternId, canManage }: { patternId: string; canManage: boolean }) {
  const { data, loading, error, reload } = useFetch(() => decisionIntelligenceApi.listPatternCaseLinks(patternId), [patternId])
  const [editingCaseId, setEditingCaseId] = useState<string | null>(null)
  const [newKind, setNewKind] = useState<CaseLinkKind>("supporting")
  const [reason, setReason] = useState("")
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  function startEdit(link: CaseLink) {
    setEditingCaseId(link.case_id)
    setNewKind(link.kind)
    setReason(link.reason ?? "")
    setSaveError(null)
  }

  async function saveRelink(caseId: string) {
    setSaving(true)
    setSaveError(null)
    try {
      await decisionIntelligenceApi.relinkPatternCaseKind(patternId, caseId, { new_kind: newKind, reason: reason || undefined })
      setEditingCaseId(null)
      reload()
    } catch (err) {
      setSaveError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="content-block" style={{ padding: "10px 0", borderTop: "1px solid var(--border)", marginTop: 8 }}>
      {loading && <span style={{ fontSize: 11, color: "var(--muted)" }}>Loading linked cases…</span>}
      {error && <ErrorNote message={error} />}
      {!loading && (data ?? []).length === 0 && <span style={{ fontSize: 11, color: "var(--muted)" }}>No cases linked yet.</span>}
      {(data ?? []).map((link) => (
        <div key={link.case_id} style={{ display: "flex", flexDirection: "column", gap: 4, padding: "6px 0" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <strong style={{ fontSize: 11 }}>Case {link.case_id.slice(0, 8)}</strong>
            <Badge tone={caseLinkTone(link.kind)}>{CASE_LINK_KIND_LABELS[link.kind]}</Badge>
            {canManage && (
              <button className="btn ghost" onClick={() => (editingCaseId === link.case_id ? setEditingCaseId(null) : startEdit(link))}>
                {editingCaseId === link.case_id ? "Cancel" : "Change"}
              </button>
            )}
          </div>
          {link.reason && <span style={{ fontSize: 11, color: "var(--text-2)" }}>{link.reason}</span>}
          {editingCaseId === link.case_id && (
            <div className="form-body" style={{ padding: 0 }}>
              <label>
                New relevance category
                <select value={newKind} onChange={(e) => setNewKind(e.target.value as CaseLinkKind)}>
                  {CASE_LINK_KINDS.map((k) => (
                    <option key={k} value={k}>
                      {CASE_LINK_KIND_LABELS[k]}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Reason (optional)
                <textarea value={reason} onChange={(e) => setReason(e.target.value)} />
              </label>
              {saveError && <ErrorNote message={saveError} />}
              <Button kind="primary" onClick={() => saveRelink(link.case_id)} disabled={saving}>
                {saving ? "Saving…" : "Save"}
              </Button>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
