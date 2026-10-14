import { useState } from "react"
import { Badge, Button, ErrorNote, Icon } from "./ui"
import { decisionIntelligenceApi } from "../di/api"
import { useFetch, errorMessage } from "../lib/useAsync"
import { useAuth } from "../auth/AuthContext"
import type { Page } from "../types"

export function CaseDrawer({ id, close, setPage }: { id: string; close: () => void; setPage: (p: Page) => void }) {
  const { hasPermission } = useAuth()
  const [tab, setTab] = useState<"Summary" | "Facts" | "Evidence">("Summary")
  const { data: theCase, loading, error, reload } = useFetch(() => decisionIntelligenceApi.getCase(id), [id])
  const [status, setStatus] = useState<string>("")
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  async function updateStatus(next: string) {
    setSaving(true)
    setSaveError(null)
    try {
      await decisionIntelligenceApi.updateCase(id, { status: next })
      reload()
    } catch (err) {
      setSaveError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="overlay" onMouseDown={close}>
      <aside className="drawer" onMouseDown={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <div className="eyebrow">Case record</div>
            <h2>{theCase?.external_ref ?? id.slice(0, 8)}</h2>
            <p>{theCase ? new Date(theCase.created_at).toLocaleString() : ""}</p>
          </div>
          <button className="icon-btn" title="Close case" onClick={close}>
            <Icon name="close" />
          </button>
        </div>
        <div className="tabs">
          {(["Summary", "Facts", "Evidence"] as const).map((t) => (
            <button className={tab === t ? "active" : ""} onClick={() => setTab(t)} key={t}>
              {t}
            </button>
          ))}
        </div>
        {loading && <div className="drawer-content">Loading…</div>}
        {error && (
          <div className="drawer-content">
            <ErrorNote message={error} />
          </div>
        )}
        {theCase && tab === "Summary" && (
          <div className="drawer-content">
            <div className="status-grid">
              <div>
                <span>Status</span>
                <strong>
                  <Badge tone={theCase.status === "escalated" ? "warning" : theCase.status === "resolved" ? "success" : "neutral"}>
                    {theCase.status}
                  </Badge>
                </strong>
              </div>
              <div>
                <span>Outcome</span>
                <strong>{theCase.outcome ?? "Not recorded"}</strong>
              </div>
              <div>
                <span>Escalation reason</span>
                <strong>{theCase.escalation_reason ?? "—"}</strong>
              </div>
              <div>
                <span>Recorded baseline decision</span>
                <strong>{theCase.human_decision ? JSON.stringify(theCase.human_decision) : "Not recorded"}</strong>
              </div>
            </div>
            {hasPermission("di_case.manage") && (
              <div className="content-block">
                <h3>Change status</h3>
                {saveError && <ErrorNote message={saveError} />}
                <select value={status || theCase.status} onChange={(e) => { setStatus(e.target.value); updateStatus(e.target.value) }} disabled={saving}>
                  <option value="open">Open</option>
                  <option value="resolved">Resolved</option>
                  <option value="escalated">Escalated</option>
                </select>
              </div>
            )}
          </div>
        )}
        {theCase && tab === "Facts" && (
          <div className="drawer-content">
            <div className="content-block">
              <h3>Recorded facts</h3>
              <pre style={{ whiteSpace: "pre-wrap", fontSize: 11, background: "var(--surface-subtle)", padding: 12, borderRadius: 7 }}>
                {JSON.stringify(theCase.facts, null, 2)}
              </pre>
            </div>
            {theCase.ai_recommendation && (
              <div className="content-block">
                <h3>AI recommendation</h3>
                <pre style={{ whiteSpace: "pre-wrap", fontSize: 11, background: "var(--surface-subtle)", padding: 12, borderRadius: 7 }}>
                  {JSON.stringify(theCase.ai_recommendation, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
        {theCase && tab === "Evidence" && (
          <div className="drawer-content">
            {theCase.evidence_refs && theCase.evidence_refs.length > 0 ? (
              theCase.evidence_refs.map((ref, i) => (
                <div className="evidence-source" key={i}>
                  <Badge tone="success">Evidence reference</Badge>
                  <p>{JSON.stringify(ref)}</p>
                </div>
              ))
            ) : (
              <div className="content-block">
                <p>No evidence references recorded for this case.</p>
              </div>
            )}
          </div>
        )}
        <div className="drawer-footer">
          <Button
            onClick={() => {
              close()
              setPage("Patterns")
            }}
          >
            View patterns
          </Button>
          <Button
            kind="primary"
            onClick={() => {
              close()
              setPage("Questions")
            }}
          >
            Open related questions
          </Button>
        </div>
      </aside>
    </div>
  )
}
