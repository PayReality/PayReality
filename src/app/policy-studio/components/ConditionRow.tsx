import { KNOWN_OPERATORS, type Condition } from "../types";

const inputStyle: React.CSSProperties = {
  backgroundColor: "var(--pr-bg-hover)",
  border: "1px solid var(--pr-overlay-10)",
  color: "var(--pr-text-primary)",
  borderRadius: 6,
  padding: "6px 8px",
  fontSize: 13,
  fontFamily: "monospace",
};

// Exported for ConditionRow.test.ts: this is what actually decides what
// value a Runtime Policy condition enforces server-side, so a coercion
// bug here (e.g. losing a leading zero, or a stray space breaking the
// "in" split) silently changes rule behavior, not just display.
export function parseValue(raw: string, operator: string): Condition["value"] {
  if (operator === "exists") return raw === "true";
  if (operator === "in") return raw.split(",").map((s) => s.trim());
  const asNumber = Number(raw);
  if (raw.trim() !== "" && !Number.isNaN(asNumber)) return asNumber;
  if (raw === "true") return true;
  if (raw === "false") return false;
  return raw;
}

export function valueToInputString(value: Condition["value"]): string {
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

interface Props {
  condition: Condition;
  onChange?: (next: Condition) => void;
  onRemove?: () => void;
  readOnly?: boolean;
}

// One condition: field, operator, value. Editable in the Workspace,
// read-only (with a diff indicator prefix supplied by the caller) in
// the Diff view.
export function ConditionRow({ condition, onChange, onRemove, readOnly }: Props) {
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
      <input
        aria-label="Condition field"
        style={{ ...inputStyle, width: 180 }}
        value={condition.field}
        placeholder="Field, e.g. amount"
        readOnly={readOnly}
        onChange={(e) => onChange?.({ ...condition, field: e.target.value })}
      />
      {readOnly ? (
        <span style={{ ...inputStyle, width: 90, textAlign: "center" }}>{condition.operator}</span>
      ) : (
        <select
          aria-label="Condition operator"
          style={{ ...inputStyle, width: 90 }}
          value={condition.operator}
          onChange={(e) => onChange?.({ ...condition, operator: e.target.value })}
        >
          {KNOWN_OPERATORS.map((op) => (
            <option key={op} value={op}>
              {op}
            </option>
          ))}
        </select>
      )}
      {condition.operator === "exists" ? (
        <select
          aria-label="Condition value"
          style={{ ...inputStyle, width: 180 }}
          value={String(condition.value)}
          disabled={readOnly}
          onChange={(e) => onChange?.({ ...condition, value: e.target.value === "true" })}
        >
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      ) : (
        <input
          aria-label="Condition value"
          style={{ ...inputStyle, width: 180 }}
          value={valueToInputString(condition.value)}
          placeholder="Value"
          readOnly={readOnly}
          onChange={(e) => onChange?.({ ...condition, value: parseValue(e.target.value, condition.operator) })}
        />
      )}
      {!readOnly && onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove condition on ${condition.field || "this field"}`}
          style={{
            background: "none",
            border: "none",
            color: "var(--pr-critical-red)",
            cursor: "pointer",
            fontSize: 12,
            padding: "6px 8px",
          }}
        >
          Remove
        </button>
      )}
    </div>
  );
}
