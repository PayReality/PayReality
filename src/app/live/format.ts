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
