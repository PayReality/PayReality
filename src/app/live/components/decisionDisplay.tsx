import { CheckCircle2, XCircle, ShieldAlert } from "lucide-react";
import {
  describeConditionBusiness,
  describeConditionTechnical,
} from "../format";
import type { Certificate } from "../../agents/types";
import type { ConditionEvaluation, DelegationEdge, LiveEvidence, RuleEvaluation } from "../types";

// Core Product Experience Redesign: display primitives shared by
// DecisionDetailPage and ManualDecisionSheet -- previously duplicated
// implicitly inside the single LiveTestIntent.tsx page these two now
// replace. Kept presentation-only (no data fetching) so both callers
// stay in charge of their own loading/error states.

// Live-QA fix: fg used to read the plain --pr-trust-green/-amber/-red
// tokens directly, which is exactly what a real getComputedStyle
// contrast check against the live demo caught as a WCAG 2.1 4.5:1
// failure on this theme's light mode (1.99:1 to 3.30:1 measured), the
// bright brand color read as text sitting on a 10%-opacity tint of that
// same color, not on the page's plain background. The *-on-tint tokens
// (theme.css) are a darker shade of the same hue in light theme only;
// dark theme already passed with the original bright color, so they
// resolve to it unchanged there.
export const OUTCOME_STYLE: Record<string, { bg: string; fg: string; icon: typeof CheckCircle2 }> = {
  ALLOW: { bg: "rgba(34,197,94,0.1)", fg: "var(--pr-trust-green-on-tint)", icon: CheckCircle2 },
  DENY: { bg: "rgba(239,68,68,0.1)", fg: "var(--pr-critical-red-on-tint)", icon: XCircle },
  HUMAN_REVIEW: { bg: "rgba(245,158,11,0.1)", fg: "var(--pr-warning-amber-on-tint)", icon: ShieldAlert },
};

// Product Experience Remediation Milestone 1 (Decision Provenance):
// self-declared by the caller, not cryptographically provable -- see
// domain/decision/source.py's own docstring server-side. `null` is a
// real, honest state (a record from before provenance tracking
// existed), never rendered as if it were "Runtime."
export function describeSource(source: string | null): string {
  if (source === "runtime") return "Runtime";
  if (source === "manual_test") return "Manual test";
  return "Unknown (recorded before provenance tracking)";
}

// Visual Experience V2 (found via browser QA): describeSource's full
// fallback sentence, "Unknown (recorded before provenance tracking),"
// wrapped across three lines in nearly every row of a real decision
// history -- provenance is supposed to stay de-emphasized, not become
// the widest, most visually noisy column on the page. The list context
// gets the short word; the full sentence stays one hover/tap away via
// `title`, and Decision Detail's own prose still uses describeSource
// directly, unabbreviated.
export function describeSourceCompact(source: string | null): string {
  if (source === "runtime") return "Runtime";
  if (source === "manual_test") return "Manual test";
  return "Unknown";
}

export function describeFreshnessStatus(status: string): string {
  if (status === "current") return "Current";
  if (status === "review_due") return "Review due";
  if (status === "expired") return "Expired";
  return "Not tracked";
}

export function ContextRow({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1.5">
      <span className="text-xs flex-shrink-0" style={{ color: "var(--pr-text-muted)" }}>{label}</span>
      <span
        className="text-xs font-medium text-right"
        style={{ color: muted ? "var(--pr-text-disabled)" : "var(--pr-text-primary)" }}
      >
        {value}
      </span>
    </div>
  );
}

export function DelegationRow({ delegation }: { delegation: DelegationEdge }) {
  return (
    <div className="py-1.5" style={{ borderTop: "1px solid var(--pr-overlay-05)", fontSize: 12 }}>
      <span style={{ color: "var(--pr-text-primary)" }}>{delegation.operation ?? "Delegation"}</span>
      {delegation.resource_id && (
        <span style={{ color: "var(--pr-text-muted)" }}> on resource {delegation.resource_id}</span>
      )}
    </div>
  );
}

export function EvidenceRecordCard({ evidence, label }: { evidence: LiveEvidence; label: string }) {
  const p = evidence.payload;
  const fields: Array<[string, string | undefined]> = [
    ["Evidence ID", evidence.evidence_id],
    ["Status", evidence.status],
    ["Key ID", evidence.key_id],
    ["Recorded at", new Date(p.recorded_at).toLocaleString()],
    ["Risk classification", p.risk_classification],
    ["Authority outcome", p.authority_outcome],
    ["Approval outcome", p.approval_outcome ?? undefined],
    ["Reviewer", p.reviewer ?? p.approver ?? undefined],
    ["Policy version", p.policy_version !== undefined ? String(p.policy_version) : undefined],
    ["Policy bundle hash", p.policy_bundle_hash],
    ["Decision engine version", p.authority_version],
    ["Prior record's hash", p.previous_hash ?? "None (first record in this chain)"],
    ["Matched policies", p.matched_mandate_ids.length > 0 ? p.matched_mandate_ids.join(", ") : "None"],
    ["Signature", `${evidence.signature.slice(0, 24)}...`],
  ];
  return (
    <div className="p-3 rounded-lg" style={{ backgroundColor: "var(--pr-overlay-03)", border: "1px solid var(--pr-overlay-05)" }}>
      <p className="text-xs font-semibold mb-2" style={{ color: "var(--pr-authority-blue)" }}>{label}</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6">
        {fields.filter(([, v]) => v !== undefined).map(([k, v]) => (
          <ContextRow key={k} label={k} value={v as string} />
        ))}
      </div>
    </div>
  );
}

// Phase 2B: one policy condition, exactly as it was actually evaluated
// against this decision's reconstructed historical policy state -- never
// a live re-evaluation. `expected_value`/`actual_value` are rendered
// with String() since they can be a number, string, or bool depending
// on the condition's own field.
// Milestone 10: two layers, per the audit's own finding that expanded
// condition detail was technical notation only. The business sentence
// (describeConditionBusiness) is primary; the exact symbolic notation
// (describeConditionTechnical) stays available right below it, smaller
// and explicitly labeled -- evidence for an auditor, not removed, just
// no longer the only thing an operator sees.
export function ConditionRow({ condition }: { condition: ConditionEvaluation }) {
  return (
    <div className="flex items-start gap-2 py-1.5">
      <span
        className="flex-shrink-0 font-bold text-xs mt-0.5"
        style={{ color: condition.passed ? "var(--pr-trust-green)" : "var(--pr-critical-red)" }}
        aria-hidden="true"
      >
        {condition.passed ? "✓" : "✗"}
      </span>
      <div className="min-w-0">
        <p className="text-xs" style={{ color: "var(--pr-text-primary)" }}>{describeConditionBusiness(condition)}</p>
        <p className="text-[11px] font-mono mt-0.5" style={{ color: "var(--pr-text-disabled)" }}>
          Technical detail: {describeConditionTechnical(condition)}
        </p>
      </div>
    </div>
  );
}

// One policy rule as reconstructed from the exact historical bundle this
// decision was evaluated against (server/app/services/decision_explanation_service.py).
// `isCausal` highlights the single rule (if any) whose match actually
// produced this decision's outcome -- read from the real OPA answer
// (evaluated_mandates), never recomputed.
export function RuleEvaluationCard({ rule, isCausal }: { rule: RuleEvaluation; isCausal: boolean }) {
  const statusLabel = rule.matched ? "Applied" : rule.scope_matched ? "Not applied" : "Not relevant";
  return (
    <div
      className="p-3 rounded-lg mb-2"
      style={{
        backgroundColor: isCausal ? "rgba(77,124,254,0.06)" : "var(--pr-overlay-03)",
        border: `1px solid ${isCausal ? "var(--pr-authority-blue)" : "var(--pr-overlay-05)"}`,
      }}
    >
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-xs font-semibold" style={{ color: "var(--pr-text-primary)" }}>{rule.policy_name}</span>
        <span
          className="text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded flex-shrink-0"
          style={{
            color: rule.matched ? "var(--pr-authority-blue)" : "var(--pr-text-disabled)",
            backgroundColor: rule.matched ? "rgba(77,124,254,0.12)" : "var(--pr-overlay-05)",
          }}
        >
          {statusLabel}
        </span>
      </div>
      <p className="text-xs mb-2" style={{ color: "var(--pr-text-muted)" }}>{rule.summary}</p>
      {rule.scope_matched ? (
        rule.conditions.map((c, i) => <ConditionRow key={i} condition={c} />)
      ) : (
        <p className="text-xs" style={{ color: "var(--pr-text-disabled)" }}>
          Scoped to a different principal or action -- not evaluated against this request.
        </p>
      )}
      {/* Milestone 10: the raw policy identifier lives here now -- inside
         expandable technical detail, not the collapsed pipeline stage or
         the primary "why" text above. */}
      <p className="text-[11px] font-mono mt-2 pt-2" style={{ color: "var(--pr-text-disabled)", borderTop: "1px solid var(--pr-overlay-05)" }}>
        Policy ID: {rule.policy_id}
      </p>
    </div>
  );
}

export function SignerCard({ certificate }: { certificate: Certificate }) {
  const fields: Array<[string, string | undefined]> = [
    ["Certificate ID", certificate.id],
    ["Status", certificate.status],
    ["Public key", `${certificate.public_key.slice(0, 24)}...`],
    ["Issued at", new Date(certificate.issued_at).toLocaleString()],
    ["Activated at", certificate.activated_at ? new Date(certificate.activated_at).toLocaleString() : undefined],
    ["Rotated at", certificate.rotated_at ? new Date(certificate.rotated_at).toLocaleString() : undefined],
    ["Expires at", certificate.expires_at ? new Date(certificate.expires_at).toLocaleString() : undefined],
    ["Revoked at", certificate.revoked_at ? new Date(certificate.revoked_at).toLocaleString() : undefined],
  ];
  return (
    <div className="p-3 rounded-lg" style={{ backgroundColor: "var(--pr-overlay-03)", border: "1px solid var(--pr-overlay-05)" }}>
      <p className="text-xs font-semibold mb-2" style={{ color: "var(--pr-authority-blue)" }}>Signer</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6">
        {fields.filter(([, v]) => v !== undefined).map(([k, v]) => (
          <ContextRow key={k} label={k} value={v as string} />
        ))}
      </div>
    </div>
  );
}
