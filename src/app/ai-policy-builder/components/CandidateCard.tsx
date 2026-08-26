import { useId, useState } from "react";
import { Link } from "react-router";
import { aiPolicyBuilderApi } from "../api";
import type { Candidate, GraphGateError, PromoteResult, ValidationErrorItem } from "../types";
import type { RuntimePolicyRequest } from "../../policy-studio/types";
import { ScopeFields } from "../../policy-studio/components/ScopeFields";
import { ConditionRow } from "../../policy-studio/components/ConditionRow";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { ApiError } from "../../live/apiClient";
import { describeApiError, formatStatus } from "../../live/format";
import { track, trackError } from "../../services/analytics";
import { Input, getInputStyle } from "../../components/ui/input";
import { FieldLabel } from "../../components/ui/label";
import { Button } from "../../components/ui/button";

// Shared between the single-document AI Policy Builder review page and
// the multi-document AI Authority Builder's corpus review page: a
// candidate's content is always the same RuntimePolicyRequest shape
// regardless of which upload path produced it (RUNTIME_POLICY_MAPPING.md,
// AI_AUTHORITY_BUILDER_ARCHITECTURE.md).
export function CandidateCard({ candidate, onChanged }: { candidate: Candidate; onChanged: () => void }) {
  const [content, setContent] = useState<RuntimePolicyRequest>(candidate.content);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errors, setErrors] = useState<ValidationErrorItem[]>([]);
  const [tagInput, setTagInput] = useState("");
  // Authority-as-a-continuous-object, Stage I.4: only known for the
  // promotion that just happened in this session -- a promoted
  // candidate reloaded from a fresh page load has no authority_id to
  // show here (that durable view is Policy Studio's Workspace/List,
  // Stage I.5a), so this stays undefined rather than fabricating one.
  const [promoteResult, setPromoteResult] = useState<PromoteResult | null>(null);
  const [graphErrors, setGraphErrors] = useState<GraphGateError[]>([]);
  const formId = useId();

  const readOnly = candidate.status !== "pending_review";
  // Authority Graph -> RuntimePolicy Compilation Gate (issue #6):
  // undefined/null for a standalone (non-corpus) candidate -- no graph
  // to be ready or not ready against, so no gate to show at all.
  const graphGated = candidate.corpus_id != null;
  const graphReady = candidate.graph_readiness?.ready ?? true;

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      await aiPolicyBuilderApi.editCandidate(candidate.candidate_id, content);
      setMessage("Saved.");
    } catch (e) {
      setMessage(describeApiError(e, "Save"));
    } finally {
      setSaving(false);
    }
  }

  async function dismiss() {
    setSaving(true);
    try {
      await aiPolicyBuilderApi.dismissCandidate(candidate.candidate_id);
      onChanged();
    } catch (e) {
      setMessage(describeApiError(e, "Dismiss"));
    } finally {
      setSaving(false);
    }
  }

  async function promote() {
    setSaving(true);
    setMessage(null);
    setErrors([]);
    setGraphErrors([]);
    const startedAt = Date.now();
    try {
      await aiPolicyBuilderApi.editCandidate(candidate.candidate_id, content);
      const result = await aiPolicyBuilderApi.promoteCandidate(candidate.candidate_id);
      track("Runtime Policy Generated", {
        policy_id: result.policy_key,
        source: "ai_candidate",
        runtime_policy_generation_ms: Date.now() - startedAt,
      });
      setPromoteResult(result);
      setMessage(
        result.source_graph_version
          ? `Promoted to Policy Studio as a draft (v${result.version}), generated from Authority Graph v${result.source_graph_version}.`
          : result.authority_id
            ? `Promoted to Policy Studio as a draft (v${result.version}). Linked to Authority ${result.authority_id}.`
            : `Promoted to Policy Studio as a draft (v${result.version}). No resolved authority -- delegated_by kept as free text.`
      );
      onChanged();
    } catch (e) {
      if (e instanceof ApiError && e.body && typeof e.body === "object" && "error" in (e.body as object) && (e.body as { error: string }).error === "graph_not_ready") {
        setGraphErrors((e.body as { errors: GraphGateError[] }).errors);
        trackError("Runtime Policy Generation Failed", {
          error_type: "graph_not_ready",
          component: "ai_candidate_promote",
          duration_ms: Date.now() - startedAt,
        });
      } else if (e instanceof ApiError && e.body && typeof e.body === "object" && "errors" in (e.body as object)) {
        setErrors((e.body as { errors: ValidationErrorItem[] }).errors);
        trackError("Runtime Policy Generation Failed", {
          error_type: "validation_error",
          component: "ai_candidate_promote",
          duration_ms: Date.now() - startedAt,
        });
      } else {
        setMessage(describeApiError(e, "Promote"));
        trackError("Runtime Policy Generation Failed", {
          error_type: e instanceof Error ? e.name : "unknown_error",
          component: "ai_candidate_promote",
          duration_ms: Date.now() - startedAt,
        });
      }
    } finally {
      setSaving(false);
    }
  }

  function addCondition() {
    setContent((c) => ({ ...c, conditions: [...c.conditions, { field: "", operator: "==", value: "" }] }));
  }
  function updateCondition(i: number, next: RuntimePolicyRequest["conditions"][number]) {
    setContent((c) => ({ ...c, conditions: c.conditions.map((cond, idx) => (idx === i ? next : cond)) }));
  }
  function removeCondition(i: number) {
    setContent((c) => ({ ...c, conditions: c.conditions.filter((_, idx) => idx !== i) }));
  }
  function addTag() {
    if (!tagInput.trim()) return;
    setContent((c) => ({ ...c, metadata: { ...c.metadata, tags: [...c.metadata.tags, tagInput.trim()] } }));
    setTagInput("");
  }
  function removeTag(tag: string) {
    setContent((c) => ({ ...c, metadata: { ...c.metadata, tags: c.metadata.tags.filter((t) => t !== tag) } }));
  }

  return (
    <div
      style={{
        backgroundColor: "var(--pr-bg-card)",
        border: "1px solid var(--pr-overlay-05)",
        borderRadius: 12,
        padding: 20,
        marginBottom: 16,
      }}
    >
      <div className="flex items-center justify-between mb-2">
        <Input
          aria-label="Policy name"
          style={{ fontSize: 15, fontWeight: 500, maxWidth: 400 }}
          value={content.name}
          readOnly={readOnly}
          onChange={(e) => setContent((c) => ({ ...c, name: e.target.value }))}
        />
        <div className="flex items-center gap-2">
          <ConfidenceBadge confidence={candidate.confidence} />
          <span style={{ fontSize: 12, color: "var(--pr-text-muted)" }}>{formatStatus(candidate.status)}</span>
        </div>
      </div>

      {candidate.source_excerpt && (
        <p
          style={{
            fontSize: 12,
            fontStyle: "italic",
            color: "var(--pr-text-muted)",
            marginBottom: 8,
            borderLeft: "2px solid var(--pr-authority-blue)",
            paddingLeft: 8,
          }}
        >
          "{candidate.source_excerpt}" ({candidate.source_location})
        </p>
      )}

      {graphGated && candidate.status === "pending_review" && (
        <div
          className="flex items-center gap-2 mb-3"
          style={{
            fontSize: 12,
            padding: "6px 10px",
            borderRadius: 8,
            backgroundColor: graphReady ? "rgba(34,197,94,0.08)" : "rgba(245,158,11,0.1)",
            color: graphReady ? "var(--pr-trust-green)" : "var(--pr-warning-amber)",
          }}
        >
          {graphReady
            ? "Grounded in the corpus's latest approved Authority Graph version -- ready to compile."
            : "Compilation blocked: this candidate is not yet grounded in an approved Authority Graph version."}
        </div>
      )}

      {candidate.missing_fields.length > 0 && (
        <div className="flex gap-2 flex-wrap mb-3">
          {candidate.missing_fields.map((f) => (
            <span
              key={f}
              style={{
                fontSize: 12,
                color: "var(--pr-warning-amber)",
                border: "1px solid var(--pr-warning-amber)",
                borderRadius: 999,
                padding: "1px 8px",
              }}
            >
              Missing: {f}
            </span>
          ))}
        </div>
      )}

      <div className="mb-3">
        <ScopeFields scope={content.scope} onChange={(scope) => setContent((c) => ({ ...c, scope }))} />
      </div>

      <FieldLabel>Conditions</FieldLabel>
      {content.conditions.map((cond, i) => (
        <ConditionRow
          key={i}
          condition={cond}
          readOnly={readOnly}
          onChange={(next) => updateCondition(i, next)}
          onRemove={() => removeCondition(i)}
        />
      ))}
      {!readOnly && (
        <button onClick={addCondition} style={{ color: "var(--pr-authority-blue)", fontSize: 12, marginBottom: 10 }}>
          + Add condition
        </button>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-3 mt-2">
        <div>
          <FieldLabel htmlFor={`${formId}-effect`}>Effect</FieldLabel>
          <select
            id={`${formId}-effect`}
            style={getInputStyle()}
            value={content.effect}
            disabled={readOnly}
            onChange={(e) => setContent((c) => ({ ...c, effect: e.target.value }))}
          >
            <option value="allow">allow</option>
            <option value="deny">deny</option>
            <option value="require_human_review">require_human_review</option>
          </select>
        </div>
        <div>
          <FieldLabel htmlFor={`${formId}-risk`}>Risk level</FieldLabel>
          <select
            id={`${formId}-risk`}
            style={getInputStyle()}
            value={content.constraints.risk_level ?? ""}
            disabled={readOnly}
            onChange={(e) =>
              setContent((c) => ({
                ...c,
                constraints: { ...c.constraints, risk_level: e.target.value || null },
              }))
            }
          >
            <option value="">(unset)</option>
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
          </select>
        </div>
        <div>
          <FieldLabel htmlFor={`${formId}-delegated-by`}>Delegated by</FieldLabel>
          <Input
            id={`${formId}-delegated-by`}
            placeholder="Role or person"
            value={content.constraints.delegated_by ?? ""}
            readOnly={readOnly}
            onChange={(e) =>
              setContent((c) => ({
                ...c,
                constraints: { ...c.constraints, delegated_by: e.target.value || null },
              }))
            }
          />
          <p style={{ fontSize: 11, color: "var(--pr-text-muted)", marginTop: 3 }}>
            The organisational authority this rule enforces.
          </p>
        </div>
        <div>
          <FieldLabel htmlFor={`${formId}-owner`}>Owner</FieldLabel>
          <Input
            id={`${formId}-owner`}
            value={content.metadata.owner ?? ""}
            readOnly={readOnly}
            onChange={(e) => setContent((c) => ({ ...c, metadata: { ...c.metadata, owner: e.target.value || null } }))}
          />
          <p style={{ fontSize: 11, color: "var(--pr-text-muted)", marginTop: 3 }}>
            Who maintains this rule, distinct from who delegated it.
          </p>
        </div>
      </div>

      <label className="flex items-center gap-2 mb-3" style={{ fontSize: 12, color: "var(--pr-text-muted)" }}>
        <input
          type="checkbox"
          checked={content.constraints.evidence_required}
          disabled={readOnly}
          onChange={(e) =>
            setContent((c) => ({
              ...c,
              constraints: { ...c.constraints, evidence_required: e.target.checked },
            }))
          }
        />
        Evidence required for every decision under this rule
      </label>

      <div className="flex items-center gap-2 flex-wrap mb-3">
        {content.metadata.tags.map((t) => (
          <span
            key={t}
            style={{ fontSize: 11, color: "var(--pr-text-secondary)", backgroundColor: "var(--pr-bg-hover)", borderRadius: 999, padding: "2px 8px" }}
          >
            {t}
            {!readOnly && (
              <button
                onClick={() => removeTag(t)}
                aria-label={`Remove tag ${t}`}
                style={{ color: "var(--pr-critical-red)", marginLeft: 6, padding: "2px 4px" }}
              >
                x
              </button>
            )}
          </span>
        ))}
        {!readOnly && (
          <>
            <Input
              aria-label="New tag"
              style={{ width: 120 }}
              placeholder="Add tag"
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addTag()}
            />
            <button onClick={addTag} style={{ color: "var(--pr-authority-blue)", fontSize: 12, padding: "6px 8px" }}>
              + Add tag
            </button>
          </>
        )}
      </div>

      {errors.length > 0 && (
        <div role="alert" className="mb-3">
          {errors.map((err, i) => (
            <p key={i} style={{ fontSize: 12, color: "var(--pr-critical-red)" }}>
              {err.field}: {err.message}
            </p>
          ))}
        </div>
      )}

      {graphErrors.length > 0 && (
        <div role="alert" className="mb-3">
          {graphErrors.map((err, i) => (
            <p key={i} style={{ fontSize: 12, color: "var(--pr-critical-red)" }}>
              Compilation blocked: {err.message}
            </p>
          ))}
        </div>
      )}

      {message && (
        <p role="alert" style={{ fontSize: 13, color: "var(--pr-text-secondary)", marginBottom: 8 }}>{message}</p>
      )}

      {candidate.status === "pending_review" ? (
        <div className="flex gap-2">
          <button
            onClick={save}
            disabled={saving}
            className="rounded-lg border"
            style={{ color: "var(--pr-text-secondary)", fontSize: 13, padding: "8px 14px", borderColor: "var(--pr-overlay-10)" }}
          >
            Save draft
          </button>
          <button
            onClick={dismiss}
            disabled={saving}
            className="rounded-lg border"
            style={{ color: "var(--pr-critical-red)", fontSize: 13, padding: "8px 14px", borderColor: "rgba(239,68,68,0.3)" }}
          >
            Dismiss
          </button>
          <Button
            variant="primary"
            onClick={promote}
            disabled={saving || (graphGated && !graphReady)}
            title={graphGated && !graphReady ? "This candidate is not yet grounded in an approved Authority Graph version." : undefined}
          >
            {graphGated ? "Compile to Runtime Policy" : "Promote to Policy Studio"}
          </Button>
        </div>
      ) : candidate.status === "promoted" && candidate.promoted_policy_key ? (
        <div className="flex items-center gap-2 flex-wrap">
          <Link to={`/governance/${candidate.promoted_policy_key}`} style={{ color: "var(--pr-trust-green)", fontSize: 13 }}>
            View in Policy Studio
          </Link>
          {promoteResult?.authority_id && (
            <span
              style={{
                fontSize: 11,
                fontFamily: "monospace",
                color: "var(--pr-authority-blue)",
                backgroundColor: "var(--pr-bg-hover)",
                borderRadius: 999,
                padding: "2px 8px",
              }}
            >
              Linked to Authority {promoteResult.authority_id}
            </span>
          )}
          {promoteResult?.source_graph_version && (
            <span
              style={{
                fontSize: 11,
                fontFamily: "monospace",
                color: "var(--pr-trust-green)",
                backgroundColor: "var(--pr-bg-hover)",
                borderRadius: 999,
                padding: "2px 8px",
              }}
            >
              Generated from Authority Graph v{promoteResult.source_graph_version}
            </span>
          )}
        </div>
      ) : (
        <p style={{ fontSize: 13, color: "var(--pr-text-muted)" }}>Dismissed.</p>
      )}
    </div>
  );
}
