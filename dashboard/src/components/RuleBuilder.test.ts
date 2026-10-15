import { describe, expect, it } from "vitest"
import { builderStateToSchema, schemaToBuilderState } from "./RuleBuilder"
import type { RuleSchema } from "../di/types"

describe("RuleBuilder schema round trip", () => {
  it("round-trips a nested AND/OR condition tree, including exceptions, without data loss", () => {
    const schema: RuleSchema = {
      root_condition: {
        combinator: "AND",
        conditions: [
          { field: "amount", operator: "lte", value: 500 },
          {
            combinator: "OR",
            conditions: [
              { field: "photo_evidence_provided", operator: "eq", value: true },
              { field: "tier", operator: "in", value: ["gold", "platinum"] },
            ],
          },
        ],
      },
      action: { decision: "approve", human_review_required: true },
      exceptions: [{ field: "fraud_suspected", operator: "is_missing", value: null }],
      missing_data_behavior: "treat_as_false",
    }

    const state = schemaToBuilderState(schema)
    const roundTripped = builderStateToSchema(state)

    expect(roundTripped).toEqual(schema)
  })

  it("round-trips a three-level-deep nested group", () => {
    const schema: RuleSchema = {
      root_condition: {
        combinator: "OR",
        conditions: [
          { field: "status", operator: "eq", value: "escalated" },
          {
            combinator: "AND",
            conditions: [
              { field: "amount", operator: "gt", value: 1000 },
              {
                combinator: "OR",
                conditions: [
                  { field: "region", operator: "eq", value: "EU" },
                  { field: "region", operator: "eq", value: "UK" },
                ],
              },
            ],
          },
        ],
      },
      action: { decision: "escalate:finance", human_review_required: false },
      exceptions: [],
      missing_data_behavior: "route_to_human",
    }

    expect(builderStateToSchema(schemaToBuilderState(schema))).toEqual(schema)
  })

  it("round-trips string, number, boolean and array leaf values exactly", () => {
    const schema: RuleSchema = {
      root_condition: {
        combinator: "AND",
        conditions: [
          { field: "decision_label", operator: "eq", value: "approve" },
          { field: "amount", operator: "eq", value: 42 },
          { field: "flagged", operator: "eq", value: false },
          { field: "tags", operator: "in", value: ["a", "b", "c"] },
        ],
      },
      action: { decision: "approve", human_review_required: false },
      exceptions: [],
      missing_data_behavior: "fail",
    }

    expect(builderStateToSchema(schemaToBuilderState(schema))).toEqual(schema)
  })

  it("produces a fresh, valid default state when there is nothing to edit yet", () => {
    const schema: RuleSchema = {
      root_condition: { field: "amount", operator: "lte", value: 500 },
      action: { decision: "approve", human_review_required: false },
      exceptions: [],
      missing_data_behavior: "route_to_human",
    }
    const state = schemaToBuilderState(schema)
    expect(state.root.kind).toBe("leaf")
    expect(state.exceptions).toHaveLength(0)
    expect(builderStateToSchema(state)).toEqual(schema)
  })
})
