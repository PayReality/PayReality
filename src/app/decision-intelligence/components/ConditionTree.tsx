import { isCompositeCondition, type ConditionNode, type RuleSchema } from "../types";

const OPERATOR_LABEL: Record<string, string> = {
  eq: "is",
  neq: "is not",
  gt: "is greater than",
  gte: "is at least",
  lt: "is less than",
  lte: "is at most",
  in: "is one of",
  not_in: "is not one of",
  contains: "contains",
  is_missing: "is missing",
};

function formatValue(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (Array.isArray(value)) return value.map(formatValue).join(", ");
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/**
 * Renders one ConditionNode (rule_schema.py's typed, nested AND/OR
 * condition language) as formatted, indented text -- never a raw JSON
 * dump. A leaf Condition reads as a plain sentence ("field is value");
 * a CompositeCondition shows its combinator once and indents its
 * children beneath it, so nesting (and therefore precedence) is visible
 * in the layout itself, the same guarantee the schema's own shape
 * already gives a program reading it.
 */
export function ConditionNodeView({ node, depth = 0 }: { node: ConditionNode; depth?: number }) {
  if (isCompositeCondition(node)) {
    return (
      <div style={{ marginLeft: depth > 0 ? 16 : 0 }}>
        <div
          className="text-xs font-semibold uppercase tracking-wide mb-1"
          style={{ color: "var(--pr-authority-blue)" }}
        >
          {node.combinator}
        </div>
        <div
          className="flex flex-col gap-1.5 pl-3"
          style={{ borderLeft: "2px solid var(--pr-overlay-10)" }}
        >
          {node.conditions.length === 0 ? (
            <span className="text-xs" style={{ color: "var(--pr-text-disabled)", fontStyle: "italic" }}>
              (no conditions)
            </span>
          ) : (
            node.conditions.map((child, i) => <ConditionNodeView key={i} node={child} depth={depth + 1} />)
          )}
        </div>
      </div>
    );
  }

  return (
    <div style={{ marginLeft: depth > 0 ? 16 : 0, fontSize: 13 }}>
      <code style={{ color: "var(--pr-text-primary)", fontFamily: "monospace" }}>{node.field}</code>{" "}
      <span style={{ color: "var(--pr-text-muted)" }}>{OPERATOR_LABEL[node.operator] ?? node.operator}</span>{" "}
      {node.operator !== "is_missing" && (
        <code style={{ color: "var(--pr-authority-blue)", fontFamily: "monospace" }}>{formatValue(node.value)}</code>
      )}
    </div>
  );
}

const MISSING_DATA_SENTENCE: Record<RuleSchema["missing_data_behavior"], string> = {
  route_to_human:
    "If any referenced fact is missing from a case, this rule does not decide automatically -- it is routed to a human for review.",
  fail: "If any referenced fact is missing from a case, this rule simply produces no decision (not routed anywhere).",
  treat_as_false:
    "If any referenced fact is missing from a case, the missing condition is treated as not matching, and the rest of the tree is still evaluated.",
};

/** The complete, readable rendering of one RuleSchema: condition tree, action, exceptions, and missing-data policy. */
export function RuleSchemaView({ schema }: { schema: RuleSchema }) {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: "var(--pr-text-muted)" }}>
          When this is true
        </p>
        <ConditionNodeView node={schema.root_condition} />
      </div>

      <div>
        <p className="text-xs font-semibold uppercase tracking-wide mb-1" style={{ color: "var(--pr-text-muted)" }}>
          Then
        </p>
        <p style={{ fontSize: 14, color: "var(--pr-text-primary)" }}>
          Decision: <strong>{schema.action.decision}</strong>
          {schema.action.human_review_required && (
            <span style={{ color: "var(--pr-warning-amber)" }}> -- always routed to a human for review</span>
          )}
        </p>
      </div>

      {schema.exceptions.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: "var(--pr-text-muted)" }}>
            Unless any exception matches (overrides the match back to "does not apply")
          </p>
          <div className="flex flex-col gap-2">
            {schema.exceptions.map((exception, i) => (
              <ConditionNodeView key={i} node={exception} />
            ))}
          </div>
        </div>
      )}

      <div>
        <p className="text-xs font-semibold uppercase tracking-wide mb-1" style={{ color: "var(--pr-text-muted)" }}>
          If data is missing
        </p>
        <p style={{ fontSize: 13, color: "var(--pr-text-secondary)" }}>{MISSING_DATA_SENTENCE[schema.missing_data_behavior]}</p>
      </div>
    </div>
  );
}
