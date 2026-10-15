import { useEffect, useState } from "react"
import { Badge, Button, EmptyPanel, ErrorNote, Icon, PageTitle, TableToolbar } from "../components/ui"
import { decisionIntelligenceApi } from "../di/api"
import type { Case } from "../di/types"
import { useFetch, errorMessage } from "../lib/useAsync"
import { useAuth } from "../auth/AuthContext"
import { CsvImportPanel } from "../components/CsvImportPanel"

// Server-side search debounce (Feature: server-side case search) -- long
// enough that a person typing a reference doesn't fire a request per
// keystroke, short enough to still feel live.
const SEARCH_DEBOUNCE_MS = 350

function statusTone(status: Case["status"]): string {
  if (status === "escalated") return "warning"
  if (status === "resolved") return "success"
  return "neutral"
}

export function Cases({ workflowId, openCase }: { workflowId: string | null; openCase: (id: string) => void }) {
  const { hasPermission } = useAuth()
  const [search, setSearch] = useState("")
  const [debouncedSearch, setDebouncedSearch] = useState("")
  const [statusFilter, setStatusFilter] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [importing, setImporting] = useState(false)
  const [externalRef, setExternalRef] = useState("")
  const [factsJson, setFactsJson] = useState("{\n  \n}")
  const [humanDecisionJson, setHumanDecisionJson] = useState("")
  const [createError, setCreateError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Debounced so every keystroke doesn't fire its own request against the
  // real `q` search parameter (di_case_service.list_cases).
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [search])

  const { data, loading, error, reload } = useFetch(
    () =>
      workflowId
        ? decisionIntelligenceApi.listCases({
            workflow_id: workflowId,
            status: statusFilter ?? undefined,
            q: debouncedSearch || undefined,
            limit: 200,
          })
        : Promise.resolve(null),
    [workflowId, statusFilter, debouncedSearch],
  )

  // The real, server-filtered page -- no client-side re-filtering on top.
  const visible = data?.cases ?? []

  async function handleCreate() {
    if (!workflowId) return
    setSubmitting(true)
    setCreateError(null)
    try {
      let facts: Record<string, unknown> = {}
      if (factsJson.trim()) {
        try {
          facts = JSON.parse(factsJson)
        } catch {
          throw new Error("Facts must be valid JSON.")
        }
      }
      let human_decision: Record<string, unknown> | undefined
      if (humanDecisionJson.trim()) {
        try {
          human_decision = JSON.parse(humanDecisionJson)
        } catch {
          throw new Error("Recorded baseline decision must be valid JSON.")
        }
      }
      await decisionIntelligenceApi.createCase({
        workflow_id: workflowId,
        facts,
        external_ref: externalRef.trim() || undefined,
        human_decision,
      })
      setCreating(false)
      setExternalRef("")
      setFactsJson("{\n  \n}")
      setHumanDecisionJson("")
      reload()
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (!workflowId) {
    return (
      <>
        <PageTitle title="Cases" description="Inspect the source evidence behind recurring uncertainty." />
        <EmptyPanel title="No workflow selected" body="Choose or create a workflow first." />
      </>
    )
  }

  return (
    <>
      <PageTitle
        title="Cases"
        description="Inspect the source evidence behind recurring uncertainty without treating any single case as the complete explanation."
        actions={
          <>
            <Button onClick={() => setStatusFilter(statusFilter === "escalated" ? null : "escalated")} icon="filter">
              {statusFilter === "escalated" ? "Clear escalation filter" : "Show escalated"}
            </Button>
            {hasPermission("di_case.manage") && (
              <Button icon="download" onClick={() => setImporting(!importing)}>
                {importing ? "Cancel import" : "Import CSV"}
              </Button>
            )}
            {hasPermission("di_case.manage") && (
              <Button kind="primary" icon="plus" onClick={() => setCreating(!creating)}>
                {creating ? "Cancel" : "New case"}
              </Button>
            )}
          </>
        }
      />
      <div className="scope-banner">
        <Icon name="file" />
        <div>
          <strong>Evidence foundation</strong>
          <span>Case content shown here is whatever has actually been recorded for this workflow. Nothing is simulated.</span>
        </div>
      </div>
      {importing && (
        <CsvImportPanel
          workflowId={workflowId}
          onImported={() => {
            reload()
          }}
        />
      )}
      {creating && (
        <section className="panel" style={{ marginBottom: 16 }}>
          <div className="form-body">
            <label>
              External reference
              <input value={externalRef} onChange={(e) => setExternalRef(e.target.value)} placeholder="e.g. CLM-10482" />
            </label>
            <label>
              Facts (JSON)
              <textarea value={factsJson} onChange={(e) => setFactsJson(e.target.value)} rows={4} />
            </label>
            <label>
              Recorded baseline decision (JSON, optional): what a replay compares a proposed decision against
              <textarea
                value={humanDecisionJson}
                onChange={(e) => setHumanDecisionJson(e.target.value)}
                rows={2}
                placeholder='e.g. {"decision": "approve"}'
              />
            </label>
            {createError && <ErrorNote message={createError} />}
            <Button kind="primary" onClick={handleCreate} disabled={submitting}>
              {submitting ? "Creating…" : "Create case"}
            </Button>
          </div>
        </section>
      )}
      {error && <ErrorNote message={error} />}
      <section className="panel table-panel">
        <TableToolbar
          search={search}
          setSearch={setSearch}
          resultsLabel={loading ? "Loading…" : `${data?.total ?? visible.length} case${(data?.total ?? visible.length) === 1 ? "" : "s"}`}
        />
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Case reference</th>
                <th>Status</th>
                <th>Outcome</th>
                <th>Escalation reason</th>
                <th>Case date</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr key={row.id} onClick={() => openCase(row.id)}>
                  <td>
                    <strong>{row.external_ref ?? row.id.slice(0, 8)}</strong>
                  </td>
                  <td>
                    <Badge tone={statusTone(row.status)}>{row.status}</Badge>
                  </td>
                  <td>{row.outcome ?? "—"}</td>
                  <td>{row.escalation_reason ?? "—"}</td>
                  <td>{new Date(row.created_at).toLocaleDateString()}</td>
                  <td>
                    <button className="row-open" title={`Open ${row.id}`}>
                      <Icon name="chevron" size={15} />
                    </button>
                  </td>
                </tr>
              ))}
              {!loading && visible.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ textAlign: "center", color: "var(--muted)" }}>
                    No cases yet.
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
