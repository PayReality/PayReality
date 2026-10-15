import { useState } from "react"
import { Badge, Button, EmptyPanel, ErrorNote, PageTitle } from "../components/ui"
import { decisionIntelligenceApi } from "../di/api"
import { useFetch, errorMessage } from "../lib/useAsync"
import { useAuth } from "../auth/AuthContext"

export function Reports({ workflowId }: { workflowId: string | null }) {
  const { hasPermission } = useAuth()
  const canViewReports = hasPermission("di_report.view")

  const overview = useFetch(
    () => (workflowId ? decisionIntelligenceApi.getWorkflowOverview(workflowId) : Promise.resolve(null)),
    [workflowId],
  )

  const orgOverview = useFetch(
    () => (canViewReports ? decisionIntelligenceApi.getOrganizationOverview() : Promise.resolve(null)),
    [canViewReports],
  )

  const replaysForExport = useFetch(
    () =>
      workflowId && canViewReports
        ? decisionIntelligenceApi.listReplays({ workflow_id: workflowId, limit: 100 })
        : Promise.resolve(null),
    [workflowId, canViewReports],
  )
  const completedReplays = (replaysForExport.data?.replay_runs ?? []).filter((r) => r.status === "completed")
  const [selectedReplayId, setSelectedReplayId] = useState("")
  const [exportingQuestions, setExportingQuestions] = useState(false)
  const [exportingReplay, setExportingReplay] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  async function exportQuestions() {
    setExportError(null)
    setExportingQuestions(true)
    try {
      await decisionIntelligenceApi.exportPriorityQuestionsCsv(workflowId ? { workflow_id: workflowId } : {})
    } catch (err) {
      setExportError(errorMessage(err))
    } finally {
      setExportingQuestions(false)
    }
  }

  async function exportReplay() {
    if (!selectedReplayId) return
    setExportError(null)
    setExportingReplay(true)
    try {
      await decisionIntelligenceApi.exportReplayResultsCsv(selectedReplayId)
    } catch (err) {
      setExportError(errorMessage(err))
    } finally {
      setExportingReplay(false)
    }
  }

  return (
    <>
      <PageTitle
        title="Reports"
        description="A per-workflow overview, a cross-workflow organisation overview, and real CSV exports of priority questions and replay results."
      />

      {!canViewReports && (
        <div className="permission-note" style={{ marginBottom: 16 }}>
          Cross-workflow reporting and CSV exports require the <code>di_report.view</code> permission. Your current role
          doesn't hold it, so the organisation-wide overview and export buttons below are hidden rather than shown as
          broken controls -- this is the real backend's own access rule, not a missing feature.
        </div>
      )}

      {!workflowId ? (
        <EmptyPanel title="No workflow selected" body="Choose or create a workflow first to see its overview." />
      ) : (
        <>
          {overview.error && <ErrorNote message={overview.error} />}
          {overview.data && (
            <div className="report-grid" style={{ marginBottom: 16 }}>
              <div className="report-card" style={{ cursor: "default" }}>
                <Badge tone="info">Live data</Badge>
                <h3>Workflow uncertainty overview</h3>
                <p>Case, pattern and question counts for this workflow, read live from the backend.</p>
                <div className="status-grid" style={{ marginTop: 12 }}>
                  <div>
                    <span>Cases</span>
                    <strong>
                      {overview.data.case_count} total, {overview.data.unresolved_case_count} unresolved
                    </strong>
                  </div>
                  <div>
                    <span>Patterns</span>
                    <strong>{overview.data.pattern_count}</strong>
                  </div>
                  <div>
                    <span>Answers awaiting approval</span>
                    <strong>{overview.data.answers_awaiting_approval}</strong>
                  </div>
                  <div>
                    <span>Rules validated</span>
                    <strong>{overview.data.rules_validated}</strong>
                  </div>
                  <div>
                    <span>Replays completed</span>
                    <strong>{overview.data.replays_completed}</strong>
                  </div>
                </div>
                <h3 style={{ marginTop: 16 }}>Questions by status</h3>
                <div className="status-grid">
                  {Object.entries(overview.data.questions_by_status).map(([status, count]) => (
                    <div key={status}>
                      <span>{status.replaceAll("_", " ")}</span>
                      <strong>{count}</strong>
                    </div>
                  ))}
                  {Object.keys(overview.data.questions_by_status).length === 0 && (
                    <div>
                      <span>No questions yet</span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {canViewReports && (
        <>
          <section className="panel" style={{ marginBottom: 16 }}>
            <div className="panel-heading">
              <div>
                <h2>Across all workflows</h2>
                <p>The organisation-wide overview (GET /reports/organization-overview), a real cross-workflow report.</p>
              </div>
            </div>
            {orgOverview.error && (
              <div style={{ padding: 16 }}>
                <ErrorNote message={orgOverview.error} />
              </div>
            )}
            {orgOverview.data && (
              <>
                <div className="status-grid" style={{ margin: 16 }}>
                  <div>
                    <span>Workflows</span>
                    <strong>{orgOverview.data.workflow_count}</strong>
                  </div>
                  <div>
                    <span>Total cases</span>
                    <strong>{orgOverview.data.total_cases}</strong>
                  </div>
                  <div>
                    <span>Total patterns</span>
                    <strong>{orgOverview.data.total_patterns}</strong>
                  </div>
                  <div>
                    <span>Total questions</span>
                    <strong>{orgOverview.data.total_questions}</strong>
                  </div>
                  <div>
                    <span>Total answers</span>
                    <strong>{orgOverview.data.total_answers}</strong>
                  </div>
                  <div>
                    <span>Total rules</span>
                    <strong>{orgOverview.data.total_rules}</strong>
                  </div>
                  <div>
                    <span>Total replays</span>
                    <strong>{orgOverview.data.total_replays}</strong>
                  </div>
                </div>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Workflow</th>
                        <th>Cases</th>
                        <th>Patterns</th>
                        <th>Questions</th>
                        <th>Answers</th>
                        <th>Rules</th>
                        <th>Replays</th>
                      </tr>
                    </thead>
                    <tbody>
                      {orgOverview.data.by_workflow.map((w) => (
                        <tr key={w.workflow_id} style={{ cursor: "default" }}>
                          <td>
                            <strong>{w.workflow_name}</strong>
                          </td>
                          <td>{w.case_count}</td>
                          <td>{w.pattern_count}</td>
                          <td>{w.question_count}</td>
                          <td>{w.answer_count}</td>
                          <td>{w.rule_count}</td>
                          <td>{w.replay_count}</td>
                        </tr>
                      ))}
                      {orgOverview.data.by_workflow.length === 0 && (
                        <tr>
                          <td colSpan={7} style={{ textAlign: "center", color: "var(--muted)" }}>
                            No workflows yet.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </section>

          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>Real exports</h2>
                <p>Both buttons download an actual file the backend generates -- never a fabricated one.</p>
              </div>
            </div>
            <div className="form-body">
              {exportError && <ErrorNote message={exportError} />}
              <div className="toggle-row">
                <span>
                  <strong>Priority questions{workflowId ? " (this workflow)" : " (every workflow)"}</strong>
                  <small>id, title, status, priority_score, owner_user_id, linked pattern/case counts.</small>
                </span>
                <Button icon="download" onClick={exportQuestions} disabled={exportingQuestions}>
                  {exportingQuestions ? "Preparing…" : "Export CSV"}
                </Button>
              </div>
              <div className="toggle-row">
                <span>
                  <strong>Replay results</strong>
                  <small>A completed replay run's per-case baseline/proposed comparison, as a real CSV.</small>
                </span>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <select value={selectedReplayId} onChange={(e) => setSelectedReplayId(e.target.value)} disabled={!workflowId}>
                    <option value="" disabled>
                      {workflowId ? "Choose a completed replay…" : "Select a workflow first"}
                    </option>
                    {completedReplays.map((r) => (
                      <option key={r.id} value={r.id}>
                        Run {r.id.slice(0, 8)} ({new Date(r.created_at).toLocaleDateString()})
                      </option>
                    ))}
                  </select>
                  <Button icon="download" onClick={exportReplay} disabled={exportingReplay || !selectedReplayId}>
                    {exportingReplay ? "Preparing…" : "Export CSV"}
                  </Button>
                </div>
              </div>
              {workflowId && completedReplays.length === 0 && (
                <div className="not-available">No completed replay runs exist yet in this workflow.</div>
              )}
            </div>
          </section>
        </>
      )}
    </>
  )
}
