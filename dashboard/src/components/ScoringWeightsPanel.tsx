import { useEffect, useState } from "react"
import { Badge, Button, ErrorNote } from "./ui"
import { decisionIntelligenceApi } from "../di/api"
import type { ScoringWeights } from "../di/types"
import { WEIGHT_DIMENSIONS, sumWeights, validateWeights } from "../di/scoringWeights"
import { useFetch, errorMessage } from "../lib/useAsync"
import { useAuth } from "../auth/AuthContext"

const DIMENSION_LABELS: Record<(typeof WEIGHT_DIMENSIONS)[number], string> = {
  reach: "Reach",
  impact: "Impact",
  risk: "Risk",
  answerability: "Answerability",
  decision_sensitivity: "Decision sensitivity",
}

// Feature: Settings - real configurable scoring weights (scoring_config.py).
// Gated honestly on the real permission (`di_settings.manage`) the same
// backend route is gated on -- a user without it never sees an editable
// form that would just 403 on save, mirroring how People & Ownership
// already degrades for `users.manage`.
export function ScoringWeightsPanel() {
  const { hasPermission } = useAuth()
  const canManage = hasPermission("di_settings.manage")
  const { data, loading, error, reload } = useFetch(
    () => (canManage ? decisionIntelligenceApi.getScoringConfig() : Promise.resolve(null)),
    [canManage],
  )
  const [form, setForm] = useState<ScoringWeights | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (data) setForm(data.weights)
  }, [data])

  if (!canManage) {
    return (
      <div className="permission-note">
        Configuring scoring weights requires the <code>di_settings.manage</code> permission (Governance Administrator
        or Owner). Your current role doesn't hold it, so this control isn't shown as editable -- this is the real
        backend's own access rule, not a missing feature.
      </div>
    )
  }

  if (loading && !form) {
    return <div style={{ color: "var(--muted)", fontSize: 12 }}>Loading scoring configuration…</div>
  }
  if (error) return <ErrorNote message={error} />
  if (!form) return null

  const total = sumWeights(form)
  const validationError = validateWeights(form)

  async function save() {
    if (!form || validateWeights(form)) return
    setSaving(true)
    setSaveError(null)
    setSaved(false)
    try {
      const updated = await decisionIntelligenceApi.updateScoringConfig(form)
      setForm(updated.weights)
      setSaved(true)
      reload()
    } catch (err) {
      setSaveError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <Badge tone={data?.is_default ? "neutral" : "success"}>
          {data?.is_default ? "Using default weights" : "Custom configuration"}
        </Badge>
        <span style={{ fontSize: 10, color: "var(--muted)" }}>
          Scoring version {data?.scoring_version}
          {data && !data.is_default && data.updated_at && ` -- last updated ${new Date(data.updated_at).toLocaleString()}`}
        </span>
      </div>
      <div className="not-available" style={{ marginBottom: 14 }}>
        Changing these weights only affects questions scored (or re-scored) from now on -- it never retroactively
        changes an already-computed priority_score on an existing question.
      </div>
      <div className="form-grid">
        {WEIGHT_DIMENSIONS.map((dimension) => (
          <label key={dimension}>
            {DIMENSION_LABELS[dimension]}
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={form[dimension]}
              onChange={(e) => {
                setSaved(false)
                setForm({ ...form, [dimension]: Number(e.target.value) })
              }}
            />
          </label>
        ))}
      </div>
      <div style={{ fontSize: 11, marginBottom: 10, color: validationError ? "var(--red)" : "var(--text-2)" }}>
        Sum: {total.toFixed(3)} {validationError ? `-- ${validationError}` : "-- valid, sums to 1.0"}
      </div>
      {saveError && <ErrorNote message={saveError} />}
      {saved && !saveError && (
        <div className="success" style={{ marginBottom: 12 }}>
          <span>
            <strong>Scoring configuration saved.</strong>
          </span>
        </div>
      )}
      <Button kind="primary" onClick={save} disabled={saving || !!validationError}>
        {saving ? "Saving…" : "Save scoring weights"}
      </Button>
    </div>
  )
}
