import { useState } from "react";
import { Sparkles, Send, Loader2, AlertTriangle } from "lucide-react";
import { Sheet, SheetContent, SheetTitle, SheetDescription } from "../../components/ui/sheet";
import { Button } from "../../components/ui/button";
import { describeApiError } from "../../live/format";
import { policyDraftingApi, type DraftResponse } from "../draftingApi";
import { EFFECT_LABEL } from "../describePolicy";
import type { RuntimePolicyRequest } from "../types";

type Mode = "draft" | "edit" | "explain";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentDraft: RuntimePolicyRequest;
  deterministicSummary: string;
  hasContent: boolean;
  onApply: (proposal: RuntimePolicyRequest) => void;
}

// Product Experience V3.2, Part C: the central invariant (section 31) is
// enforced structurally here, not just by convention -- this component
// has no code path that calls save/publish/approve. `onApply` merges a
// validated proposal into the CALLER's own form state; applying is
// never saving, and saving (PolicyWorkspacePage's own handleSave) remains
// a separate, explicit, unchanged action the user takes afterward.
export function DraftWithAIPanel({ open, onOpenChange, currentDraft, deterministicSummary, hasContent, onApply }: Props) {
  const [mode, setMode] = useState<Mode>("draft");
  const [instruction, setInstruction] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DraftResponse | null>(null);
  const [explanation, setExplanation] = useState<string | null>(null);

  function reset() {
    setResult(null);
    setExplanation(null);
    setError(null);
  }

  async function handleSend() {
    if (!instruction.trim() && mode !== "explain") return;
    setLoading(true);
    setError(null);
    setResult(null);
    setExplanation(null);
    try {
      if (mode === "explain") {
        const text = await policyDraftingApi.explain(currentDraft, deterministicSummary, instruction.trim() || undefined);
        setExplanation(text);
      } else {
        // Draft and Edit are the same call (section 34/35): Edit simply
        // supplies the current draft as additional context. The manual
        // rule itself (currentDraft, held by the caller) is never
        // touched by this call -- only `result` here changes, which is
        // this panel's own local proposal-preview state.
        const response = await policyDraftingApi.draft(instruction, mode === "edit" ? currentDraft : null);
        setResult(response);
      }
    } catch (e) {
      // Section 65: keep the manual rule unchanged, say clearly that the
      // proposal could not be generated, allow retry -- never partially
      // mutate anything here, since nothing has been applied yet at this
      // point regardless of what error occurs.
      setError(describeApiError(e, "Draft with AI"));
    } finally {
      setLoading(false);
    }
  }

  function handleApply() {
    if (!result?.proposal) return;
    onApply(result.proposal);
    reset();
    setInstruction("");
  }

  const canApply = !!result?.proposal && result.unknown_entities.length === 0 && !result.clarifying_question;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-[420px] max-w-[92vw] flex flex-col p-0 gap-0 border-l"
        style={{ backgroundColor: "var(--pr-bg-secondary)", borderColor: "var(--pr-overlay-05)" }}
      >
        <SheetTitle className="sr-only">Draft with AI</SheetTitle>
        <SheetDescription className="sr-only">
          Describe organisational authority in plain language; PayReality proposes structured rule fields for you to
          review and apply. AI never creates or approves organisational authority on its own.
        </SheetDescription>

        <div className="px-5 py-4 border-b flex items-center gap-2" style={{ borderColor: "var(--pr-overlay-05)" }}>
          <Sparkles className="w-4 h-4" style={{ color: "var(--pr-authority-blue)" }} />
          <h2 className="text-sm font-semibold" style={{ color: "var(--pr-text-primary)" }}>Draft with AI</h2>
        </div>

        <div className="flex gap-1 px-5 pt-3" role="tablist" aria-label="AI assistant mode">
          {(["draft", "edit", "explain"] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              onClick={() => {
                setMode(m);
                reset();
              }}
              className="px-3 py-1.5 rounded-lg text-xs font-medium capitalize"
              style={{
                backgroundColor: mode === m ? "color-mix(in srgb, var(--pr-authority-blue) 14%, transparent)" : "transparent",
                color: mode === m ? "var(--pr-authority-blue)" : "var(--pr-text-muted)",
                transitionDuration: "var(--pr-motion-fast)",
              }}
            >
              {m}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          <p className="text-xs mb-3" style={{ color: "var(--pr-text-muted)" }}>
            {mode === "draft" && "Describe the organisational authority you want to express. AI proposes rule fields for you to review, never creates authority on its own."}
            {mode === "edit" && (hasContent ? "Describe how to change the rule currently open in the builder." : "Start describing this rule below, then switch to Draft.")}
            {mode === "explain" && "Ask about the rule currently open in the builder, in plain language."}
          </p>

          <div className="flex gap-2 mb-4">
            <textarea
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder={
                mode === "explain"
                  ? "What does this rule mean? (optional, leave blank for a general explanation)"
                  : "e.g. Only allow the CFO to create vendor payments up to R250,000. Anything above that should need human approval."
              }
              rows={3}
              className="form-field flex-1"
              style={{
                backgroundColor: "var(--pr-bg-primary)",
                border: "1px solid var(--pr-overlay-10)",
                color: "var(--pr-text-primary)",
                borderRadius: 8,
                padding: "8px 10px",
                fontSize: 13,
                resize: "none",
              }}
              disabled={loading}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  handleSend();
                }
              }}
            />
          </div>
          <Button onClick={handleSend} disabled={loading || (!instruction.trim() && mode !== "explain")} size="sm">
            {loading ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" style={{ animationDuration: "var(--pr-motion-slow)" }} />
                Thinking...
              </>
            ) : (
              <>
                <Send size={13} />
                {mode === "explain" ? "Explain" : mode === "edit" ? "Propose changes" : "Draft"}
              </>
            )}
          </Button>

          {error && (
            <div role="alert" className="mt-4 p-3 rounded-lg text-xs flex items-start gap-2" style={{ backgroundColor: "color-mix(in srgb, var(--pr-critical-red) 10%, transparent)", color: "var(--pr-critical-red)" }}>
              <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
              <span>{error} Your current rule is unchanged. You can try again, or keep editing manually.</span>
            </div>
          )}

          {explanation && (
            <div className="mt-4 p-3 rounded-lg text-sm" style={{ backgroundColor: "var(--pr-overlay-03)", color: "var(--pr-text-primary)" }}>
              {explanation}
            </div>
          )}

          {result?.clarifying_question && (
            <div className="mt-4 p-3 rounded-lg text-sm" style={{ backgroundColor: "color-mix(in srgb, var(--pr-warning-amber) 10%, transparent)", color: "var(--pr-text-primary)" }}>
              <p className="font-medium mb-1" style={{ color: "var(--pr-warning-amber)" }}>Needs clarification</p>
              {result.clarifying_question}
            </div>
          )}

          {result && result.unknown_entities.length > 0 && (
            <div className="mt-4 p-3 rounded-lg text-sm" style={{ backgroundColor: "color-mix(in srgb, var(--pr-warning-amber) 10%, transparent)", color: "var(--pr-text-primary)" }}>
              <p className="font-medium mb-1" style={{ color: "var(--pr-warning-amber)" }}>
                Not a registered entity in this organisation
              </p>
              <ul className="space-y-1">
                {result.unknown_entities.map((u) => (
                  <li key={`${u.field}-${u.value}`}>
                    "{u.value}" is not a registered {u.field} in this organisation.
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs" style={{ color: "var(--pr-text-muted)" }}>
                Register the missing entity first through its own page, then try again.
              </p>
            </div>
          )}

          {result?.proposal && (
            <div className="mt-4">
              <p className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: "var(--pr-authority-blue)" }}>
                AI-proposed changes
              </p>
              <DiffPreview current={currentDraft} proposal={result.proposal} hasContent={hasContent} />
              {result.requires_additional_policies && result.additional_policies_note && (
                <p className="mt-2 text-xs" style={{ color: "var(--pr-warning-amber)" }}>
                  This may need more than one rule: {result.additional_policies_note}
                </p>
              )}
              {result.missing_fields.length > 0 && (
                <p className="mt-2 text-xs" style={{ color: "var(--pr-text-muted)" }}>
                  Not confidently determined: {result.missing_fields.join(", ")}
                </p>
              )}
              <div className="flex gap-2 mt-3">
                <Button onClick={handleApply} disabled={!canApply} size="sm">
                  Apply proposal
                </Button>
                <Button onClick={reset} variant="ghost" size="sm">
                  Keep current rule
                </Button>
              </div>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function fieldRow(label: string, before: string, after: string) {
  if (before === after) return null;
  return (
    <div key={label} className="flex items-start justify-between gap-3 py-1.5 border-b text-xs" style={{ borderColor: "var(--pr-overlay-04)" }}>
      <span style={{ color: "var(--pr-text-muted)" }}>{label}</span>
      <span className="text-right">
        <span style={{ color: "var(--pr-text-disabled)", textDecoration: before !== "(none)" ? "line-through" : undefined }}>
          {before}
        </span>
        {" -> "}
        <span style={{ color: "var(--pr-text-primary)", fontWeight: 500 }}>{after}</span>
      </span>
    </div>
  );
}

// Product Experience V3.2, section 39: shows exactly what will change
// before it's applied. Compares only the fields this proposal actually
// sets, never a full-object dump.
function DiffPreview({ current, proposal, hasContent }: { current: RuntimePolicyRequest; proposal: RuntimePolicyRequest; hasContent: boolean }) {
  const before = hasContent ? current : ({ scope: { principal: "", action: "", agent: null, resource: null }, conditions: [], effect: "require_human_review", constraints: current.constraints } as RuntimePolicyRequest);
  const na = (v: string | null | undefined) => (v ? v : "(none)");

  return (
    <div className="rounded-lg p-3" style={{ backgroundColor: "var(--pr-bg-primary)", border: "1px solid var(--pr-overlay-06)" }}>
      {fieldRow("Principal", na(before.scope.principal), na(proposal.scope.principal))}
      {fieldRow("Agent", na(before.scope.agent), na(proposal.scope.agent))}
      {fieldRow("Action", na(before.scope.action), na(proposal.scope.action))}
      {fieldRow("Resource", na(before.scope.resource), na(proposal.scope.resource))}
      {fieldRow("Conditions", String(before.conditions.length), String(proposal.conditions.length))}
      {fieldRow("Delegated by", na(before.constraints.delegated_by), na(proposal.constraints.delegated_by))}
      {fieldRow("Outcome", EFFECT_LABEL[before.effect] ?? before.effect, EFFECT_LABEL[proposal.effect] ?? proposal.effect)}
    </div>
  );
}
