import { useEffect, useState } from "react"
import { Button } from "./ui"
import type { ConditionNode, ConditionOperator, MissingDataBehavior, RuleSchema } from "../di/types"
import { isCompositeCondition } from "../di/types"

// A real, structured rule builder replacing the raw JSON textarea
// (Feature: visual rule builder). Produces and consumes the exact same
// RuleSchema the backend accepts/returns (rule_schema.py): a Condition
// (field/operator/value) or a CompositeCondition (AND/OR of nested
// ConditionNodes, recursively), a RuleAction, a list of top-level
// exception ConditionNodes, and missing_data_behavior.
//
// Internally this keeps its own tree shape with a stable `id` per node
// (for React keys / in-place edits), never persisted or sent to the
// backend -- `builderStateToSchema` strips it back out. The two
// conversion functions are exported standalone (not just used inside the
// component) specifically so a round-trip through a real nested AND/OR
// tree can be unit-tested without rendering anything.

export type ConditionOp = ConditionOperator

export const OPERATORS: ConditionOp[] = ["eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in", "contains", "is_missing"]

export const OPERATOR_LABELS: Record<ConditionOp, string> = {
  eq: "equals",
  neq: "does not equal",
  gt: "is greater than",
  gte: "is greater than or equal to",
  lt: "is less than",
  lte: "is less than or equal to",
  in: "is in (list)",
  not_in: "is not in (list)",
  contains: "contains",
  is_missing: "is missing",
}

let nextId = 0
function uid(): string {
  nextId += 1
  return `n${nextId}-${Date.now().toString(36)}`
}

export interface BuilderLeaf {
  id: string
  kind: "leaf"
  field: string
  operator: ConditionOp
  // Always a raw string in the UI, opportunistically JSON-parsed on the
  // way out (parseLeafValue) -- same "try JSON, fall back to the literal
  // string" convention this codebase already uses for Case.facts cells
  // (csv_import.py's own _try_parse_json).
  value: string
}

export interface BuilderGroup {
  id: string
  kind: "group"
  combinator: "AND" | "OR"
  children: BuilderNode[]
}

export type BuilderNode = BuilderLeaf | BuilderGroup

export interface RuleBuilderState {
  root: BuilderNode
  decision: string
  humanReviewRequired: boolean
  exceptions: BuilderNode[]
  missingDataBehavior: MissingDataBehavior
}

export function emptyLeaf(): BuilderLeaf {
  return { id: uid(), kind: "leaf", field: "", operator: "eq", value: "" }
}

export function emptyGroup(): BuilderGroup {
  return { id: uid(), kind: "group", combinator: "AND", children: [emptyLeaf()] }
}

function stringifyLeafValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return ""
  if (typeof value === "string") return value
  return JSON.stringify(value)
}

function parseLeafValue(raw: string, operator: ConditionOp): unknown {
  if (operator === "is_missing") return null
  const trimmed = raw.trim()
  if (trimmed === "") return ""
  try {
    return JSON.parse(trimmed)
  } catch {
    return raw
  }
}

function nodeFromSchema(node: ConditionNode): BuilderNode {
  if (isCompositeCondition(node)) {
    return {
      id: uid(),
      kind: "group",
      combinator: node.combinator,
      children: node.conditions.length > 0 ? node.conditions.map(nodeFromSchema) : [emptyLeaf()],
    }
  }
  return {
    id: uid(),
    kind: "leaf",
    field: node.field,
    operator: node.operator,
    value: stringifyLeafValue(node.value),
  }
}

function nodeToSchema(node: BuilderNode): ConditionNode {
  if (node.kind === "group") {
    return { combinator: node.combinator, conditions: node.children.map(nodeToSchema) }
  }
  return { field: node.field, operator: node.operator, value: parseLeafValue(node.value, node.operator) }
}

/** Converts a real backend RuleSchema into this builder's own editable tree -- including arbitrarily nested AND/OR groups. */
export function schemaToBuilderState(schema: RuleSchema): RuleBuilderState {
  return {
    root: nodeFromSchema(schema.root_condition),
    decision: schema.action.decision,
    humanReviewRequired: schema.action.human_review_required,
    exceptions: schema.exceptions.map(nodeFromSchema),
    missingDataBehavior: schema.missing_data_behavior,
  }
}

/** Converts this builder's tree back into the exact RuleSchema shape the backend accepts -- the inverse of schemaToBuilderState. */
export function builderStateToSchema(state: RuleBuilderState): RuleSchema {
  return {
    root_condition: nodeToSchema(state.root),
    action: { decision: state.decision, human_review_required: state.humanReviewRequired },
    exceptions: state.exceptions.map(nodeToSchema),
    missing_data_behavior: state.missingDataBehavior,
  }
}

export function defaultBuilderState(): RuleBuilderState {
  return {
    root: emptyLeaf(),
    decision: "",
    humanReviewRequired: false,
    exceptions: [],
    missingDataBehavior: "route_to_human",
  }
}

/** A leaf must at least name a field; a group must have at least one child. Recurses into every nested node. */
export function findBuilderError(node: BuilderNode): string | null {
  if (node.kind === "leaf") {
    if (!node.field.trim()) return "Every condition needs a field name."
    return null
  }
  if (node.children.length === 0) return "A group needs at least one condition."
  for (const child of node.children) {
    const err = findBuilderError(child)
    if (err) return err
  }
  return null
}

export function validateBuilderState(state: RuleBuilderState): string | null {
  if (!state.decision.trim()) return "The rule's action needs a decision label."
  const rootErr = findBuilderError(state.root)
  if (rootErr) return rootErr
  for (const exception of state.exceptions) {
    const err = findBuilderError(exception)
    if (err) return err
  }
  return null
}

function ConditionNodeEditor({
  node,
  depth,
  canRemove,
  onChange,
  onRemove,
}: {
  node: BuilderNode
  depth: number
  canRemove: boolean
  onChange: (next: BuilderNode) => void
  onRemove?: () => void
}) {
  const isGroup = node.kind === "group"

  function toggleKind(nextKind: "leaf" | "group") {
    if (nextKind === "group" && node.kind === "leaf") {
      onChange({ id: node.id, kind: "group", combinator: "AND", children: [node] })
    } else if (nextKind === "leaf" && node.kind === "group") {
      onChange(node.children[0] ?? emptyLeaf())
    }
  }

  return (
    <div className="rule-node" style={{ marginLeft: depth * 16, marginBottom: 10 }}>
      <div className="rule-row" style={{ gridTemplateColumns: isGroup ? "170px 110px 1fr" : "140px 1fr 180px 1fr" }}>
        <select aria-label="Condition type" value={isGroup ? "group" : "condition"} onChange={(e) => toggleKind(e.target.value as "leaf" | "group")}>
          <option value="condition">Single condition</option>
          <option value="group">Group (AND/OR)</option>
        </select>
        {isGroup ? (
          <>
            <select
              aria-label="Combinator"
              value={(node as BuilderGroup).combinator}
              onChange={(e) => onChange({ ...(node as BuilderGroup), combinator: e.target.value as "AND" | "OR" })}
            >
              <option value="AND">AND</option>
              <option value="OR">OR</option>
            </select>
            <span />
          </>
        ) : (
          <>
            <input
              aria-label="Field"
              placeholder="field, e.g. amount"
              value={(node as BuilderLeaf).field}
              onChange={(e) => onChange({ ...(node as BuilderLeaf), field: e.target.value })}
            />
            <select
              aria-label="Operator"
              value={(node as BuilderLeaf).operator}
              onChange={(e) => onChange({ ...(node as BuilderLeaf), operator: e.target.value as ConditionOp })}
            >
              {OPERATORS.map((op) => (
                <option key={op} value={op}>
                  {OPERATOR_LABELS[op]}
                </option>
              ))}
            </select>
            {(node as BuilderLeaf).operator === "is_missing" ? (
              <span style={{ fontSize: 10, color: "var(--muted)", alignSelf: "center" }}>No value needed</span>
            ) : (
              <input
                aria-label="Value"
                placeholder='value, e.g. 500 or "approve" or ["a","b"]'
                value={(node as BuilderLeaf).value}
                onChange={(e) => onChange({ ...(node as BuilderLeaf), value: e.target.value })}
              />
            )}
          </>
        )}
        {canRemove && onRemove && (
          <Button kind="ghost" icon="close" onClick={onRemove}>
            Remove
          </Button>
        )}
      </div>
      {isGroup && (
        <div style={{ marginTop: 4 }}>
          {(node as BuilderGroup).children.map((child, i) => (
            <ConditionNodeEditor
              key={child.id}
              node={child}
              depth={depth + 1}
              canRemove={(node as BuilderGroup).children.length > 1}
              onRemove={() =>
                onChange({
                  ...(node as BuilderGroup),
                  children: (node as BuilderGroup).children.filter((_, idx) => idx !== i),
                })
              }
              onChange={(updated) =>
                onChange({
                  ...(node as BuilderGroup),
                  children: (node as BuilderGroup).children.map((c, idx) => (idx === i ? updated : c)),
                })
              }
            />
          ))}
          <div style={{ display: "flex", gap: 6, marginLeft: 16 }}>
            <Button
              kind="ghost"
              icon="plus"
              onClick={() => onChange({ ...(node as BuilderGroup), children: [...(node as BuilderGroup).children, emptyLeaf()] })}
            >
              Add condition
            </Button>
            <Button
              kind="ghost"
              icon="plus"
              onClick={() => onChange({ ...(node as BuilderGroup), children: [...(node as BuilderGroup).children, emptyGroup()] })}
            >
              Add group
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

export function RuleBuilder({
  initialSchema,
  onChange,
}: {
  initialSchema: RuleSchema
  onChange: (schema: RuleSchema) => void
}) {
  const [state, setState] = useState<RuleBuilderState>(() => schemaToBuilderState(initialSchema))
  const [showJson, setShowJson] = useState(false)

  useEffect(() => {
    onChange(builderStateToSchema(state))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state])

  const error = validateBuilderState(state)

  return (
    <div>
      <label style={{ display: "block", marginBottom: 8, fontSize: 10, fontWeight: 600, color: "var(--text-2)" }}>
        Condition tree
      </label>
      <ConditionNodeEditor node={state.root} depth={0} canRemove={false} onChange={(root) => setState({ ...state, root })} />

      <div className="form-grid" style={{ marginTop: 14 }}>
        <label>
          Decision
          <input
            placeholder="e.g. approve"
            value={state.decision}
            onChange={(e) => setState({ ...state, decision: e.target.value })}
          />
        </label>
        <label className="toggle-row">
          <span>Require human review</span>
          <input
            type="checkbox"
            checked={state.humanReviewRequired}
            onChange={(e) => setState({ ...state, humanReviewRequired: e.target.checked })}
          />
        </label>
      </div>

      <label style={{ display: "block", margin: "14px 0 8px", fontSize: 10, fontWeight: 600, color: "var(--text-2)" }}>
        Exceptions -- if any of these match, the rule's action never applies
      </label>
      {state.exceptions.map((exception, i) => (
        <ConditionNodeEditor
          key={exception.id}
          node={exception}
          depth={0}
          canRemove
          onRemove={() => setState({ ...state, exceptions: state.exceptions.filter((_, idx) => idx !== i) })}
          onChange={(updated) =>
            setState({ ...state, exceptions: state.exceptions.map((e, idx) => (idx === i ? updated : e)) })
          }
        />
      ))}
      <Button kind="ghost" icon="plus" onClick={() => setState({ ...state, exceptions: [...state.exceptions, emptyLeaf()] })}>
        Add exception
      </Button>

      <label style={{ display: "block", margin: "14px 0 8px", fontSize: 10, fontWeight: 600, color: "var(--text-2)" }}>
        When a referenced fact is missing from a case
      </label>
      <select
        value={state.missingDataBehavior}
        onChange={(e) => setState({ ...state, missingDataBehavior: e.target.value as MissingDataBehavior })}
      >
        <option value="route_to_human">Route to human review</option>
        <option value="fail">Fail (classify as error)</option>
        <option value="treat_as_false">Treat the condition as false</option>
      </select>

      {error && (
        <div className="callout" style={{ borderLeftColor: "var(--amber)", background: "var(--amber-soft)", color: "#7d5117", marginTop: 14 }}>
          <strong>Incomplete</strong>
          <span>{error}</span>
        </div>
      )}

      <div style={{ marginTop: 14 }}>
        <Button kind="ghost" onClick={() => setShowJson(!showJson)}>
          {showJson ? "Hide JSON preview" : "View as JSON"}
        </Button>
        {showJson && (
          <pre style={{ whiteSpace: "pre-wrap", fontSize: 11, background: "var(--surface-subtle)", padding: 12, borderRadius: 7, marginTop: 8 }}>
            {JSON.stringify(builderStateToSchema(state), null, 2)}
          </pre>
        )}
      </div>
    </div>
  )
}
