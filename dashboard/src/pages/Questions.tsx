import { useEffect, useState } from "react"
import { Badge, Button, EmptyPanel, ErrorNote, PageTitle, TableToolbar } from "../components/ui"
import { decisionIntelligenceApi } from "../di/api"
import type { Answer, Question, QuestionDetail } from "../di/types"
import { QUESTION_STATUS_LABELS } from "../di/types"
import { linkedCaseSummary, PriorityScoreCell, ScoreBand, ScoreValue } from "../di/scoring"
import { useFetch, errorMessage } from "../lib/useAsync"
import type { Modal, Page } from "../types"
import { useAuth } from "../auth/AuthContext"
import type { OrgUser } from "../users/types"

const SCORE_FIELDS = [
  { key: "reach_score", label: "Reach" },
  { key: "impact_score", label: "Decision impact" },
  { key: "risk_score", label: "Risk if unresolved" },
  { key: "answerability_score", label: "Answerability" },
  { key: "decision_sensitivity_score", label: "Decision sensitivity" },
] as const

export function Questions({
  workflowId,
  setModal,
  setPage,
  orgUsers,
  totalCases,
  refreshKey,
}: {
  workflowId: string | null
  setModal: (m: Modal) => void
  setPage: (p: Page) => void
  orgUsers: OrgUser[] | null
  totalCases: number | null
  refreshKey: number
}) {
  const { user, hasPermission } = useAuth()
  const [search, setSearch] = useState("")
  const [selected, setSelected] = useState<string[]>([])
  const [detailId, setDetailId] = useState<string | null>(null)
  const [tab, setTab] = useState<"Rationale" | "Evidence" | "Answer" | "History">("Rationale")
  const [assigning, setAssigning] = useState(false)

  const { data, loading, error, reload } = useFetch(
    () =>
      workflowId
        ? decisionIntelligenceApi.listQuestions({ workflow_id: workflowId, sort_by: "priority_score", limit: 200 })
        : Promise.resolve(null),
    [workflowId, refreshKey],
  )
  const questions = data?.questions ?? []

  useEffect(() => {
    if (questions.length > 0 && (!detailId || !questions.some((q) => q.id === detailId))) {
      setDetailId(questions[0].id)
    }
    if (questions.length === 0) setDetailId(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questions.map((q) => q.id).join(",")])

  const detail = useFetch<QuestionDetail | null>(
    () => (detailId ? decisionIntelligenceApi.getQuestion(detailId) : Promise.resolve(null)),
    [detailId],
  )
  const answers = useFetch<Answer[] | null>(
    () => (detailId ? decisionIntelligenceApi.listAnswers(detailId) : Promise.resolve(null)),
    [detailId],
  )

  const [scores, setScores] = useState<Record<string, string>>({})
  const [scoreError, setScoreError] = useState<string | null>(null)
  const [savingScores, setSavingScores] = useState(false)

  useEffect(() => {
    setAssigning(false)
  }, [detailId])

  useEffect(() => {
    if (!detail.data) return
    const q = detail.data.question
    setScores({
      reach_score: q.reach_score?.toString() ?? "",
      impact_score: q.impact_score?.toString() ?? "",
      risk_score: q.risk_score?.toString() ?? "",
      answerability_score: q.answerability_score?.toString() ?? "",
      decision_sensitivity_score: q.decision_sensitivity_score?.toString() ?? "",
    })
    // Only re-seed inputs when a DIFFERENT question is opened, not on
    // every background refresh of the same one -- avoids clobbering an
    // in-progress edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailId])

  const visible = questions.filter((q) => q.title.toLowerCase().includes(search.toLowerCase()))
  const q: Question | undefined = detail.data?.question

  async function handleSaveScores() {
    if (!q) return
    setSavingScores(true)
    setScoreError(null)
    try {
      const payload: Record<string, number> = {}
      for (const { key } of SCORE_FIELDS) {
        const raw = scores[key]
        if (raw !== "" && raw !== undefined) {
          const n = Number(raw)
          if (Number.isNaN(n) || n < 0 || n > 100) throw new Error(`${key.replaceAll("_", " ")} must be a number between 0 and 100.`)
          payload[key] = n
        }
      }
      await decisionIntelligenceApi.updateQuestion(q.id, payload)
      const allFilled = SCORE_FIELDS.every(({ key }) => scores[key] !== "")
      if (allFilled) await decisionIntelligenceApi.scoreQuestion(q.id)
      detail.reload()
      reload()
    } catch (err) {
      setScoreError(err instanceof Error ? err.message : errorMessage(err))
    } finally {
      setSavingScores(false)
    }
  }

  async function bulkAssign(ownerUserId: string) {
    await Promise.all(selected.map((id) => decisionIntelligenceApi.updateQuestion(id, { owner_user_id: ownerUserId })))
    setSelected([])
    reload()
  }

  if (!workflowId) {
    return (
      <>
        <PageTitle title="Priority Questions" description="Discover which unanswered questions matter most." />
        <EmptyPanel title="No workflow selected" body="Choose or create a workflow first." />
      </>
    )
  }

  return (
    <>
      <PageTitle
        title="Priority Questions"
        description="Discover which unanswered questions could resolve the most recurring uncertainty across your AI workflow."
        actions={
          hasPermission("di_question.manage") ? (
            <Button kind="primary" icon="plus" onClick={() => setModal("new-question")}>
              New question
            </Button>
          ) : undefined
        }
      />
      <div className="explain-strip">
        <div>
          <strong>How ranking works</strong>
          <span>
            priority = 0.30×reach + 0.30×impact + 0.20×risk + 0.10×answerability + 0.10×decision sensitivity. Any unscored
            dimension leaves the whole question "not yet assessed," never a fabricated number.
          </span>
        </div>
      </div>
      {error && <ErrorNote message={error} />}
      <section className="panel table-panel">
        <TableToolbar search={search} setSearch={setSearch} resultsLabel={loading ? "Loading…" : `${visible.length} questions`} />
        {selected.length > 0 && hasPermission("di_question.manage") && (
          <div className="bulk-bar">
            <strong>{selected.length} selected</strong>
            {orgUsers && orgUsers.length > 0 ? (
              <select onChange={(e) => e.target.value && bulkAssign(e.target.value)} defaultValue="">
                <option value="" disabled>
                  Assign owner…
                </option>
                {orgUsers.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                  </option>
                ))}
              </select>
            ) : (
              <span style={{ fontSize: 10, color: "var(--muted)" }}>Owner lookup requires the Owner role.</span>
            )}
            <Button onClick={() => setSelected([])}>Clear selection</Button>
          </div>
        )}
        <div className="table-scroll">
          <table className="question-table">
            <thead>
              <tr>
                <th></th>
                <th>Question</th>
                <th>Impact</th>
                <th>Risk</th>
                <th>Priority</th>
                <th>Evidence</th>
                <th>Owner</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((item) => (
                <tr key={item.id} className={detailId === item.id ? "active-row" : ""} onClick={() => setDetailId(item.id)}>
                  <td>
                    <input
                      aria-label={`Select ${item.title}`}
                      type="checkbox"
                      checked={selected.includes(item.id)}
                      onChange={() => setSelected(selected.includes(item.id) ? selected.filter((x) => x !== item.id) : [...selected, item.id])}
                      onClick={(e) => e.stopPropagation()}
                    />
                  </td>
                  <td>
                    <strong>{item.title}</strong>
                  </td>
                  <td>
                    <ScoreBand score={item.impact_score} />
                  </td>
                  <td>
                    <ScoreBand score={item.risk_score} />
                  </td>
                  <td>
                    <PriorityScoreCell score={item.priority_score} scoringVersion={item.scoring_version} />
                  </td>
                  <td>
                    <QuestionEvidenceCell questionId={item.id} totalCases={totalCases} />
                  </td>
                  <td>{orgUsers?.find((u) => u.id === item.owner_user_id)?.name ?? (item.owner_user_id ? item.owner_user_id.slice(0, 8) : "Unassigned")}</td>
                  <td>
                    <Badge tone="info">{QUESTION_STATUS_LABELS[item.status]}</Badge>
                  </td>
                </tr>
              ))}
              {!loading && visible.length === 0 && (
                <tr>
                  <td colSpan={8} style={{ textAlign: "center", color: "var(--muted)" }}>
                    No questions yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {q && (
        <section className="panel detail-panel">
          <div className="detail-head">
            <div>
              <div className="eyebrow">Question {q.id.slice(0, 8)}</div>
              <h2>{q.title}</h2>
              <div className="inline-meta">
                <Badge tone="info">{QUESTION_STATUS_LABELS[q.status]}</Badge>
                <span>Owner: {orgUsers?.find((u) => u.id === q.owner_user_id)?.name ?? (q.owner_user_id ?? "Unassigned")}</span>
                <span>Updated {new Date(q.updated_at).toLocaleDateString()}</span>
              </div>
            </div>
            {hasPermission("di_question.manage") && (
              <div>
                <Button onClick={() => setAssigning(!assigning)}>Assign owner</Button>
                {q.status === "proposed" || q.status === "in_analysis" || q.status === "awaiting_answer" ? (
                  <Button
                    kind="primary"
                    onClick={async () => {
                      await decisionIntelligenceApi.submitQuestionForReview(q.id)
                      detail.reload()
                      reload()
                    }}
                  >
                    Submit for review
                  </Button>
                ) : q.status === "logic_validated" || q.status === "replay_completed" ? (
                  <Button
                    kind="primary"
                    onClick={async () => {
                      await decisionIntelligenceApi.markQuestionReadyForReview(q.id)
                      detail.reload()
                      reload()
                    }}
                  >
                    Mark ready for review
                  </Button>
                ) : q.status === "ready_for_review" ? (
                  <Button
                    kind="primary"
                    onClick={async () => {
                      if (!confirm("Approve this question for operational use? This is a real, permission-gated transition.")) return
                      await decisionIntelligenceApi.approveQuestionForOperationalUse(q.id)
                      detail.reload()
                      reload()
                    }}
                  >
                    Approve for operational use
                  </Button>
                ) : null}
              </div>
            )}
          </div>
          {assigning && (
            <div className="form-body" style={{ borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)" }}>
              {orgUsers && orgUsers.length > 0 ? (
                <label>
                  Authoritative owner
                  <select
                    defaultValue={q.owner_user_id ?? ""}
                    onChange={async (e) => {
                      await decisionIntelligenceApi.updateQuestion(q.id, { owner_user_id: e.target.value })
                      setAssigning(false)
                      detail.reload()
                      reload()
                    }}
                  >
                    <option value="">Unassigned</option>
                    {orgUsers.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.name}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <span style={{ fontSize: 11, color: "var(--muted)" }}>
                  Looking up team members to assign requires the Owner role (<code>users.manage</code>).
                </span>
              )}
            </div>
          )}
          <div className="tabs">
            {(["Rationale", "Evidence", "Answer", "History"] as const).map((t) => (
              <button className={tab === t ? "active" : ""} onClick={() => setTab(t)} key={t}>
                {t}
              </button>
            ))}
          </div>
          {tab === "Rationale" && (
            <div>
              <div className="rationale-grid">
                {SCORE_FIELDS.map(({ key, label }) => (
                  <ScoreValue key={key} label={label} score={(q as unknown as Record<string, number | null>)[key]} />
                ))}
              </div>
              {hasPermission("di_question.manage") && (
                <div className="form-body" style={{ borderTop: "1px solid var(--border)" }}>
                  <strong style={{ fontSize: 11, display: "block", marginBottom: 10 }}>Score this question (0-100 each)</strong>
                  <div className="form-grid">
                    {SCORE_FIELDS.map(({ key, label }) => (
                      <label key={key}>
                        {label}
                        <input
                          type="number"
                          min={0}
                          max={100}
                          value={scores[key] ?? ""}
                          onChange={(e) => setScores({ ...scores, [key]: e.target.value })}
                        />
                      </label>
                    ))}
                  </div>
                  {scoreError && <ErrorNote message={scoreError} />}
                  <Button kind="primary" onClick={handleSaveScores} disabled={savingScores}>
                    {savingScores ? "Saving…" : "Save scores"}
                  </Button>
                </div>
              )}
            </div>
          )}
          {tab === "Evidence" && (
            <div className="evidence-layout">
              <div>
                <h3>Linked patterns</h3>
                {detail.data!.patterns.length === 0 && <p>No patterns linked yet.</p>}
                {detail.data!.patterns.map((p) => (
                  <button className="evidence-ref" key={p.id} onClick={() => setPage("Patterns")}>
                    <span>
                      <strong>{p.name}</strong>
                      <small>{p.review_status}</small>
                    </span>
                  </button>
                ))}
                <h3 style={{ marginTop: 16 }}>Linked cases</h3>
                <p>{linkedCaseSummary(detail.data!.case_ids.length, totalCases)} linked as evidence for this question.</p>
                <button className="evidence-ref" onClick={() => setPage("Cases")}>
                  <span>
                    <strong>Open Cases</strong>
                    <small>View the underlying case records</small>
                  </span>
                </button>
              </div>
              <div className="missing-box">
                <strong>Evidence foundation</strong>
                <p>Every figure above is read live from this workflow's real linked records -- nothing here is estimated.</p>
              </div>
            </div>
          )}
          {tab === "Answer" && (
            <AnswerPanel questionId={q.id} answers={answers.data ?? []} reload={() => { answers.reload(); detail.reload(); reload() }} currentUserId={user?.id ?? null} canSubmit={hasPermission("di_answer.submit")} canApprove={hasPermission("di_answer.approve")} />
          )}
          {tab === "History" && (
            <div className="timeline">
              {(answers.data ?? []).length === 0 && <div style={{ padding: "0 0 16px" }}>No answers recorded yet.</div>}
              {(answers.data ?? []).map((a) => (
                <div key={a.id}>
                  <i />
                  <strong>
                    Answer v{a.version} · {a.status}
                  </strong>
                  <span>
                    {a.submitted_at ? `Submitted ${new Date(a.submitted_at).toLocaleString()}` : "Not submitted yet"}
                    {a.decided_at ? ` · Decided ${new Date(a.decided_at).toLocaleString()}` : ""}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </>
  )
}

function QuestionEvidenceCell({ questionId, totalCases }: { questionId: string; totalCases: number | null }) {
  const { data } = useFetch(() => decisionIntelligenceApi.getQuestion(questionId), [questionId])
  if (!data) return <span className="score-pending">—</span>
  return <span>{linkedCaseSummary(data.case_ids.length, totalCases)}</span>
}

export function AnswerPanel({
  questionId,
  answers,
  reload,
  currentUserId,
  canSubmit,
  canApprove,
}: {
  questionId: string
  answers: Answer[]
  reload: () => void
  currentUserId: string | null
  canSubmit: boolean
  canApprove: boolean
}) {
  const latest = answers[answers.length - 1]
  const [content, setContent] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function createDraft() {
    if (!content.trim()) return
    setBusy(true)
    setError(null)
    try {
      await decisionIntelligenceApi.createDraftAnswer(questionId, { content: content.trim() })
      setContent("")
      reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function act(fn: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await fn()
      reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const isSelfApprove = !!latest && !!currentUserId && latest.author_user_id === currentUserId

  return (
    <div className="answer-box">
      {!latest && canSubmit && (
        <div className="form-body" style={{ padding: 0 }}>
          <label>
            Draft an authoritative answer
            <textarea value={content} onChange={(e) => setContent(e.target.value)} placeholder="What is the authoritative answer to this question?" />
          </label>
          {error && <ErrorNote message={error} />}
          <Button kind="primary" onClick={createDraft} disabled={busy}>
            {busy ? "Saving…" : "Save draft answer"}
          </Button>
        </div>
      )}
      {latest && (
        <>
          <div className="ai-label">Answer v{latest.version} · {latest.status}</div>
          <h3>{latest.content}</h3>
          {error && <ErrorNote message={error} />}
          {isSelfApprove && latest.status === "submitted" && (
            <div className="callout">
              <strong>Separation of duties</strong>
              <span>
                You authored this answer, so you cannot also approve it. This platform requires a different reviewer to
                approve any answer you submit -- enforced server-side, not just hidden here.
              </span>
            </div>
          )}
          <div className="answer-actions">
            {latest.status === "draft" && canSubmit && (
              <Button kind="primary" onClick={() => act(() => decisionIntelligenceApi.submitAnswer(latest.id))} disabled={busy}>
                Submit for approval
              </Button>
            )}
            {latest.status === "submitted" && canApprove && (
              <>
                <Button kind="danger" onClick={() => act(() => decisionIntelligenceApi.rejectAnswer(latest.id))} disabled={busy}>
                  Reject
                </Button>
                <Button
                  kind="primary"
                  onClick={() => act(() => decisionIntelligenceApi.approveAnswer(latest.id))}
                  disabled={busy || isSelfApprove}
                  title={isSelfApprove ? "You authored this answer and cannot approve it yourself" : undefined}
                >
                  {isSelfApprove ? "Cannot approve your own answer" : "Approve"}
                </Button>
              </>
            )}
            {(latest.status === "approved" || latest.status === "rejected") && canSubmit && (
              <Button onClick={() => setContent(latest.content)} disabled={busy}>
                Draft a superseding answer
              </Button>
            )}
          </div>
          {content && (latest.status === "approved" || latest.status === "rejected") && (
            <div className="form-body" style={{ padding: "12px 0 0" }}>
              <textarea value={content} onChange={(e) => setContent(e.target.value)} />
              <Button
                kind="primary"
                onClick={() => act(() => decisionIntelligenceApi.supersedeAnswer(latest.id, { content }))}
                disabled={busy}
              >
                Save superseding answer
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
