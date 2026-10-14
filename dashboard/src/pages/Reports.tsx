import { Badge, EmptyPanel, ErrorNote, Icon, PageTitle } from "../components/ui"
import { decisionIntelligenceApi } from "../di/api"
import { useFetch } from "../lib/useAsync"

export function Reports({ workflowId }: { workflowId: string | null }) {
  const overview = useFetch(
    () => (workflowId ? decisionIntelligenceApi.getWorkflowOverview(workflowId) : Promise.resolve(null)),
    [workflowId],
  )

  if (!workflowId) {
    return (
      <>
        <PageTitle title="Reports" description="Prepare evidence-led summaries of this workflow." />
        <EmptyPanel title="No workflow selected" body="Choose or create a workflow first." />
      </>
    )
  }

  return (
    <>
      <PageTitle
        title="Reports"
        description="The only report this backend currently generates is a per-workflow overview. There is no cross-workflow aggregate report and no PDF/CSV export yet."
      />
      <div className="not-available" style={{ marginBottom: 16 }}>
        <Icon name="download" />
        <span>
          Export isn't available yet. The backend exposes <code>GET /workflows/&#123;id&#125;/overview</code> only -- no
          PDF or CSV generation endpoint exists. Rather than fake a download, this page shows the real overview data below.
        </span>
      </div>
      {overview.error && <ErrorNote message={overview.error} />}
      {overview.data && (
        <div className="report-grid">
          <div className="report-card" style={{ cursor: "default" }}>
            <Badge tone="info">Live data</Badge>
            <h3>Workflow uncertainty overview</h3>
            <p>Case, pattern and question counts for this workflow, read live from the backend.</p>
            <div className="status-grid" style={{ marginTop: 12 }}>
              <div>
                <span>Cases</span>
                <strong>{overview.data.case_count} total, {overview.data.unresolved_case_count} unresolved</strong>
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
  )
}
