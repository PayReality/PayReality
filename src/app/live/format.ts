import { ApiError } from "./apiClient";

// A clean, human sentence for any failed action, never the raw backend
// error payload. Previously several pages showed
// `${action} failed: ${JSON.stringify(e.body)}` directly to the user,
// exposing internal validation payloads; this is the one place that
// decision is made now.
// Codes 401/403 wrap for reasons other than a missing Operator Key
// (added when Agent Lifecycle introduced agent-status rejections on
// /v1/intents): checked first so "this agent is revoked" never gets
// mislabeled as an Operator Key problem.
const AGENT_STATUS_DETAIL: Record<string, string> = {
  agent_revoked: "This agent's certificate has been permanently revoked and can no longer act.",
  agent_retired: "This agent has been retired and can no longer act.",
  agent_not_operational: "This agent hasn't been activated yet.",
};

// Phase 10 (RBAC.md): require_permission's specific detail codes, checked
// before the generic 401/403 Operator Key message so a logged-in user
// who simply lacks the right role sees that, not a prompt to enter a key
// they were never meant to have.
const PERMISSION_DETAIL: Record<string, string> = {
  authentication_required: "this action needs you to sign in, or the Operator Key set in the sidebar (bottom left).",
  invalid_or_expired_credential: "your session has expired. Sign in again to continue.",
  permission_denied: "your role doesn't include this permission. Ask your Organisation Owner if you believe this is wrong.",
};

// Phase 2B: GET .../explanation's own 404, distinct from an Operator Key
// problem -- the decision itself (or its cross-org binding) wasn't found.
const NOT_FOUND_DETAIL: Record<string, string> = {
  decision_not_found: "this decision could not be found.",
};

export function describeApiError(e: unknown, action: string): string {
  if (e instanceof ApiError) {
    const detail = e.body && typeof e.body === "object" ? (e.body as { detail?: string }).detail : undefined;
    if (detail && AGENT_STATUS_DETAIL[detail]) {
      return `${action} failed: ${AGENT_STATUS_DETAIL[detail]}`;
    }
    if (detail && PERMISSION_DETAIL[detail]) {
      return `${action} failed: ${PERMISSION_DETAIL[detail]}`;
    }
    if (detail && NOT_FOUND_DETAIL[detail]) {
      return `${action} failed: ${NOT_FOUND_DETAIL[detail]}`;
    }
    if (e.status === 401 || e.status === 403) {
      return `${action} failed: this action needs the Operator Key set in the sidebar (bottom left). Enter it there and try again.`;
    }
    return `${action} failed. Please try again, or contact support if this continues.`;
  }
  return `${action} failed. Check your connection and try again.`;
}

// "pending_review", "VERIFIED", "HUMAN_REVIEW" -> "Pending review",
// "Verified", "Human review". Used everywhere a status/outcome enum is
// shown as text, regardless of what case the API sent it in, so the
// same value never reads differently on different pages.
export function formatStatus(status: string): string {
  const spaced = status.toLowerCase().replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

// A Decision's `reason` is a raw backend code (AGENT_SUSPENDED,
// no_active_policy, opa_timeout, unrecognized_action, ...), not a
// sentence (PAYREALITY_UX_REVIEW.md, "give every reason code a
// plain-English sentence"). This is the one place that translation
// happens; every page that shows a decision reason should go through
// this rather than rendering `decision.reason` directly.
const REASON_SENTENCE: Record<string, string> = {
  AGENT_SUSPENDED: "This agent is currently suspended and cannot act.",
  agent_suspended: "This agent is currently suspended and cannot act.",
  agent_revoked: "This agent's certificate has been permanently revoked.",
  agent_retired: "This agent has been retired and can no longer act.",
  agent_not_operational: "This agent hasn't been activated yet.",
  unrecognized_action: "This isn't an action the platform recognizes yet, so it was sent to a human to be safe.",
  no_active_policy: "There's no active rule for this yet, so it was sent to a human to decide.",
  opa_timeout: "The check took too long to run, so this was sent to a human to decide.",
  undetermined: "The rule didn't clearly match, so this was sent to a human to decide.",
  replay_detected: "This exact request was already submitted once before.",
};

export function describeReason(reason: string | null | undefined): string | null {
  if (!reason) return null;
  if (REASON_SENTENCE[reason]) return REASON_SENTENCE[reason];
  if (reason.startsWith("opa_error")) return "The policy check itself hit an error, so this was sent to a human to decide.";
  // Visual Experience V2 (found via browser QA): a real backend reason
  // code is always a single snake_case/UPPER_SNAKE token, never
  // containing a space -- formatStatus's lowercase-then-capitalize-first
  // is only valid for that shape. This demo's own fixtures put full,
  // already-proper-cased sentences in this same field for some decisions
  // (e.g. "Within David Okonkwo's delegated $50,000 Treasury spending
  // limit..."), which ran through formatStatus and rendered as
  // "within david okonkwo's delegated $50,000 treasury spending limit"
  // -- every proper noun silently lowercased. Prose (has a space) is
  // returned verbatim; only a genuine single-token code gets humanized.
  if (reason.includes(" ")) return reason;
  // Unknown code: fall back to a humanized version rather than the raw token.
  return formatStatus(reason);
}

// Phase 2B (PHASE_2B_LIVE_PER_CONDITION_EXPLAINABILITY_SUMMARY.md):
// GET .../explanation's `unavailable_reason` codes -- distinct from a
// Decision's own `reason` above, these explain why the per-condition
// RECONSTRUCTION isn't possible, not why the decision itself came out
// the way it did.
const EXPLANATION_UNAVAILABLE_SENTENCE: Record<string, string> = {
  no_policy_evaluated: "No active policy existed when this decision was made, so there's no rule to break down.",
  evaluation_did_not_complete: "The policy check itself didn't complete for this decision, so there's no rule-level result to show.",
  bundle_not_found: "The exact policy bundle this decision was evaluated against can no longer be found.",
  bundle_manifest_not_available: "This decision predates per-condition explainability, so condition-level detail isn't available for it.",
  evidence_not_available: "No evidence record was found for this decision, so condition-level detail isn't available.",
  principal_not_resolved: "The acting principal for this decision couldn't be resolved, so condition-level detail isn't available.",
  historical_policy_record_missing: "Part of the historical policy record this decision depended on is missing.",
};

export function describeExplanationUnavailable(reason: string | null | undefined): string {
  if (!reason) return "Condition-level detail isn't available for this decision.";
  return EXPLANATION_UNAVAILABLE_SENTENCE[reason] ?? formatStatus(reason);
}

// Milestone 10 (MILESTONE_10_DECISION_SECURITY_AND_CLARITY_SUMMARY.md):
// a small, deterministic business-language layer for per-condition
// explanations (PHASE_2B_PRODUCTION_AND_PRODUCT_READINESS_AUDIT.md
// section 10 found none existed). No LLM, no semantic guessing: only
// `amount`, the one field this platform's own vocabulary is confident
// about, gets a fully-worded sentence; every Operator gets a phrase,
// since Operator is a small, closed, unambiguous set
// (domain/runtime_policy/conditions.py's Operator enum), not
// open-ended text safe or unsafe to translate. An unrecognized field
// keeps its raw name verbatim rather than an invented label -- "if a
// condition cannot safely be translated, keep it honest," not silently
// papered over.
// Domain Generalization Milestone: "Amount" (not "Payment amount") --
// this field applies to any action with a numeric amount, not only a
// financial one, even though $-formatting below remains the one
// heuristic this vocabulary is confident enough to apply by default.
const CONDITION_FIELD_LABELS: Record<string, string> = {
  amount: "Amount",
};

const OPERATOR_PHRASES: Record<string, string> = {
  "<=": "at or below",
  ">=": "at or above",
  "<": "below",
  ">": "above",
  "==": "equal to",
  "!=": "not equal to",
  in: "one of",
  contains: "includes",
  exists: "present",
};

function formatConditionValue(field: string, value: unknown): string {
  if (typeof value === "number") {
    const formatted = value.toLocaleString("en-US");
    return field === "amount" ? `$${formatted}` : formatted;
  }
  return String(value);
}

interface ConditionLike {
  field: string;
  operator: string;
  expected_value: unknown;
  actual_value: unknown;
  passed: boolean;
}

// The primary, operator-facing line. Deterministically derived from the
// same field/operator/expected/actual values the technical line below
// also shows -- never a different, invented claim about what the
// condition means.
export function describeConditionBusiness(condition: ConditionLike): string {
  const fieldLabel = CONDITION_FIELD_LABELS[condition.field] ?? condition.field;
  const expected = formatConditionValue(condition.field, condition.expected_value);
  const actual = formatConditionValue(condition.field, condition.actual_value);

  if (condition.field === "amount" && (condition.operator === "<=" || condition.operator === "<")) {
    return condition.passed
      ? `${fieldLabel} (${actual}) is within the allowed limit of ${expected}.`
      : `${fieldLabel} (${actual}) exceeds the allowed limit of ${expected}.`;
  }
  if (condition.field === "amount" && (condition.operator === ">=" || condition.operator === ">")) {
    return condition.passed
      ? `${fieldLabel} (${actual}) meets the required minimum of ${expected}.`
      : `${fieldLabel} (${actual}) is below the required minimum of ${expected}.`;
  }
  const operatorPhrase = OPERATOR_PHRASES[condition.operator] ?? condition.operator;
  return `${fieldLabel} was ${operatorPhrase} ${expected} (actual: ${actual}) -- ${condition.passed ? "matched" : "did not match"}.`;
}

// The secondary, auditor/engineer-facing line -- the exact symbolic
// notation, preserved verbatim (never removed, only de-emphasized and
// labeled), so nothing the business line summarizes is ever lost.
export function describeConditionTechnical(condition: ConditionLike): string {
  return `${condition.field} ${condition.operator} ${String(condition.expected_value)} (actual: ${String(condition.actual_value)})`;
}
