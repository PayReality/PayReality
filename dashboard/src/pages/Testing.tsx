import { useEffect, useState } from "react"
import { Badge, Button, EmptyPanel, ErrorNote, PageTitle } from "../components/ui"
import { decisionIntelligenceApi } from "../di/api"
import type { DecisionRule, ReplayCaseResult, ReplayRun, RuleVersion } from "../di/types"
import { OUTCOME_CATEGORIES, OUTCOME_CATEGORY_LABELS } from "../di/types"
import { useFetch, errorMessage } from "../lib/useAsync"
import type { Page } from "../types"
import { useAuth } from "../auth/AuthContext"

export function Testing({ workflowId, setPage }: { workflowId: string | null; setPage: (p: Page) => void }) {
  const { hasPermission } = useAuth()
  const [selectedReplayId, setSelectedReplayId] = useState<string | null>(null)
  const [configuring, setConfiguring] = useState(false)

  const { data: replaysPage, loading, error, reload } = useFetch(
    () => (workflowId ? decisionIntelligenceApi.listReplays({ workflow_id: workflowId, limit: 100 }) : Promise.resolve(null)),
    [workflowId],
  )
  const replays = replaysPage?.replay_runs ?? []

  useEffect(() => {
    if (replays.length > 0 && !selectedReplayId) setSelectedReplayId(replays[0].id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [replays.map((r) => r.id).join(",")])

  const results = useFetch<ReplayCaseResult[] | null>(
    () => (selectedReplayId ? decisionIntelligenceApi.listReplayResults(selectedReplayId).then((p) => p.results) : Promise.resolve(null)),
    [selectedReplayId],
  )
  const selectedReplay = replays.find((r) => r.id === selectedReplayId)

  if (!workflowId) {
    return (
      <>
        <PageTitle title="Testing & Replay" description="Evaluate approved logic against real historical cases." />
        <EmptyPanel title="No workflow selected" body="Choose or create a workflow first." />
      </>
    )
  }

  return (
    <>
      <PageTitle
        title="Testing & Replay"
        description="Run a validated decision rule against real persisted cases and compare it to each case's recorded baseline decision."
        actions={
          <>
            <Button onClick={() => setPage("Decision Logic")}>View decision logic</Button>
            {hasPermission("di_replay.run") && (
              <Button kind="primary" icon="play" onClick={() => setConfiguring(!configuring)}>
                {configuring ? "Cancel" : "Configure replay"}
              </Button>
            )}
          </>
        }
      />
      <div className="simulation-banner">
        <Badge tone="info">Real execution</Badge>
        <div>
          <strong>Agreement, not correctness</strong>
          <span>
            "Agrees with baseline" means the proposed decision matches what a human already decided -- it is never a claim
            that either the baseline or the rule was right.
          </span>
        </div>
      </div>
      {error && <ErrorNote message={error} />}
      {configuring && (
        <ReplayConfigurator
          workflowId={workflowId}
          onCreated={(run) => {
            setConfiguring(false)
            reload()
            setSelectedReplayId(run.id)
          }}
        />
      )}
      <div className="logic-layout">
        <section className="panel logic-list">
          <div className="panel-heading">
            <div>
              <h2>Replay runs</h2>
              <p>{loading ? "Loading…" : `${replays.length} run(s)`}</p>
            </div>
          </div>
          {replays.map((r) => (
            <button className={`logic-item ${selectedReplayId === r.id ? "active" : ""}`} key={r.id} onClick={() => setSelectedReplayId(r.id)}>
              <div>
                <strong>Run {r.id.slice(0, 8)}</strong>
                <span>{new Date(r.created_at).toLocaleString()}</span>
              </div>
              <Badge tone={r.status === "completed" ? "success" : r.status === "failed" ? "warning" : "neutral"}>{r.status}</Badge>
            </button>
          ))}
          {!loading && replays.length === 0 && <div style={{ padding: 20, color: "var(--muted)", fontSize: 11 }}>No replays run yet.</div>}
        </section>
        {selectedReplay && (
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>Outcome summary</h2>
                <p>Rule version {selectedReplay.rule_version_id.slice(0, 8)} · {selectedReplay.summary?.total_cases ?? 0} cases</p>
              </div>
              <Badge tone="info">Run {selectedReplay.id.slice(0, 8)}</Badge>
            </div>
            <div className="test-summary">
              {OUTCOME_CATEGORIES.map((cat) => {
                const count = selectedReplay.summary?.counts[cat] ?? 0
                const total = selectedReplay.summary?.total_cases ?? 0
                const pct = total > 0 ? ((count / total) * 100).toFixed(0) : "0"
                return (
                  <button key={cat}>
                    <strong>{count}</strong>
                    <span>
                      {OUTCOME_CATEGORY_LABELS[cat]} ({pct}%)
                    </span>
                  </button>
                )
              })}
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Case</th>
                    <th>Baseline</th>
                    <th>Proposed</th>
                    <th>Outcome</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {(results.data ?? []).map((r) => (
                    <tr key={r.id} onClick={() => setPage("Cases")}>
                      <td>
                        <strong>{r.case_id.slice(0, 8)}</strong>
                      </td>
                      <td>{r.baseline_decision ? JSON.stringify(r.baseline_decision) : "—"}</td>
                      <td>{r.proposed_decision ? JSON.stringify(r.proposed_decision) : "—"}</td>
                      <td>
                        <Badge tone={r.outcome_category === "disagrees_with_baseline" ? "warning" : "neutral"}>
                          {OUTCOME_CATEGORY_LABELS[r.outcome_category]}
                        </Badge>
                      </td>
                      <td>{r.notes ?? "—"}</td>
                    </tr>
                  ))}
                  {results.data && results.data.length === 0 && (
                    <tr>
                      <td colSpan={5} style={{ textAlign: "center", color: "var(--muted)" }}>
                        No per-case results.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </div>
    </>
  )
}

function ReplayConfigurator({ workflowId, onCreated }: { workflowId: string; onCreated: (run: ReplayRun) => void }) {
  const [rules, setRules] = useState<DecisionRule[] | null>(null)
  const [versionsByRule, setVersionsByRule] = useState<Record<string, RuleVersion[]>>({})
  const [ruleId, setRuleId] = useState("")
  const [versionId, setVersionId] = useState("")
  const [filterStatus, setFilterStatus] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    decisionIntelligenceApi.listRules({ workflow_id: workflowId, status: "validated", limit: 200 }).then((p) => setRules(p.rules))
  }, [workflowId])

  useEffect(() => {
    if (!ruleId) return
    decisionIntelligenceApi.listRuleVersions(ruleId).then((versions) => {
      setVersionsByRule((prev) => ({ ...prev, [ruleId]: versions }))
      const rule = rules?.find((r) => r.id === ruleId)
      setVersionId(rule?.current_version_id ?? versions[versions.length - 1]?.id ?? "")
    })
  }, [ruleId, rules])

  async function submit() {
    if (!versionId) return
    setSubmitting(true)
    setError(null)
    try {
      const run = await decisionIntelligenceApi.createReplay({
        workflow_id: workflowId,
        rule_version_id: versionId,
        filter_status: filterStatus || undefined,
      })
      onCreated(run)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="panel" style={{ marginBottom: 16 }}>
      <div className="form-body">
        {rules !== null && rules.length === 0 && (
          <div className="not-available">No validated rules exist yet in this workflow. Validate a rule on Decision Logic first.</div>
        )}
        {rules && rules.length > 0 && (
          <>
            <div className="form-grid">
              <label>
                Validated rule
                <select value={ruleId} onChange={(e) => setRuleId(e.target.value)}>
                  <option value="" disabled>
                    Choose a rule…
                  </option>
                  {rules.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Rule version
                <select value={versionId} onChange={(e) => setVersionId(e.target.value)} disabled={!ruleId}>
                  {(versionsByRule[ruleId] ?? []).map((v) => (
                    <option key={v.id} value={v.id}>
                      v{v.version}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label>
              Case filter
              <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
                <option value="">All cases in this workflow</option>
                <option value="open">Open cases only</option>
                <option value="resolved">Resolved cases only</option>
                <option value="escalated">Escalated cases only</option>
              </select>
            </label>
            {error && <ErrorNote message={error} />}
            <Button kind="primary" onClick={submit} disabled={submitting || !versionId}>
              {submitting ? "Running replay…" : "Run replay"}
            </Button>
          </>
        )}
      </div>
    </section>
  )
}
