import { useEffect, useId, useState } from "react";
import { integrationsApi, type CreateMappingBody } from "../api";
import { describeApiError } from "../../live/format";
import { policyStudioApi } from "../../policy-studio/api";
import { humanizeAction } from "../helpers";
import { Alert } from "../../components/ui/alert";
import { Button } from "../../components/ui/button";
import { Select } from "../../components/ui/select";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetFooter } from "../../components/ui/sheet";
import type { ActionMapping } from "../types";

// Trusted Integration Architecture, Phase 4 (sections 9-12): a guided
// DRAFT-mapping form. Only fields the backend actually supports
// (integration_contract.py's CreateContractVersionRequest); no
// transformation-expression language, no invented ontology.

interface ContextField {
  key: string;
  value: string;
}

function toContextBindings(fields: ContextField[]): Record<string, string> {
  return Object.fromEntries(fields.filter((f) => f.key.trim() !== "").map((f) => [f.key.trim(), f.value.trim()]));
}

function fromContextBindings(bindings: Record<string, string>): ContextField[] {
  const entries = Object.entries(bindings);
  return entries.length > 0 ? entries.map(([key, value]) => ({ key, value: String(value) })) : [{ key: "", value: "" }];
}

export function MappingFormSheet({ open, onOpenChange, systemId, systemLabel, editingMapping, onSaved }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  systemId: string;
  systemLabel: string;
  // Present -> editing this DRAFT mapping's fields; absent -> creating new.
  editingMapping?: ActionMapping | null;
  onSaved: (mapping: ActionMapping) => void;
}) {
  const formId = useId();
  const [actions, setActions] = useState<string[]>([]);
  const [sourceOperation, setSourceOperation] = useState("");
  const [canonicalAction, setCanonicalAction] = useState("");
  const [resourcePath, setResourcePath] = useState("");
  const [factSubjectPath, setFactSubjectPath] = useState("");
  const [amountPath, setAmountPath] = useState("");
  const [currencyPath, setCurrencyPath] = useState("");
  const [contextFields, setContextFields] = useState<ContextField[]>([{ key: "", value: "" }]);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [sourceSchemaFingerprint, setSourceSchemaFingerprint] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    policyStudioApi.getVocabulary().then((v) => setActions(v.actions)).catch(() => setActions([]));
    if (editingMapping) {
      setSourceOperation(editingMapping.source_operation);
      setCanonicalAction(editingMapping.canonical_action);
      setResourcePath(editingMapping.resource_path ?? "");
      setFactSubjectPath(editingMapping.fact_subject_path ?? "");
      setAmountPath(editingMapping.amount_path ?? "");
      setCurrencyPath(editingMapping.currency_path ?? "");
      setContextFields(fromContextBindings(editingMapping.context_bindings));
      setSourceSchemaFingerprint(editingMapping.source_schema_fingerprint ?? "");
    } else {
      setSourceOperation("");
      setCanonicalAction("");
      setResourcePath("");
      setFactSubjectPath("");
      setAmountPath("");
      setCurrencyPath("");
      setContextFields([{ key: "", value: "" }]);
      setSourceSchemaFingerprint("");
    }
    setError(null);
  }, [open, editingMapping]);

  async function handleSave() {
    if (!sourceOperation.trim() || !canonicalAction) return;
    setSaving(true);
    setError(null);
    const body: CreateMappingBody = {
      source_operation: sourceOperation.trim(),
      canonical_action: canonicalAction,
      resource_path: resourcePath.trim() || null,
      fact_subject_path: factSubjectPath.trim() || null,
      amount_path: amountPath.trim() || null,
      currency_path: currencyPath.trim() || null,
      context_bindings: toContextBindings(contextFields),
      source_schema_fingerprint: sourceSchemaFingerprint.trim() || null,
    };
    try {
      const saved = editingMapping
        ? await integrationsApi.editMapping(systemId, editingMapping.id, body)
        : await integrationsApi.createMapping(systemId, body);
      onOpenChange(false);
      onSaved(saved);
    } catch (e) {
      setError(describeApiError(e, editingMapping ? "Save mapping" : "Create mapping"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-lg flex flex-col p-0 gap-0" style={{ backgroundColor: "var(--pr-bg-card)" }}>
        <SheetHeader className="border-b" style={{ borderColor: "var(--pr-overlay-05)" }}>
          <SheetTitle>{editingMapping ? "Edit action mapping" : "New action mapping"}</SheetTitle>
          <SheetDescription>
            This tells PayReality what an action in {systemLabel} means. It starts as a draft --
            nothing here affects real decisions until it's validated and approved.
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto p-4">
          <div className="grid grid-cols-1 gap-3 mb-4">
            <div>
              <label htmlFor={`${formId}-source`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                External action in {systemLabel}
              </label>
              <input
                id={`${formId}-source`}
                value={sourceOperation}
                onChange={(e) => setSourceOperation(e.target.value)}
                placeholder="e.g. ChangeSupplierBankDetails"
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
              <p className="text-[11px] mt-1" style={{ color: "var(--pr-text-disabled)" }}>
                Exactly what the system itself calls this action -- an API method, event name, or
                transaction code.
              </p>
            </div>

            <div>
              <label htmlFor={`${formId}-action`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                What this means to PayReality
              </label>
              <Select
                id={`${formId}-action`}
                value={canonicalAction}
                onChange={(e) => setCanonicalAction(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border text-sm"
                containerClassName="block w-full"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              >
                <option value="">Select an action...</option>
                {actions.map((a) => <option key={a} value={a}>{humanizeAction(a)}</option>)}
              </Select>
              {sourceOperation && canonicalAction && (
                <p className="text-[11px] mt-1.5 px-2 py-1.5 rounded" style={{ backgroundColor: "var(--pr-overlay-05)", color: "var(--pr-text-secondary)" }}>
                  &ldquo;{sourceOperation}&rdquo; means &ldquo;{humanizeAction(canonicalAction)}&rdquo; to PayReality.
                </p>
              )}
            </div>

            <div>
              <label htmlFor={`${formId}-resource`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                Where can PayReality find the resource? <span style={{ color: "var(--pr-text-disabled)", fontWeight: 400 }}>(optional)</span>
              </label>
              <input
                id={`${formId}-resource`}
                value={resourcePath}
                onChange={(e) => setResourcePath(e.target.value)}
                placeholder="e.g. supplier.id"
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
            </div>

            <div>
              <label htmlFor={`${formId}-subject`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                Where can PayReality find who/what this action is about? <span style={{ color: "var(--pr-text-disabled)", fontWeight: 400 }}>(optional)</span>
              </label>
              <input
                id={`${formId}-subject`}
                value={factSubjectPath}
                onChange={(e) => setFactSubjectPath(e.target.value)}
                placeholder="e.g. supplier.id"
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
              <p className="text-[11px] mt-1" style={{ color: "var(--pr-text-disabled)" }}>
                Used to check trusted facts about this subject (e.g. "is this supplier approved?").
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor={`${formId}-amount`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                  Where's the amount? <span style={{ color: "var(--pr-text-disabled)", fontWeight: 400 }}>(optional)</span>
                </label>
                <input
                  id={`${formId}-amount`}
                  value={amountPath}
                  onChange={(e) => setAmountPath(e.target.value)}
                  placeholder="e.g. payment.amount"
                  className="w-full px-3 py-2 rounded-lg border text-sm"
                  style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
                />
              </div>
              <div>
                <label htmlFor={`${formId}-currency`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                  Where's the currency? <span style={{ color: "var(--pr-text-disabled)", fontWeight: 400 }}>(optional)</span>
                </label>
                <input
                  id={`${formId}-currency`}
                  value={currencyPath}
                  onChange={(e) => setCurrencyPath(e.target.value)}
                  placeholder="e.g. payment.currency"
                  className="w-full px-3 py-2 rounded-lg border text-sm"
                  style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                What other information from this action can affect PayReality's decision? <span style={{ color: "var(--pr-text-disabled)", fontWeight: 400 }}>(optional)</span>
              </label>
              <p className="text-[11px] mb-2" style={{ color: "var(--pr-text-disabled)" }}>
                Only the fields listed here are trusted -- e.g. region, payment type, supplier
                category. Anything not listed here is never used to decide.
              </p>
              {contextFields.map((f, i) => (
                <div key={i} style={{ display: "flex", gap: 6, marginBottom: 6 }}>
                  <input
                    value={f.key}
                    onChange={(e) => { const next = [...contextFields]; next[i] = { ...next[i], key: e.target.value }; setContextFields(next); }}
                    placeholder="Field name (e.g. region)"
                    aria-label="Trusted context field name"
                    className="px-2 py-1.5 rounded-lg border text-sm"
                    style={{ flex: 1, backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
                  />
                  <input
                    value={f.value}
                    onChange={(e) => { const next = [...contextFields]; next[i] = { ...next[i], value: e.target.value }; setContextFields(next); }}
                    placeholder="Where to find it (e.g. region.code)"
                    aria-label="Trusted context field location"
                    className="px-2 py-1.5 rounded-lg border text-sm"
                    style={{ flex: 1, backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
                  />
                  <button
                    type="button"
                    onClick={() => setContextFields(contextFields.filter((_, j) => j !== i))}
                    aria-label="Remove field"
                    className="px-2 rounded-lg border text-sm"
                    style={{ borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-muted)" }}
                  >
                    &times;
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={() => setContextFields([...contextFields, { key: "", value: "" }])}
                className="text-xs"
                style={{ color: "var(--pr-authority-blue)" }}
              >
                + Add field
              </button>
            </div>

            <div>
              <button
                type="button"
                onClick={() => setShowAdvanced((s) => !s)}
                className="text-xs"
                style={{ color: "var(--pr-text-muted)" }}
              >
                {showAdvanced ? "Hide advanced" : "Show advanced"}
              </button>
              {showAdvanced && (
                <div className="mt-2">
                  <label htmlFor={`${formId}-fingerprint`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                    Source schema fingerprint <span style={{ color: "var(--pr-text-disabled)", fontWeight: 400 }}>(optional, for your own audit records)</span>
                  </label>
                  <input
                    id={`${formId}-fingerprint`}
                    value={sourceSchemaFingerprint}
                    onChange={(e) => setSourceSchemaFingerprint(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border text-sm font-mono"
                    style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
                  />
                  <p className="text-[11px] mt-1" style={{ color: "var(--pr-text-disabled)" }}>
                    Not used by PayReality's decisions -- a record of which version of the source
                    system's own schema you mapped from, for your own drift-checking later. If
                    you're not sure what to put here, leave it blank and ask a developer.
                  </p>
                </div>
              )}
            </div>
          </div>

          {error && <Alert severity="error" className="text-sm">{error}</Alert>}
        </div>

        <SheetFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSave} disabled={!sourceOperation.trim() || !canonicalAction || saving}>
            {saving ? "Saving..." : editingMapping ? "Save draft" : "Create draft mapping"}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
