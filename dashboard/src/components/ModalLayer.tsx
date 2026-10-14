import { useEffect, useState } from "react"
import { Badge, Button, ErrorNote, Icon } from "./ui"
import { decisionIntelligenceApi } from "../di/api"
import type { Case, Pattern, Question } from "../di/types"
import { errorMessage } from "../lib/useAsync"
import type { Modal, Page } from "../types"
import type { OrgUser } from "../users/types"

export function ModalLayer({
  modal,
  close,
  setPage,
  workflowId,
  orgUsers,
  onQuestionCreated,
}: {
  modal: Modal
  close: () => void
  setPage: (p: Page) => void
  workflowId: string | null
  orgUsers: OrgUser[] | null
  onQuestionCreated: () => void
}) {
  if (!modal) return null
  const title =
    modal === "search"
      ? "Search this workflow"
      : modal === "export-info"
        ? "Export report"
        : modal === "new-question"
          ? "Create a priority question"
          : "Notifications"
  return (
    <div className="overlay modal-overlay" onMouseDown={close}>
      <div className={`modal ${modal === "search" ? "search-modal" : ""}`} onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h2>{title}</h2>
          </div>
          <button className="icon-btn" title="Close dialog" onClick={close}>
            <Icon name="close" />
          </button>
        </div>
        {modal === "search" && <SearchBody workflowId={workflowId} close={close} setPage={setPage} />}
        {modal === "notifications-info" && (
          <div className="form-body">
            <div className="not-available">
              In-app notifications aren't implemented in the backend yet -- there's no notification endpoint to show real
              data from, so this stays an honest placeholder rather than a fabricated activity feed.
            </div>
          </div>
        )}
        {modal === "export-info" && (
          <div className="form-body">
            <div className="not-available">
              <Icon name="download" />
              <span>
                No export/report-generation endpoint exists on the backend yet. See the Reports page for the one real
                report (a per-workflow overview) this backend currently provides.
              </span>
            </div>
          </div>
        )}
        {modal === "new-question" && <NewQuestionBody workflowId={workflowId} orgUsers={orgUsers} close={close} onCreated={onQuestionCreated} />}
      </div>
    </div>
  )
}

function SearchBody({ workflowId, close, setPage }: { workflowId: string | null; close: () => void; setPage: (p: Page) => void }) {
  const [query, setQuery] = useState("")
  const [questions, setQuestions] = useState<Question[]>([])
  const [patterns, setPatterns] = useState<Pattern[]>([])
  const [cases, setCases] = useState<Case[]>([])

  useEffect(() => {
    if (!workflowId) return
    decisionIntelligenceApi.listQuestions({ workflow_id: workflowId, limit: 200 }).then((p) => setQuestions(p.questions))
    decisionIntelligenceApi.listPatterns({ workflow_id: workflowId, limit: 200 }).then((p) => setPatterns(p.patterns))
    decisionIntelligenceApi.listCases({ workflow_id: workflowId, limit: 200 }).then((p) => setCases(p.cases))
  }, [workflowId])

  const q = query.toLowerCase()
  const questionResults = q ? questions.filter((x) => x.title.toLowerCase().includes(q)) : []
  const patternResults = q ? patterns.filter((x) => x.name.toLowerCase().includes(q)) : []
  const caseResults = q ? cases.filter((x) => (x.external_ref ?? "").toLowerCase().includes(q)) : []

  return (
    <div>
      <label className="modal-search">
        <Icon name="search" />
        <input autoFocus placeholder="Search cases, patterns, questions…" value={query} onChange={(e) => setQuery(e.target.value)} />
      </label>
      <div className="search-filters">
        <Badge tone="info">Within the selected workflow</Badge>
      </div>
      <div className="search-results">
        {questionResults.map((x) => (
          <button
            key={`q-${x.id}`}
            onClick={() => {
              close()
              setPage("Questions")
            }}
          >
            <span>Question</span>
            <strong>{x.title}</strong>
            <Icon name="chevron" />
          </button>
        ))}
        {patternResults.map((x) => (
          <button
            key={`p-${x.id}`}
            onClick={() => {
              close()
              setPage("Patterns")
            }}
          >
            <span>Pattern</span>
            <strong>{x.name}</strong>
            <Icon name="chevron" />
          </button>
        ))}
        {caseResults.map((x) => (
          <button
            key={`c-${x.id}`}
            onClick={() => {
              close()
              setPage("Cases")
            }}
          >
            <span>Case</span>
            <strong>{x.external_ref ?? x.id.slice(0, 8)}</strong>
            <Icon name="chevron" />
          </button>
        ))}
        {q && questionResults.length + patternResults.length + caseResults.length === 0 && (
          <div style={{ padding: 16, color: "var(--muted)", fontSize: 11 }}>No matches in this workflow.</div>
        )}
      </div>
    </div>
  )
}

function NewQuestionBody({
  workflowId,
  orgUsers,
  close,
  onCreated,
}: {
  workflowId: string | null
  orgUsers: OrgUser[] | null
  close: () => void
  onCreated: () => void
}) {
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [ownerId, setOwnerId] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function submit() {
    if (!workflowId || !title.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await decisionIntelligenceApi.createQuestion({
        workflow_id: workflowId,
        title: title.trim(),
        description: description.trim() || undefined,
        owner_user_id: ownerId || undefined,
      })
      onCreated()
      close()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <div className="form-body">
        <label>
          Question text *
          <textarea
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="What authoritative answer could resolve this recurring uncertainty?"
          />
        </label>
        <label>
          Why it may matter
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Describe the cases and decisions potentially affected." />
        </label>
        {orgUsers && orgUsers.length > 0 && (
          <label>
            Proposed owner
            <select value={ownerId} onChange={(e) => setOwnerId(e.target.value)}>
              <option value="">Unassigned</option>
              {orgUsers.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {error && <ErrorNote message={error} />}
      </div>
      <div className="modal-footer">
        <Button onClick={close}>Cancel</Button>
        <Button kind="primary" onClick={submit} disabled={submitting || !title.trim()}>
          {submitting ? "Creating…" : "Create question"}
        </Button>
      </div>
    </>
  )
}
