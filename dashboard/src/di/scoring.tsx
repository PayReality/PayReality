import { Badge } from "../components/ui"

/**
 * The backend's five scoring dimensions (reach/impact/risk/
 * answerability/decision_sensitivity) and the combined priority_score
 * are nullable 0-100 floats (scoring.py's hard contract: ANY missing
 * input makes the whole priority_score null, never a default/average).
 * The design shows qualitative High/Medium/Low bands; this is the one
 * banding applied everywhere, consistently: >=70 High, >=40 Medium,
 * else Low. A null score is never banded -- it renders as "Not yet
 * assessed," exactly as scoring.py's own docstring requires, never as a
 * silent Low/0.
 */
export type Band = "High" | "Medium" | "Low"

export function bandFor(score: number | null): Band | null {
  if (score === null || score === undefined) return null
  if (score >= 70) return "High"
  if (score >= 40) return "Medium"
  return "Low"
}

export function bandTone(band: Band): string {
  if (band === "High") return "warning"
  if (band === "Medium") return "info"
  return "neutral"
}

/** A single dimension score, rendered as a band badge or "Not yet assessed." */
export function ScoreBand({ score }: { score: number | null }) {
  const band = bandFor(score)
  if (band === null) return <span className="score-pending">Not yet assessed</span>
  return <Badge tone={bandTone(band)}>{band}</Badge>
}

/** The raw 0-100 number alongside its band, for detail views. */
export function ScoreValue({ label, score }: { label: string; score: number | null }) {
  return (
    <div className="why-card">
      <span>{label}</span>
      {score === null ? (
        <strong className="score-pending" style={{ fontSize: 13 }}>
          Not yet assessed
        </strong>
      ) : (
        <strong>
          {score.toFixed(0)} <span style={{ fontWeight: 400, color: "var(--muted)", fontSize: 11 }}>/ 100 · {bandFor(score)}</span>
        </strong>
      )}
    </div>
  )
}

/** priority_score, the combined figure -- same null discipline. */
export function PriorityScoreCell({ score, scoringVersion }: { score: number | null; scoringVersion: string | null }) {
  if (score === null) return <span className="score-pending">Not yet assessed</span>
  return (
    <span>
      <strong>{score.toFixed(1)}</strong>
      {scoringVersion && <span style={{ color: "var(--muted)", fontSize: 10 }}> ({scoringVersion})</span>}
    </span>
  )
}

/**
 * The design's mock "evidence: 72%" column doesn't map to any real
 * backend field. Rather than fabricate an "evidence confidence"
 * statistic, this renders the one honest, computable stand-in: how many
 * of the workflow's cases are actually linked to this question as
 * evidence, out of the workflow's total case count. Returns null (render
 * as "—") when the total case count isn't known yet.
 */
export function linkedCaseSummary(linkedCount: number, totalCases: number | null): string {
  if (totalCases === null) return `${linkedCount} linked`
  return `${linkedCount} / ${totalCases} cases`
}
