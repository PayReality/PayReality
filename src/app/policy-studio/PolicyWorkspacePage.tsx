import { useEffect, useId, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { policyStudioApi } from "./api";
import { organizationApi } from "../organization/api";
import type { EnterpriseSystem } from "../organization/types";
import type { Condition, Constraints, Effect, Metadata, RuntimePolicy, RuntimePolicyRequest, Scope } from "./types";
import { PolicyStatusBadge } from "./components/PolicyStatusBadge";
import { ConditionRow } from "./components/ConditionRow";
import { ScopeFields } from "./components/ScopeFields";
import { LifecycleTimeline } from "./components/LifecycleTimeline";
import { describeApiError } from "../live/format";
import { describePolicy, EFFECT_LABEL } from "./describePolicy";
import { track, trackError } from "../services/analytics";
import { Card } from "../components/ui/card";
import { FieldLabel } from "../components/ui/label";
import { Input, getInputStyle } from "../components/ui/input";
import { Button } from "../components/ui/button";
import { ConfirmButton } from "../components/ui/confirm-button";
import { Alert } from "../components/ui/alert";
import { policyLifecycleApi } from "./lifecycleApi";
import { useAuth } from "../auth/AuthContext";
import { useResourceSync } from "../services/resourceSync";
import { PageHeader } from "../components/ui/page-header";
import { AuthorityChain } from "../components/ui/authority-chain";
import { ShieldCheck, FileCheck } from "lucide-react";

const EMPTY: RuntimePolicyRequest = {
  name: "",
  description: "",
  scope: { principal: "", action: "", agent: null, resource: null },
  conditions: [],
  effect: "require_human_review",
  constraints: {
    delegated_by: null, expires: null, evidence_required: true, risk_level: null,
    authority_id: null, mandate_id: null, enterprise_system_id: null,
  },
  metadata: { owner: null, created_by: null, tags: [] },
};

export function PolicyWorkspacePage() {
  const { policyKey } = useParams();
  const isNew = !policyKey || policyKey === "new";
  const navigate = useNavigate();
  const formId = useId();
  const { user, hasPermission } = useAuth();

  const [existing, setExisting] = useState<RuntimePolicy | null>(null);
  const [form, setForm] = useState<RuntimePolicyRequest>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [tagInput, setTagInput] = useState("");
  const [actor, setActor] = useState("");
  const [lifecycleMessage, setLifecycleMessage] = useState<string | null>(null);
  const canPublish = !user || hasPermission("runtime_policy.publish");

  useEffect(() => {
    if (user) setActor(user.name);
  }, [user]);
  // Phase 5, Release 2 (Enterprise System binding): the configuration
  // surface for which registered system this policy's allowed action
  // reaches -- lives here, alongside delegated_by/risk_level, not in
  // Organisation Settings' Enterprise Systems tab (which only needs to
  // list/create systems, unchanged by this release).
  const [enterpriseSystems, setEnterpriseSystems] = useState<EnterpriseSystem[]>([]);

  function loadEnterpriseSystems() {
    organizationApi.listEnterpriseSystems().then(setEnterpriseSystems).catch(() => setEnterpriseSystems([]));
  }

  useEffect(loadEnterpriseSystems, []);
  // Milestone 14: this dropdown had no way to learn a system was
  // registered elsewhere (e.g. Organisation Settings, open in another
  // tab) -- "organization" had zero consumers anywhere in the app before
  // this.
  useResourceSync(["organization"], loadEnterpriseSystems);

  const [loadError, setLoadError] = useState<string | null>(null);

  function loadExisting() {
    if (isNew) return;
    setLoadError(null);
    policyStudioApi
      .get(policyKey!)
      .then((p) => {
        setExisting(p);
        setForm({
          name: p.name,
          description: p.description,
          scope: p.scope,
          conditions: p.conditions,
          effect: p.effect,
          constraints: p.constraints,
          metadata: p.metadata,
        });
      })
      .catch((e) => setLoadError(describeApiError(e, "Loading policy")));
  }

  // Milestone 14: this fetch used to have no .catch() -- a failure left
  // `existing` null forever with no error shown, and since `isNew` is
  // derived only from the URL param (not from whether the fetch
  // succeeded), the page silently rendered as a blank "New Rule" form
  // for what was actually an existing policy that failed to load.
  useEffect(loadExisting, [isNew, policyKey]);

  async function handleSave() {
    if (!form.scope.principal.trim() || !form.scope.action.trim()) {
      setMessage("Who this applies to, and what action, are both required before a rule can be saved.");
      return;
    }
    setSaving(true);
    setMessage(null);
    const startedAt = Date.now();
    try {
      const saved = isNew ? await policyStudioApi.create(form) : await policyStudioApi.edit(policyKey!, form);
      if (isNew) {
        track("Runtime Policy Generated", {
          policy_id: saved.policy_key,
          source: "manual",
          runtime_policy_generation_ms: Date.now() - startedAt,
        });
      }
      setMessage(`Saved as draft, v${saved.version}.`);
      if (isNew) navigate(`/governance/${saved.policy_key}`);
      else setExisting(saved);
    } catch (e) {
      setMessage(describeApiError(e, "Save"));
      if (isNew) {
        trackError("Runtime Policy Generation Failed", {
          error_type: e instanceof Error ? e.name : "unknown_error",
          component: "policy_studio_manual",
          duration_ms: Date.now() - startedAt,
        });
      }
    } finally {
      setSaving(false);
    }
  }

  async function handleSubmitForReview() {
    setSaving(true);
    setMessage(null);
    try {
      const updated = await policyStudioApi.submitForReview(policyKey!);
      setExisting(updated);
      setMessage("Submitted for review.");
    } catch (e) {
      setMessage(describeApiError(e, "Submit"));
    } finally {
      setSaving(false);
    }
  }

  async function runLifecycleAction(action: (key: string, actor: string) => Promise<unknown>, label: string) {
    if (!actor.trim()) {
      setLifecycleMessage("Enter your name first.");
      return;
    }
    setLifecycleMessage(null);
    try {
      await action(policyKey!, actor);
      setLifecycleMessage(`${label} recorded.`);
      const refreshed = await policyStudioApi.get(policyKey!);
      setExisting(refreshed);
    } catch (e) {
      setLifecycleMessage(describeApiError(e, label));
    }
  }

  function updateCondition(index: number, next: Condition) {
    setForm((f) => ({ ...f, conditions: f.conditions.map((c, i) => (i === index ? next : c)) }));
  }
  function removeCondition(index: number) {
    setForm((f) => ({ ...f, conditions: f.conditions.filter((_, i) => i !== index) }));
  }
  function addCondition() {
    setForm((f) => ({ ...f, conditions: [...f.conditions, { field: "", operator: "==", value: "" }] }));
  }
  function updateScope(scope: Scope) {
    setForm((f) => ({ ...f, scope }));
  }
  function updateConstraints(constraints: Constraints) {
    setForm((f) => ({ ...f, constraints }));
  }
  function updateMetadata(metadata: Metadata) {
    setForm((f) => ({ ...f, metadata }));
  }
  function addTag() {
    if (!tagInput.trim()) return;
    updateMetadata({ ...form.metadata, tags: [...form.metadata.tags, tagInput.trim()] });
    setTagInput("");
  }
  function removeTag(tag: string) {
    updateMetadata({ ...form.metadata, tags: form.metadata.tags.filter((t) => t !== tag) });
  }

  if (!isNew && !existing && loadError) {
    return (
      <div className="p-8 max-w-3xl">
        <Link to="/governance" style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>
          &lt; Back to Governance
        </Link>
        <Alert severity="error" className="text-sm mt-4">
          <div className="flex items-center gap-3">
            <span>{loadError}</span>
            <Button variant="ghost" size="sm" onClick={loadExisting}>Retry</Button>
          </div>
        </Alert>
      </div>
    );
  }

  // QA pass: without this branch, an existing policy still being fetched
  // rendered the blank EMPTY-form fields (the same shape as authoring a
  // genuinely new rule) until loadExisting() resolved and overwrote
  // whatever the reviewer had already started typing, with no warning.
  if (!isNew && !existing) {
    return <div className="p-8" style={{ color: "var(--pr-text-muted)" }}>Loading...</div>;
  }

  return (
    <div className="p-8 max-w-3xl" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <div className="mb-2">
        <Link to="/governance" style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>
          &lt; Back to Governance
        </Link>
      </div>

      <PageHeader
        title={form.name || "New Rule"}
        status={
          existing && (
            <span className="flex items-center gap-2">
              <span style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>v{existing.version}</span>
              <PolicyStatusBadge status={existing.status} />
            </span>
          )
        }
        primaryAction={
          <Button onClick={handleSave} disabled={saving}>
            {saving ? "Saving..." : "Save draft"}
          </Button>
        }
      />

      {message && (
        <p role="alert" style={{ color: "var(--pr-text-secondary)", marginBottom: 16 }}>{message}</p>
      )}

      {existing && (
        <div className="mb-4 flex gap-3 text-sm">
          <Link to={`/governance/${policyKey}/versions`} style={{ color: "var(--pr-authority-blue)" }}>
            History
          </Link>
          <Link to={`/governance/${policyKey}/simulate`} style={{ color: "var(--pr-authority-blue)" }}>
            Simulate
          </Link>
          {existing.status === "draft" && (
            <ConfirmButton
              variant="ghost"
              onConfirm={handleSubmitForReview}
              disabled={saving}
              confirmLabel="Submit"
              style={{ color: "var(--pr-authority-blue)" }}
            >
              Submit for review
            </ConfirmButton>
          )}
          {(existing.status === "approved" || existing.status === "compiled" || existing.status === "active") && (
            <Link to={`/governance/${policyKey}/publish`} style={{ color: "var(--pr-authority-blue)" }}>
              Publish
            </Link>
          )}
          {canPublish && existing.status === "active" && (
            <>
              <ConfirmButton
                variant="ghost"
                onConfirm={() => runLifecycleAction(policyLifecycleApi.deprecate, "Deprecate")}
                confirmLabel="Deprecate"
                style={{ color: "var(--pr-warning-amber)" }}
              >
                Deprecate
              </ConfirmButton>
              <ConfirmButton
                variant="ghost"
                onConfirm={() => runLifecycleAction(policyLifecycleApi.retire, "Retire")}
                confirmLabel="Retire"
                style={{ color: "var(--pr-critical-red)" }}
              >
                Retire
              </ConfirmButton>
            </>
          )}
          {canPublish && existing.status !== "active" && existing.status !== "archived" && existing.status !== "draft" && (
            <ConfirmButton
              variant="ghost"
              onConfirm={() => runLifecycleAction(policyLifecycleApi.archive, "Archive")}
              confirmLabel="Archive"
              style={{ color: "var(--pr-text-muted)" }}
            >
              Archive
            </ConfirmButton>
          )}
        </div>
      )}

      {existing && canPublish && (existing.status === "active" || (existing.status !== "draft" && existing.status !== "archived")) && (
        <div className="mb-4 flex items-center gap-2" style={{ fontSize: 12 }}>
          <label htmlFor={`${formId}-actor`} style={{ color: "var(--pr-text-muted)" }}>
            {user ? "Acting as" : "Your name (for lifecycle actions)"}
          </label>
          <input
            id={`${formId}-actor`}
            value={actor}
            onChange={(e) => setActor(e.target.value)}
            readOnly={!!user}
            style={{
              backgroundColor: user ? "var(--pr-bg-primary)" : "var(--pr-bg-hover)",
              border: "1px solid var(--pr-overlay-10)",
              color: user ? "var(--pr-text-muted)" : "var(--pr-text-primary)",
              borderRadius: 6, padding: "4px 8px", fontSize: 12, width: 180,
            }}
          />
        </div>
      )}

      {lifecycleMessage && (
        <p role="alert" style={{ color: "var(--pr-text-secondary)", fontSize: 13, marginBottom: 16 }}>{lifecycleMessage}</p>
      )}

      <Card borderColor="rgba(77,124,254,0.25)" style={{ marginBottom: 16 }}>
        <h2 className="text-sm font-medium mb-2" style={{ color: "var(--pr-text-muted)" }}>In plain English</h2>
        <p style={{ color: "var(--pr-text-primary)", fontSize: 15 }}>{describePolicy(form)}</p>
      </Card>

      <Card style={{ marginBottom: 16 }}>
        <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>Identity</h2>
        <FieldLabel htmlFor={`${formId}-name`}>Name</FieldLabel>
        <Input
          id={`${formId}-name`}
          style={{ marginBottom: 10 }}
          value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
        />
        <FieldLabel htmlFor={`${formId}-description`}>Description</FieldLabel>
        <Input
          id={`${formId}-description`}
          value={form.description ?? ""}
          onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
        />
      </Card>

      <Card style={{ marginBottom: 16 }}>
        <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>Who, what, and when</h2>
        <ScopeFields scope={form.scope} onChange={updateScope} />
      </Card>

      <Card style={{ marginBottom: 16 }}>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>
            Conditions (all must hold)
          </h2>
          <button onClick={addCondition} style={{ color: "var(--pr-authority-blue)", fontSize: 13 }}>
            + Add condition
          </button>
        </div>
        {form.conditions.map((c, i) => (
          <ConditionRow key={i} condition={c} onChange={(next) => updateCondition(i, next)} onRemove={() => removeCondition(i)} />
        ))}
        {form.conditions.length === 0 && (
          <p style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>No conditions yet: this policy matches on scope alone.</p>
        )}
      </Card>

      <Card style={{ marginBottom: 16 }}>
        <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>Constraints</h2>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <FieldLabel htmlFor={`${formId}-delegated-by`}>Delegated by</FieldLabel>
            <Input
              id={`${formId}-delegated-by`}
              placeholder="Role or person"
              value={form.constraints.delegated_by ?? ""}
              onChange={(e) => updateConstraints({ ...form.constraints, delegated_by: e.target.value || null })}
            />
            <p style={{ fontSize: 11, color: "var(--pr-text-muted)", marginTop: 3 }}>
              The organisational authority this rule enforces, not who wrote it.
            </p>
          </div>
          <div>
            <FieldLabel htmlFor={`${formId}-risk-level`}>Risk level</FieldLabel>
            <select
              id={`${formId}-risk-level`}
              style={getInputStyle()}
              value={form.constraints.risk_level ?? ""}
              onChange={(e) => updateConstraints({ ...form.constraints, risk_level: e.target.value || null })}
            >
              <option value="">(none)</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="critical">critical</option>
            </select>
          </div>
        </div>
        <label className="flex items-center gap-2 mt-3" style={{ fontSize: 13, color: "var(--pr-text-secondary)" }}>
          <input
            type="checkbox"
            checked={form.constraints.evidence_required}
            onChange={(e) => updateConstraints({ ...form.constraints, evidence_required: e.target.checked })}
          />
          Evidence required
        </label>
        <div className="mt-3">
          <FieldLabel htmlFor={`${formId}-enterprise-system`}>Enterprise System (optional)</FieldLabel>
          <select
            id={`${formId}-enterprise-system`}
            style={getInputStyle()}
            value={form.constraints.enterprise_system_id ?? ""}
            onChange={(e) => updateConstraints({ ...form.constraints, enterprise_system_id: e.target.value || null })}
          >
            <option value="">(none)</option>
            {enterpriseSystems.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
          <p style={{ fontSize: 11, color: "var(--pr-text-muted)", marginTop: 3 }}>
            Which downstream system this rule's allowed action ultimately reaches, if any. Recorded
            on every Decision this rule produces.
          </p>
        </div>
        {(form.constraints.authority_id || form.constraints.mandate_id) && (
          <div className="mt-4" data-tour="policy-authority-block">
            <AuthorityChain
              links={[
                ...(form.constraints.authority_id
                  ? [{ icon: ShieldCheck, label: "Authority", value: form.constraints.authority_id }]
                  : []),
                ...(form.constraints.mandate_id
                  ? [{ icon: FileCheck, label: "Mandate", value: form.constraints.mandate_id }]
                  : []),
              ]}
            />
          </div>
        )}
      </Card>

      <Card style={{ marginBottom: 16 }}>
        <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>What should happen</h2>
        <div className="flex gap-4">
          {(["allow", "deny", "require_human_review"] as Effect[]).map((eff) => (
            <label key={eff} className="flex items-center gap-2" style={{ fontSize: 13, color: "var(--pr-text-secondary)" }}>
              <input type="radio" checked={form.effect === eff} onChange={() => setForm((f) => ({ ...f, effect: eff }))} />
              {EFFECT_LABEL[eff]}
            </label>
          ))}
        </div>
      </Card>

      <Card style={{ marginBottom: 16 }}>
        <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>Metadata</h2>
        <FieldLabel htmlFor={`${formId}-owner`}>Owner</FieldLabel>
        <Input
          id={`${formId}-owner`}
          style={{ marginBottom: 3 }}
          value={form.metadata.owner ?? ""}
          onChange={(e) => updateMetadata({ ...form.metadata, owner: e.target.value || null })}
        />
        <p style={{ fontSize: 11, color: "var(--pr-text-muted)", marginTop: 0, marginBottom: 10 }}>
          Who maintains this rule day to day, distinct from "Delegated by" above.
        </p>
        <FieldLabel htmlFor={`${formId}-tag-input`}>Tags</FieldLabel>
        <div className="flex gap-2 flex-wrap mb-2">
          {form.metadata.tags.map((t) => (
            <span key={t} style={getInputStyle("hover", { width: "auto", display: "inline-flex", alignItems: "center", gap: 6 })}>
              {t}
              <button
                onClick={() => removeTag(t)}
                aria-label={`Remove tag ${t}`}
                style={{ color: "var(--pr-critical-red)", padding: "2px 4px" }}
              >
                x
              </button>
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <Input
            id={`${formId}-tag-input`}
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            placeholder="New tag"
          />
          <button onClick={addTag} style={{ color: "var(--pr-authority-blue)", fontSize: 13, padding: "6px 8px" }}>
            + Add tag
          </button>
        </div>
      </Card>

      {existing && (
        <Card style={{ marginBottom: 16 }}>
          <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>Timeline</h2>
          <LifecycleTimeline policyKey={policyKey!} />
        </Card>
      )}
    </div>
  );
}
