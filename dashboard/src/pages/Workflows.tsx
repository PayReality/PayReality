import { useEffect, useState } from "react"
import { Badge, Button, ErrorNote, Icon, PageTitle, TableToolbar } from "../components/ui"
import { decisionIntelligenceApi } from "../di/api"
import type { Workflow, WorkflowOverview } from "../di/types"
import { errorMessage } from "../lib/useAsync"
import { useAuth } from "../auth/AuthContext"

export function Workflows({
  workflows,
  onCreated,
  setWorkflowId,
}: {
  workflows: Workflow[]
  onCreated: () => void
  setWorkflowId: (id: string) => void
}) {
  const { hasPermission } = useAuth()
  const [search, setSearch] = useState("")
  const [overviews, setOverviews] = useState<Record<string, WorkflowOverview>>({})
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let cancelled = false
    Promise.all(
      workflows.map((w) =>
        decisionIntelligenceApi
          .getWorkflowOverview(w.id)
          .then((o) => [w.id, o] as const)
          .catch(() => null),
      ),
    ).then((results) => {
      if (cancelled) return
      const next: Record<string, WorkflowOverview> = {}
      for (const r of results) if (r) next[r[0]] = r[1]
      setOverviews(next)
    })
    return () => {
      cancelled = true
    }
  }, [workflows])

  const visible = workflows.filter((w) => w.name.toLowerCase().includes(search.toLowerCase()))

  async function handleCreate() {
    if (!name.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      const created = await decisionIntelligenceApi.createWorkflow({
        name: name.trim(),
        description: description.trim() || undefined,
      })
      setCreating(false)
      setName("")
      setDescription("")
      onCreated()
      setWorkflowId(created.id)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <PageTitle
        title="Workflows"
        description="Browse the AI-powered business workflows under cross-case uncertainty analysis."
        actions={
          hasPermission("di_workflow.manage") ? (
            <Button kind="primary" icon="plus" onClick={() => setCreating(!creating)}>
              {creating ? "Cancel" : "New workflow"}
            </Button>
          ) : undefined
        }
      />
      {creating && (
        <section className="panel" style={{ marginBottom: 16 }}>
          <div className="form-body">
            <label>
              Workflow name *
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Claims Assessment" />
            </label>
            <label>
              Description
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What business decisions does this workflow cover?"
              />
            </label>
            {error && <ErrorNote message={error} />}
            <Button kind="primary" onClick={handleCreate} disabled={submitting || !name.trim()}>
              {submitting ? "Creating…" : "Create workflow"}
            </Button>
          </div>
        </section>
      )}
      <section className="panel table-panel">
        <TableToolbar search={search} setSearch={setSearch} resultsLabel={`${visible.length} of ${workflows.length} workflows`} />
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Workflow</th>
                <th>Cases</th>
                <th>Patterns</th>
                <th>Questions</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {visible.map((w) => {
                const o = overviews[w.id]
                const totalQuestions = o ? Object.values(o.questions_by_status).reduce((a, b) => a + b, 0) : null
                return (
                  <tr key={w.id} onClick={() => setWorkflowId(w.id)}>
                    <td>
                      <strong>{w.name}</strong>
                      {w.description && <span className="cell-sub">{w.description}</span>}
                    </td>
                    <td>{o ? o.case_count : "—"}</td>
                    <td>{o ? o.pattern_count : "—"}</td>
                    <td>{totalQuestions ?? "—"}</td>
                    <td>
                      <Badge tone={w.status === "active" ? "success" : "neutral"}>{w.status}</Badge>
                    </td>
                    <td>
                      <Icon name="chevron" />
                    </td>
                  </tr>
                )
              })}
              {visible.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ textAlign: "center", color: "var(--muted)" }}>
                    No workflows yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}
