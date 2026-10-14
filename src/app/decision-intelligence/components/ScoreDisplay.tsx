/**
 * Renders one priority-scoring dimension (scoring.py: reach/impact/risk/
 * answerability/decision_sensitivity, each 0-100, or the combined
 * priority_score). Hard contract carried over from the backend's own
 * (scoring.py's module docstring): a `null` score means missing
 * evidence -- nobody has judged that dimension yet -- and must always
 * read as "Not yet assessed," visibly distinct from a real 0 (the
 * lowest possible judged score) or a blank cell that could be mistaken
 * for "confirmed absent."
 */
export function ScoreDisplay({ label, value, size = "md" }: { label: string; value: number | null; size?: "sm" | "md" }) {
  const fontSize = size === "sm" ? 12 : 13;
  return (
    <div>
      <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>{label}</p>
      {value === null ? (
        <p style={{ fontSize, fontStyle: "italic", color: "var(--pr-text-disabled)" }}>Not yet assessed</p>
      ) : (
        <p style={{ fontSize, fontWeight: 600, color: "var(--pr-text-primary)" }}>{value.toFixed(0)}<span style={{ fontWeight: 400, color: "var(--pr-text-muted)" }}> / 100</span></p>
      )}
    </div>
  );
}

/** The combined priority_score cell for a list row -- same null handling, more compact. */
export function PriorityScoreCell({ value, scoringVersion }: { value: number | null; scoringVersion: string | null }) {
  if (value === null) {
    return (
      <span style={{ fontStyle: "italic", color: "var(--pr-text-disabled)", fontSize: 13 }}>
        Needs scoring
      </span>
    );
  }
  return (
    <span style={{ fontSize: 13, color: "var(--pr-text-primary)" }}>
      <strong>{value.toFixed(1)}</strong>
      {scoringVersion && <span style={{ color: "var(--pr-text-disabled)", fontSize: 11 }}> ({scoringVersion})</span>}
    </span>
  );
}
