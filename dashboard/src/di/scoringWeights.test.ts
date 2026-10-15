import { describe, expect, it } from "vitest"
import { sumWeights, validateWeights, weightsSumToOne } from "./scoringWeights"
import { DEFAULT_SCORING_WEIGHTS } from "./types"
import type { ScoringWeights } from "./types"

describe("scoring weights client-side validation (mirrors scoring.validate_weights)", () => {
  it("accepts the real backend default weights, which sum to exactly 1.0", () => {
    expect(sumWeights(DEFAULT_SCORING_WEIGHTS)).toBeCloseTo(1.0, 10)
    expect(weightsSumToOne(DEFAULT_SCORING_WEIGHTS)).toBe(true)
    expect(validateWeights(DEFAULT_SCORING_WEIGHTS)).toBeNull()
  })

  it("rejects a set that sums to less than 1.0", () => {
    const weights: ScoringWeights = { reach: 0.2, impact: 0.2, risk: 0.2, answerability: 0.1, decision_sensitivity: 0.1 }
    expect(sumWeights(weights)).toBeCloseTo(0.8, 10)
    expect(weightsSumToOne(weights)).toBe(false)
    expect(validateWeights(weights)).toMatch(/must sum to 1\.0/)
  })

  it("rejects a set that sums to more than 1.0", () => {
    const weights: ScoringWeights = { reach: 0.5, impact: 0.5, risk: 0.5, answerability: 0.3, decision_sensitivity: 0.3 }
    expect(weightsSumToOne(weights)).toBe(false)
  })

  it("accepts a set within the backend's own 0.001 floating-point tolerance", () => {
    const weights: ScoringWeights = {
      reach: 0.30001,
      impact: 0.3,
      risk: 0.2,
      answerability: 0.1,
      decision_sensitivity: 0.1,
    }
    expect(weightsSumToOne(weights)).toBe(true)
  })

  it("rejects a negative weight even when the sum happens to be 1.0", () => {
    const weights: ScoringWeights = { reach: 0.5, impact: 0.5, risk: 0.2, answerability: 0.1, decision_sensitivity: -0.3 }
    expect(sumWeights(weights)).toBeCloseTo(1.0, 10)
    expect(validateWeights(weights)).toMatch(/non-negative/)
  })

  it("re-derives validity purely from the live sum, so a UI can gate Save on it directly", () => {
    const weights: ScoringWeights = { reach: 0.4, impact: 0.3, risk: 0.2, answerability: 0.05, decision_sensitivity: 0.05 }
    expect(weightsSumToOne(weights)).toBe(true)
    const edited = { ...weights, reach: 0.41 }
    expect(weightsSumToOne(edited)).toBe(false)
  })
})
