import { useEffect, useState } from "react"
import { Badge, Button, EmptyPanel, ErrorNote, Icon, LoadingPanel, PageTitle } from "../components/ui"
import { decisionIntelligenceApi } from "../di/api"
import type { Pattern, Question, WorkflowOverview } from "../di/types"
import { useFetch, errorMessage } from "../lib/useAsync"
import type { Modal, Page } from "../types"

export function Overview({
  workflowId,
  setPage,
  setModal,
}: {
  workflowId: string | null
  setPage: (p: Page) => void
  setModal: (m: Modal) => void
}) {
  const overview = useFetch<WorkflowOverview | null>(
    () => (workflowId ? decisionIntelligenceApi.getWorkflowOverview(workflowId) : Promise.resolve(null)),
    [workflowId],
  )
  const [patterns, setPatterns] = useState<{ pattern: Pattern; linkedCases: number }[]>([])
  const [patternsError, setPatternsError] = useState<string | null>(null)
  const [topQuestions, setTopQuestions] = useState<Question[] | null>(null)
  const [questionsError, setQuestionsError] = useState<string | null>(null)

  useEffect(() => {
    if (!workflowId) return
    let cancelled = false
    decisionIntelligenceApi
      .listPatterns({ workflow_id: workflowId, limit: 4 })
      .then(async (page) => {
        if (cancelled) return
        const withCounts = await Promise.all(
          page.patterns.map(async (pattern) => {
            try {
              const caseIds = await decisionIntelligenceApi.listPatternCases(pattern.id)
              return { pattern, linkedCases: caseIds.length }
            } catch {
              return { pattern, linkedCases: 0 }
            }
          }),
        )
        if (!cancelled) setPatterns(withCounts)
      })
      .catch((err) => !cancelled && setPatternsError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [workflowId])

  useEffect(() => {
    if (!workflowId) return
    let cancelled = false
    decisionIntelligenceApi
      .listQuestions({ workflow_id: workflowId, sort_by: "priority_score", limit: 3 })
      .then((page) => !cancelled && setTopQuestions(page.questions))
      .catch((err) => !cancelled && setQuestionsError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [workflowId])

  if (!workflowId) {
    return (
      <>
        <PageTitle title="Overview" description="Understand where your AI workflow encounters uncertainty." />
        <EmptyPanel
          title="No workflow selected"
          body="Create a workflow on the Workflows page to start analysing cases, patterns and questions."
        />
      </>
    )
  }

  const o = overview.data
  const totalQuestions = o ? Object.values(o.questions_by_status).reduce((a, b) => a + b, 0) : null
  const awaitingAnswer = o?.questions_by_status["awaiting_answer"] ?? 0

  const metrics: [string, string, string, Page][] = [
    ["Cases recorded", o ? String(o.case_count) : "—", "Case set with traceable sources", "Cases"],
    ["Patterns identified", o ? String(o.pattern_count) : "—", "Recurring uncertainty found across cases", "Patterns"],
    ["Priority questions", totalQuestions !== null ? String(totalQuestions) : "—", "Across every lifecycle stage", "Questions"],
    ["Awaiting an answer", String(awaitingAnswer), "Questions with no answer submitted yet", "Questions"],
  ]

  return (
    <>
      <PageTitle
        title="Overview"
        description="Understand where your AI workflow encounters uncertainty, which questions matter most, and what should be tested next."
        actions={
          <>
            <Button icon="download" onClick={() => setModal("export-info")}>
              Export report
            </Button>
            <Button kind="primary" onClick={() => setPage("Questions")}>
              Review priority questions
            </Button>
          </>
        }
      />
      {overview.error && <ErrorNote message={overview.error} />}
      {overview.loading && <LoadingPanel label="Loading workflow overview…" />}
      {o && (
        <>
          <div className="kpi-grid">
            {metrics.map(([label, value, caption, destination], i) => (
              <button className="kpi" key={label} onClick={() => setPage(destination)}>
                <div className="kpi-top">
                  <span>{label}</span>
                  <span className="kpi-icon">0{i + 1}</span>
                </div>
                <strong>{value}</strong>
                <p>{caption}</p>
                <div className="kpi-link">
                  Explore <Icon name="arrow" size={14} />
                </div>
              </button>
            ))}
          </div>
          <div className="overview-grid">
            <section className="panel uncertainty-panel">
              <div className="panel-heading">
                <div>
                  <h2>Recurring uncertainty</h2>
                  <p>What repeatedly prevents a confident decision</p>
                </div>
                <Button kind="ghost" onClick={() => setPage("Patterns")}>
                  View patterns
                </Button>
              </div>
              {patternsError && <ErrorNote message={patternsError} />}
              {patterns.length === 0 && !patternsError && (
                <div className="chart-note">
                  <Icon name="help" size={15} />
                  <span>No patterns recorded for this workflow yet.</span>
                </div>
              )}
              {patterns.length > 0 && (
                <>
                  <div className="chart-labels">
                    <span>Pattern category</span>
                    <span>Linked cases</span>
                  </div>
                  {patterns.map(({ pattern, linkedCases }) => (
                    <button className="bar-row" key={pattern.id} onClick={() => setPage("Patterns")}>
                      <div className="bar-copy">
                        <strong>{pattern.name}</strong>
                        <span>{pattern.description}</span>
                      </div>
                      <div className="bar-track">
                        <i style={{ width: `${o.case_count > 0 ? Math.min(100, (linkedCases / o.case_count) * 100) : 0}%` }} />
                      </div>
                      <div className="bar-value">
                        <strong>{linkedCases}</strong>
                        <span>{o.case_count > 0 ? `${((linkedCases / o.case_count) * 100).toFixed(1)}%` : "—"}</span>
                      </div>
                    </button>
                  ))}
                  <div className="chart-note">
                    <Icon name="help" size={15} />
                    <span>
                      Categories are analytical hypotheses. Review evidence before treating a candidate pattern as
                      established.
                    </span>
                  </div>
                </>
              )}
            </section>
            <section className="panel priority-panel">
              <div className="panel-heading">
                <div>
                  <h2>Priority questions</h2>
                  <p>Questions with the greatest potential decision leverage</p>
                </div>
                <Badge tone="info">Sorted by priority score</Badge>
              </div>
              {questionsError && <ErrorNote message={questionsError} />}
              {topQuestions && topQuestions.length === 0 && (
                <div className="chart-note">
                  <Icon name="help" size={15} />
                  <span>No priority questions recorded for this workflow yet.</span>
                </div>
              )}
              {topQuestions?.map((q, i) => (
                <button className="question-card" key={q.id} onClick={() => setPage("Questions")}>
                  <div className="rank">{i + 1}</div>
                  <div className="question-main">
                    <strong>{q.title}</strong>
                    <div className="question-meta">
                      <span>
                        Priority <b>{q.priority_score !== null ? q.priority_score.toFixed(1) : "not yet assessed"}</b>
                      </span>
                      <Badge tone="info">{q.status.replaceAll("_", " ")}</Badge>
                    </div>
                  </div>
                  <Icon name="chevron" size={16} />
                </button>
              ))}
              <Button kind="ghost" onClick={() => setPage("Questions")}>
                View all priority questions <Icon name="arrow" size={14} />
              </Button>
            </section>
          </div>
        </>
      )}
    </>
  )
}
