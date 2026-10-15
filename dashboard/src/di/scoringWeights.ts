import { SCORING_WEIGHT_SUM_TOLERANCE } from "./types"
import type { ScoringWeights } from "./types"

// Pure helpers, deliberately separated from the form component so they can
// be unit-tested directly and so the client-side check can never silently
// drift from scoring.validate_weights (same tolerance, same "every weight
// non-negative" rule, same "all five required" rule).
export const WEIGHT_DIMENSIONS = ["reach", "impact", "risk", "answerability", "decision_sensitivity"] as const

export function sumWeights(weights: ScoringWeights): number {
  return WEIGHT_DIMENSIONS.reduce((total, dimension) => total + (Number(weights[dimension]) || 0), 0)
}

/** Mirrors scoring.validate_weights exactly: every dimension non-negative, and the five sum to 1.0 within tolerance. */
export function validateWeights(weights: ScoringWeights): string | null {
  for (const dimension of WEIGHT_DIMENSIONS) {
    const value = weights[dimension]
    if (value === null || value === undefined || Number.isNaN(Number(value)) || Number(value) < 0) {
      return `${dimension.replaceAll("_", " ")} must be a non-negative number.`
    }
  }
  const total = sumWeights(weights)
  if (Math.abs(total - 1.0) > SCORING_WEIGHT_SUM_TOLERANCE) {
    return `The five weights must sum to 1.0 -- they currently sum to ${total.toFixed(3)}.`
  }
  return null
}

export function weightsSumToOne(weights: ScoringWeights): boolean {
  return validateWeights(weights) === null
}
