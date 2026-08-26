import { useEffect, useState } from "react";
import { Link } from "react-router";
import { organizationApi, organizationStructureApi } from "./api";
import { RequirePermission } from "../auth/RequireAuth";
import { describeApiError } from "../live/format";
import { getTheme, setTheme, type Theme } from "../lib/theme";
import type {
  BusinessUnit,
  Department,
  EnterpriseSystem,
  EnterpriseSystemStatus,
  EnterpriseSystemType,
  HealthState,
  HealthStatus,
  IntegrationsStatus,
  IntegrationStatus,
  OrganizationSettings,
  Team,
} from "./types";

const cardStyle: React.CSSProperties = {
  backgroundColor: "var(--pr-bg-card)",
  border: "1px solid var(--pr-overlay-05)",
  borderRadius: 12,
};

// Core Product Experience Redesign, section 10: renamed from "Runtime
// Authority" -- this tab is fallback-defaults configuration (default
// review/policy behavior, evidence retention, decision logging), not
// the product's core "Runtime Authority" pillar itself. Colliding tab
// and product-concept names is the exact confusion the nav rename to
// "Decisions" already fixed once (see Layout.tsx's own comment on why
// "Authority" was renamed away from the nav). Frontend label only --
// no backend field or settings key is renamed.
const TABS = [
  "General",
  "Organisation Structure",
  "Security",
  "Decision Defaults",
  "Integrations",
  "Enterprise Systems",
  "Notifications",
  "Audit",
  "Organisation Health",
  "About",
] as const;

type Tab = (typeof TABS)[number];

function fieldLabelStyle(): React.CSSProperties {
  return { color: "var(--pr-text-muted)", display: "block", marginBottom: 6 };
}

function inputStyle(): React.CSSProperties {
  return {
    backgroundColor: "var(--pr-input-bg)",
    color: "var(--pr-text-primary)",
    border: "1px solid var(--pr-overlay-08)",
    borderRadius: 8,
    padding: "8px 10px",
    fontSize: 13,
    width: "100%",
  };
}

function SaveButton({ onClick, saving }: { onClick: () => void; saving: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={saving}
      className="text-sm font-medium px-4 py-2 rounded-lg mt-4"
      style={{ backgroundColor: "var(--pr-authority-blue)", color: "white", opacity: saving ? 0.6 : 1 }}
    >
      {saving ? "Saving..." : "Save changes"}
    </button>
  );
}

const HEALTH_COLORS: Record<HealthState, string> = {
  healthy: "var(--pr-trust-green)",
  warning: "var(--pr-warning-amber)",
  offline: "var(--pr-critical-red)",
};

const INTEGRATION_COLORS: Record<IntegrationStatus, string> = {
  connected: "var(--pr-trust-green)",
  configuration_required: "var(--pr-warning-amber)",
  disconnected: "var(--pr-critical-red)",
};

const ENTERPRISE_SYSTEM_STATUS_COLORS: Record<EnterpriseSystemStatus, string> = {
  connected: "var(--pr-trust-green)",
  configuration_required: "var(--pr-warning-amber)",
};

const ENTERPRISE_SYSTEM_TYPES: EnterpriseSystemType[] = [
  "erp", "crm", "finance", "hr", "procurement", "legal", "manufacturing", "other",
];

function Pill({ label, color }: { label: string; color: string }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full"
      style={{ backgroundColor: `${color}1a`, color }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: color }} />
      {label}
    </span>
  );
}

function humanize(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function GeneralTab({ settings, onSaved }: { settings: OrganizationSettings; onSaved: (s: OrganizationSettings) => void }) {
  const [name, setName] = useState(settings.name);
  const [timezone, setTimezone] = useState(settings.timezone);
  const [currency, setCurrency] = useState(settings.default_currency);
  const [language, setLanguage] = useState(settings.default_language);
  const [logoUrl, setLogoUrl] = useState(settings.logo_url ?? "");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      const updated = await organizationApi.updateSettings({
        name,
        timezone,
        default_currency: currency,
        default_language: language,
        logo_url: logoUrl || null,
      });
      onSaved(updated);
      setMessage("Saved.");
    } catch (e) {
      setMessage(describeApiError(e, "Save"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4 max-w-md">
      <div>
        <label htmlFor="org-settings-name" style={fieldLabelStyle()}>Organisation Name</label>
        <input id="org-settings-name" style={inputStyle()} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div>
        <label htmlFor="org-settings-logo-url" style={fieldLabelStyle()}>Logo URL</label>
        <input id="org-settings-logo-url" style={inputStyle()} value={logoUrl} onChange={(e) => setLogoUrl(e.target.value)} placeholder="https://..." />
      </div>
      <div>
        <label htmlFor="org-settings-timezone" style={fieldLabelStyle()}>Timezone</label>
        <input id="org-settings-timezone" style={inputStyle()} value={timezone} onChange={(e) => setTimezone(e.target.value)} />
      </div>
      <div>
        <label htmlFor="org-settings-currency" style={fieldLabelStyle()}>Default Currency</label>
        <input id="org-settings-currency" style={inputStyle()} value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} maxLength={3} />
      </div>
      <div>
        <label htmlFor="org-settings-language" style={fieldLabelStyle()}>Default Language</label>
        <input id="org-settings-language" style={inputStyle()} value={language} onChange={(e) => setLanguage(e.target.value)} />
      </div>
      <SaveButton onClick={save} saving={saving} />
      {message && <p role="alert" className="text-xs" style={{ color: "var(--pr-text-muted)" }}>{message}</p>}

      <AppearanceSection />
    </div>
  );
}

function AppearanceSection() {
  const [theme, setThemeState] = useState<Theme>(() => getTheme());

  function choose(next: Theme) {
    setTheme(next);
    setThemeState(next);
  }

  return (
    <div style={{ ...cardStyle, padding: 16 }} className="mt-6">
      <h3 className="text-sm font-medium mb-1" style={{ color: "var(--pr-text-primary)" }}>Appearance</h3>
      <p className="text-xs mb-3" style={{ color: "var(--pr-text-muted)" }}>
        Light or dark mode for this browser. This is a personal display preference, not an
        organisation-wide setting -- it isn't saved to the organisation and won't affect anyone
        else's view of the platform.
      </p>
      <div className="flex gap-2">
        {(["light", "dark"] as const).map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => choose(option)}
            className="text-sm font-medium px-4 py-2 rounded-lg capitalize"
            style={
              theme === option
                ? { backgroundColor: "var(--pr-authority-blue)", color: "white" }
                : { border: "1px solid var(--pr-overlay-10)", color: "var(--pr-text-secondary)" }
            }
          >
            {option}
          </button>
        ))}
      </div>
    </div>
  );
}

function EditableRow({
  name,
  onRename,
  onDelete,
  deleteTitle,
}: {
  name: string;
  onRename: (name: string) => Promise<void>;
  onDelete: () => Promise<void>;
  deleteTitle?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const [busy, setBusy] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  async function save() {
    if (!draft.trim() || draft.trim() === name) {
      setEditing(false);
      setDraft(name);
      return;
    }
    setBusy(true);
    try {
      await onRename(draft.trim());
    } finally {
      setBusy(false);
      setEditing(false);
    }
  }

  async function confirmDelete() {
    setBusy(true);
    try {
      await onDelete();
    } finally {
      setBusy(false);
      setConfirmingDelete(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      {editing ? (
        <>
          <input
            style={{ ...inputStyle(), width: 200 }}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && save()}
            autoFocus
          />
          <button type="button" onClick={save} disabled={busy} style={{ color: "var(--pr-authority-blue)", fontSize: 12 }}>
            Save
          </button>
          <button
            type="button"
            onClick={() => { setEditing(false); setDraft(name); }}
            style={{ color: "var(--pr-text-muted)", fontSize: 12 }}
          >
            Cancel
          </button>
        </>
      ) : (
        <>
          <span className="text-sm" style={{ color: "var(--pr-text-primary)" }}>{name}</span>
          <button type="button" onClick={() => setEditing(true)} style={{ color: "var(--pr-text-muted)", fontSize: 11 }}>
            Rename
          </button>
          {confirmingDelete ? (
            <>
              <button type="button" onClick={confirmDelete} disabled={busy} style={{ color: "var(--pr-critical-red)", fontSize: 11 }}>
                {busy ? "Deleting..." : "Confirm delete"}
              </button>
              <button type="button" onClick={() => setConfirmingDelete(false)} disabled={busy} style={{ color: "var(--pr-text-muted)", fontSize: 11 }}>
                Cancel
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmingDelete(true)}
              title={deleteTitle}
              style={{ color: "var(--pr-critical-red)", fontSize: 11 }}
            >
              Delete
            </button>
          )}
        </>
      )}
    </div>
  );
}

function OrganisationStructureTab({ settings }: { settings: OrganizationSettings }) {
  const [units, setUnits] = useState<BusinessUnit[] | null>(null);
  const [departments, setDepartments] = useState<Department[] | null>(null);
  const [teams, setTeams] = useState<Team[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [newUnitName, setNewUnitName] = useState("");
  const [newDeptName, setNewDeptName] = useState<Record<string, string>>({});
  const [newTeamName, setNewTeamName] = useState<Record<string, string>>({});

  function load() {
    organizationStructureApi.listBusinessUnits().then(setUnits).catch(() => setUnits([]));
    organizationStructureApi.listDepartments().then(setDepartments).catch(() => setDepartments([]));
    organizationStructureApi.listTeams().then(setTeams).catch(() => setTeams([]));
  }
  useEffect(load, []);

  async function withReload(fn: () => Promise<unknown>, action: string) {
    setMessage(null);
    try {
      await fn();
      load();
    } catch (e) {
      setMessage(describeApiError(e, action));
    }
  }

  async function addUnit() {
    if (!newUnitName.trim()) return;
    await withReload(() => organizationStructureApi.createBusinessUnit(newUnitName.trim()), "Create business unit");
    setNewUnitName("");
  }

  async function addDepartment(businessUnitId: string) {
    const name = newDeptName[businessUnitId];
    if (!name?.trim()) return;
    await withReload(
      () => organizationStructureApi.createDepartment(businessUnitId, name.trim()),
      "Create department"
    );
    setNewDeptName((prev) => ({ ...prev, [businessUnitId]: "" }));
  }

  async function addTeam(departmentId: string) {
    const name = newTeamName[departmentId];
    if (!name?.trim()) return;
    await withReload(() => organizationStructureApi.createTeam(departmentId, name.trim()), "Create team");
    setNewTeamName((prev) => ({ ...prev, [departmentId]: "" }));
  }

  return (
    <div style={{ ...cardStyle, padding: 16, maxWidth: 640 }}>
      <p className="text-xs mb-1" style={{ color: "var(--pr-text-muted)" }}>
        The organisational hierarchy Principals and Agents are placed into -- visible on Agent
        Detail and used by Runtime Authority Context resolution. Renaming is supported; moving a
        unit under a different parent is not, create a new one under the right parent instead.
      </p>
      <p className="text-sm font-medium mb-4" style={{ color: "var(--pr-text-primary)" }}>{settings.name}</p>

      {message && <p role="alert" className="text-xs mb-3" style={{ color: "var(--pr-critical-red)" }}>{message}</p>}

      <div className="space-y-4 mb-4">
        {(units ?? []).map((unit) => {
          const unitDepartments = (departments ?? []).filter((d) => d.business_unit_id === unit.id);
          return (
            <div key={unit.id} className="pl-3" style={{ borderLeft: "2px solid var(--pr-authority-blue)" }}>
              <EditableRow
                name={unit.name}
                onRename={(name) => withReload(() => organizationStructureApi.updateBusinessUnit(unit.id, name), "Rename business unit")}
                onDelete={() => withReload(() => organizationStructureApi.deleteBusinessUnit(unit.id), "Delete business unit")}
                deleteTitle="Remove its Departments and any Principal assigned to it first"
              />
              <div className="pl-4 mt-2 space-y-3">
                {unitDepartments.map((dept) => {
                  const deptTeams = (teams ?? []).filter((t) => t.department_id === dept.id);
                  return (
                    <div key={dept.id} className="pl-3" style={{ borderLeft: "2px solid var(--pr-overlay-10)" }}>
                      <EditableRow
                        name={dept.name}
                        onRename={(name) => withReload(() => organizationStructureApi.updateDepartment(dept.id, name), "Rename department")}
                        onDelete={() => withReload(() => organizationStructureApi.deleteDepartment(dept.id), "Delete department")}
                        deleteTitle="Remove its Teams and any Principal assigned to it first"
                      />
                      <div className="pl-4 mt-1 space-y-1">
                        {deptTeams.map((team) => (
                          <EditableRow
                            key={team.id}
                            name={team.name}
                            onRename={(name) => withReload(() => organizationStructureApi.updateTeam(team.id, name), "Rename team")}
                            onDelete={() => withReload(() => organizationStructureApi.deleteTeam(team.id), "Delete team")}
                            deleteTitle="Remove any Principal assigned to it first"
                          />
                        ))}
                        <div className="flex gap-2 mt-1">
                          <input
                            style={{ ...inputStyle(), width: 160 }}
                            placeholder="New team"
                            value={newTeamName[dept.id] ?? ""}
                            onChange={(e) => setNewTeamName((prev) => ({ ...prev, [dept.id]: e.target.value }))}
                            onKeyDown={(e) => e.key === "Enter" && addTeam(dept.id)}
                          />
                          <button type="button" onClick={() => addTeam(dept.id)} style={{ color: "var(--pr-authority-blue)", fontSize: 12 }}>
                            + Add team
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
                <div className="flex gap-2">
                  <input
                    style={{ ...inputStyle(), width: 180 }}
                    placeholder="New department"
                    value={newDeptName[unit.id] ?? ""}
                    onChange={(e) => setNewDeptName((prev) => ({ ...prev, [unit.id]: e.target.value }))}
                    onKeyDown={(e) => e.key === "Enter" && addDepartment(unit.id)}
                  />
                  <button type="button" onClick={() => addDepartment(unit.id)} style={{ color: "var(--pr-authority-blue)", fontSize: 12 }}>
                    + Add department
                  </button>
                </div>
              </div>
            </div>
          );
        })}
        {units?.length === 0 && <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>No business units yet.</p>}
      </div>

      <div className="flex gap-2 pt-3" style={{ borderTop: "1px solid var(--pr-overlay-05)" }}>
        <input
          style={{ ...inputStyle(), width: 220 }}
          placeholder="New business unit"
          value={newUnitName}
          onChange={(e) => setNewUnitName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addUnit()}
        />
        <button
          type="button"
          onClick={addUnit}
          className="text-sm font-medium px-4 py-2 rounded-lg"
          style={{ backgroundColor: "var(--pr-authority-blue)", color: "white" }}
        >
          + Add business unit
        </button>
      </div>
    </div>
  );
}

function SecurityTab({ settings, onSaved }: { settings: OrganizationSettings; onSaved: (s: OrganizationSettings) => void }) {
  const extra = settings.settings ?? {};
  const [sessionTimeout, setSessionTimeout] = useState(String(extra.session_timeout_minutes ?? 480));
  const [mfaRequired, setMfaRequired] = useState(Boolean(extra.mfa_required));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      const updated = await organizationApi.updateSettings({
        settings: {
          session_timeout_minutes: Number(sessionTimeout) || 480,
          mfa_required: mfaRequired,
        },
      });
      onSaved(updated);
      setMessage("Saved.");
    } catch (e) {
      setMessage(describeApiError(e, "Save"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <div style={{ ...cardStyle, padding: 16 }}>
        <h3 className="text-sm font-medium mb-1" style={{ color: "var(--pr-text-primary)" }}>Operator Key</h3>
        <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>
          The shared superuser credential (ADMIN_API_KEY) is set as a deploy-time environment variable,
          not something this UI can rotate live. See EVIDENCE_KEY_ROTATION.md's runbook pattern for how
          a similar rotation is done safely; the same real-runbook approach applies here.
        </p>
      </div>

      <div style={{ ...cardStyle, padding: 16 }}>
        <h3 className="text-sm font-medium mb-1" style={{ color: "var(--pr-text-primary)" }}>Signature Window</h3>
        <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>
          Intent signatures are valid for a fixed window (server INTENT_SIGNATURE_WINDOW_SECONDS),
          configured per deployment, not per organisation.
        </p>
      </div>

      <div className="max-w-md space-y-4">
        <div>
          <label htmlFor="org-settings-session-timeout" style={fieldLabelStyle()}>Session Timeout (minutes)</label>
          <input
            id="org-settings-session-timeout"
            type="number"
            min={5}
            style={inputStyle()}
            value={sessionTimeout}
            onChange={(e) => setSessionTimeout(e.target.value)}
          />
        </div>
        <label className="flex items-center gap-2 text-sm" style={{ color: "var(--pr-text-primary)" }}>
          <input type="checkbox" checked={mfaRequired} onChange={(e) => setMfaRequired(e.target.checked)} />
          Require MFA for all users
        </label>
        <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>
          This sets the requirement only. A full enrolment/verification flow isn't built yet -- see
          RBAC.md's disclosed scope.
        </p>
        <SaveButton onClick={save} saving={saving} />
        {message && <p role="alert" className="text-xs" style={{ color: "var(--pr-text-muted)" }}>{message}</p>}
      </div>

      <ApiKeysSection />
    </div>
  );
}

function ApiKeysSection() {
  const [keys, setKeys] = useState<import("./types").ApiKey[] | null>(null);
  const [name, setName] = useState("");
  const [role, setRole] = useState("auditor");
  const [rawKey, setRawKey] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmingRevokeId, setConfirmingRevokeId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  function load() {
    organizationApi.listApiKeys().then(setKeys).catch(() => setKeys([]));
  }
  useEffect(load, []);

  async function create() {
    if (!name.trim() || creating) return;
    setCreating(true);
    try {
      const result = await organizationApi.createApiKey(name, role);
      setRawKey(result.raw_key);
      setName("");
      load();
    } catch (e) {
      setMessage(describeApiError(e, "Create API key"));
    } finally {
      setCreating(false);
    }
  }

  async function revoke(id: string) {
    try {
      await organizationApi.revokeApiKey(id);
      load();
    } catch (e) {
      setMessage(describeApiError(e, "Revoke"));
    } finally {
      setConfirmingRevokeId(null);
    }
  }

  return (
    <div style={{ ...cardStyle, padding: 16 }}>
      <h3 className="text-sm font-medium mb-1" style={{ color: "var(--pr-text-primary)" }}>API Keys</h3>
      <p className="text-xs mb-3" style={{ color: "var(--pr-text-muted)" }}>
        Each key is scoped to a role, and each role carries the same decision rights whether a
        person or an API key is exercising it, not a separate credential-only permission set.
      </p>
      <div className="flex flex-wrap gap-2 mb-3">
        <input
          style={{ ...inputStyle(), width: 200 }}
          placeholder="Key name (e.g. CI pipeline)"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <select style={{ ...inputStyle(), width: 180 }} value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="owner">Organisation Owner</option>
          <option value="governance_admin">Governance Administrator</option>
          <option value="agent_admin">Agent Administrator</option>
          <option value="reviewer">Reviewer</option>
          <option value="auditor">Auditor</option>
          <option value="executive">Executive</option>
        </select>
        <button
          type="button"
          onClick={create}
          disabled={creating}
          className="text-sm font-medium px-4 py-2 rounded-lg disabled:opacity-60"
          style={{ backgroundColor: "var(--pr-authority-blue)", color: "white" }}
        >
          {creating ? "Creating..." : "Create key"}
        </button>
      </div>

      {rawKey && (
        <div className="mb-3 p-3 rounded-lg text-xs" style={{ backgroundColor: "rgba(245,158,11,0.1)", color: "var(--pr-warning-amber)" }}>
          Copy this now -- it won't be shown again: <code className="break-all">{rawKey}</code>
        </div>
      )}
      {message && <p role="alert" className="text-xs mb-2" style={{ color: "var(--pr-text-muted)" }}>{message}</p>}

      <div className="space-y-1.5">
        {(keys ?? []).map((k) => (
          <div key={k.id} className="flex items-center justify-between gap-3 text-xs py-1.5" style={{ color: "var(--pr-text-secondary)" }}>
            <span style={{ wordBreak: "break-word" }}>
              {k.name} <span style={{ color: "var(--pr-text-muted)" }}>({k.key_prefix}...)</span> -- {humanize(k.role)}
            </span>
            {k.revoked_at ? (
              <span style={{ color: "var(--pr-text-disabled)" }}>Revoked</span>
            ) : confirmingRevokeId === k.id ? (
              <span className="flex items-center gap-2">
                <button type="button" onClick={() => revoke(k.id)} style={{ color: "var(--pr-critical-red)" }}>
                  Confirm revoke
                </button>
                <button type="button" onClick={() => setConfirmingRevokeId(null)} style={{ color: "var(--pr-text-muted)" }}>
                  Cancel
                </button>
              </span>
            ) : (
              <button type="button" onClick={() => setConfirmingRevokeId(k.id)} style={{ color: "var(--pr-critical-red)" }}>
                Revoke
              </button>
            )}
          </div>
        ))}
        {keys?.length === 0 && <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>No API keys yet.</p>}
      </div>
    </div>
  );
}

function RuntimeAuthorityTab({ settings, onSaved }: { settings: OrganizationSettings; onSaved: (s: OrganizationSettings) => void }) {
  const extra = settings.settings ?? {};
  const [reviewBehavior, setReviewBehavior] = useState(String(extra.default_human_review_behavior ?? "escalate"));
  const [retentionDays, setRetentionDays] = useState(String(extra.evidence_retention_days ?? 2555));
  const [policyBehavior, setPolicyBehavior] = useState(String(extra.default_policy_behavior ?? "deny"));
  const [decisionLogging, setDecisionLogging] = useState(extra.decision_logging_enabled !== false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      const updated = await organizationApi.updateSettings({
        settings: {
          default_human_review_behavior: reviewBehavior,
          evidence_retention_days: Number(retentionDays) || 2555,
          default_policy_behavior: policyBehavior,
          decision_logging_enabled: decisionLogging,
        },
      });
      onSaved(updated);
      setMessage("Saved.");
    } catch (e) {
      setMessage(describeApiError(e, "Save"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-md space-y-4">
      <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>
        These are the organisation-wide defaults Runtime Authority falls back to when a specific
        rule doesn't cover a case, not a replacement for your own delegated authority and rules.
      </p>
      <div>
        <label htmlFor="org-settings-review-behavior" style={fieldLabelStyle()}>Default Human Review Behaviour</label>
        <select id="org-settings-review-behavior" style={inputStyle()} value={reviewBehavior} onChange={(e) => setReviewBehavior(e.target.value)}>
          <option value="escalate">Escalate to Review Queue</option>
          <option value="deny">Deny by default</option>
        </select>
      </div>
      <div>
        <label htmlFor="org-settings-evidence-retention" style={fieldLabelStyle()}>Evidence Retention (days)</label>
        <input id="org-settings-evidence-retention" type="number" min={1} style={inputStyle()} value={retentionDays} onChange={(e) => setRetentionDays(e.target.value)} />
        <p className="text-xs mt-1" style={{ color: "var(--pr-text-muted)" }}>
          Recorded as policy today; no automated purge job exists yet.
        </p>
      </div>
      <div>
        <label htmlFor="org-settings-policy-behavior" style={fieldLabelStyle()}>Default Policy Behaviour</label>
        <select id="org-settings-policy-behavior" style={inputStyle()} value={policyBehavior} onChange={(e) => setPolicyBehavior(e.target.value)}>
          <option value="deny">Fail closed (deny)</option>
          <option value="review">Fail to human review</option>
        </select>
      </div>
      <label className="flex items-center gap-2 text-sm" style={{ color: "var(--pr-text-primary)" }}>
        <input type="checkbox" checked={decisionLogging} onChange={(e) => setDecisionLogging(e.target.checked)} />
        Decision logging enabled
      </label>
      <SaveButton onClick={save} saving={saving} />
      {message && <p role="alert" className="text-xs" style={{ color: "var(--pr-text-muted)" }}>{message}</p>}
    </div>
  );
}

function IntegrationsTab() {
  const [status, setStatus] = useState<IntegrationsStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setError(null);
    organizationApi
      .getIntegrations()
      .then(setStatus)
      .catch((e) => setError(describeApiError(e, "Loading integration status")));
  }
  useEffect(load, []);

  const rows: Array<{ key: keyof IntegrationsStatus; label: string }> = [
    { key: "azure_ai_foundry", label: "Azure AI Foundry" },
    { key: "anthropic", label: "Anthropic" },
    { key: "azure_openai", label: "Azure OpenAI" },
    { key: "aws_bedrock", label: "AWS Bedrock" },
    { key: "opa", label: "OPA" },
    { key: "postgresql", label: "PostgreSQL" },
  ];

  return (
    <div style={{ ...cardStyle, padding: 16, maxWidth: 480 }}>
      <p className="text-xs mb-4" style={{ color: "var(--pr-text-muted)" }}>
        These are the components Runtime Authority itself runs on. The enterprise systems it
        protects, the ERP, CRM, procurement, and finance systems an agent's action ultimately
        reaches, are registered separately under the Enterprise Systems tab.
      </p>
      {error && (
        <p role="alert" className="text-xs mb-3" style={{ color: "var(--pr-warning-amber)" }}>
          {error} <button type="button" onClick={load} style={{ color: "var(--pr-authority-blue)", textDecoration: "underline" }}>Retry</button>
        </p>
      )}
      <div className="space-y-3">
        {rows.map((row) => (
          <div key={row.key} className="flex items-center justify-between gap-3">
            <span className="text-sm" style={{ color: "var(--pr-text-primary)" }}>{row.label}</span>
            {status ? (
              <Pill label={humanize(status[row.key])} color={INTEGRATION_COLORS[status[row.key]]} />
            ) : error ? (
              <span className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Unknown</span>
            ) : (
              <span className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Checking...</span>
            )}
          </div>
        ))}
      </div>
      <p className="text-xs mt-4" style={{ color: "var(--pr-text-muted)" }}>
        Azure OpenAI and AWS Bedrock have no integration built yet -- shown honestly as
        "Configuration Required," never fabricated as Connected.
      </p>
    </div>
  );
}

function EnterpriseSystemsTab() {
  const [systems, setSystems] = useState<EnterpriseSystem[] | null>(null);
  const [name, setName] = useState("");
  const [type, setType] = useState<EnterpriseSystemType>("erp");
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  function load() {
    organizationApi.listEnterpriseSystems().then(setSystems).catch(() => setSystems([]));
  }
  useEffect(load, []);

  async function create() {
    if (!name.trim()) return;
    setCreating(true);
    setMessage(null);
    try {
      await organizationApi.createEnterpriseSystem(name.trim(), type);
      setName("");
      load();
    } catch (e) {
      setMessage(describeApiError(e, "Register"));
    } finally {
      setCreating(false);
    }
  }

  return (
    <div style={{ ...cardStyle, padding: 16, maxWidth: 520 }}>
      <p className="text-xs mb-4" style={{ color: "var(--pr-text-muted)" }}>
        The downstream systems (ERP, CRM, Finance, HR, Procurement, ...) an agent's allowed action
        ultimately reaches. Registering one here only records that it exists -- it does not connect
        it. No connector exists for any system yet, so status always shows honestly as
        "Configuration Required," never fabricated as Connected.
      </p>
      <div className="flex flex-wrap gap-2 mb-4">
        <input
          style={{ ...inputStyle(), width: 220 }}
          placeholder="System name (e.g. SAP S/4HANA)"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <select
          style={{ ...inputStyle(), width: 160 }}
          value={type}
          onChange={(e) => setType(e.target.value as EnterpriseSystemType)}
        >
          {ENTERPRISE_SYSTEM_TYPES.map((t) => (
            <option key={t} value={t}>{humanize(t)}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={create}
          disabled={creating || !name.trim()}
          className="text-sm font-medium px-4 py-2 rounded-lg disabled:opacity-50"
          style={{ backgroundColor: "var(--pr-authority-blue)", color: "white" }}
        >
          {creating ? "Registering..." : "Register system"}
        </button>
      </div>
      {message && <p role="alert" className="text-xs mb-3" style={{ color: "var(--pr-critical-red)" }}>{message}</p>}

      <div className="space-y-1.5">
        {(systems ?? []).map((s) => (
          <div key={s.id} className="flex items-center justify-between gap-3 text-sm py-1.5" style={{ color: "var(--pr-text-secondary)" }}>
            <span style={{ wordBreak: "break-word" }}>
              {s.name} <span style={{ color: "var(--pr-text-muted)", fontSize: 12 }}>({humanize(s.type)})</span>
            </span>
            <Pill label={humanize(s.status)} color={ENTERPRISE_SYSTEM_STATUS_COLORS[s.status]} />
          </div>
        ))}
        {systems?.length === 0 && (
          <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>No enterprise systems registered yet.</p>
        )}
      </div>
    </div>
  );
}

function NotificationsTab({ settings, onSaved }: { settings: OrganizationSettings; onSaved: (s: OrganizationSettings) => void }) {
  const extra = (settings.settings?.notifications as Record<string, unknown>) ?? {};
  const [email, setEmail] = useState(Boolean(extra.email));
  const [slack, setSlack] = useState(Boolean(extra.slack));
  const [teams, setTeams] = useState(Boolean(extra.teams));
  const [webhookUrl, setWebhookUrl] = useState(String(extra.webhook_url ?? ""));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      const updated = await organizationApi.updateSettings({
        settings: { notifications: { email, slack, teams, webhook_url: webhookUrl } },
      });
      onSaved(updated);
      setMessage("Saved.");
    } catch (e) {
      setMessage(describeApiError(e, "Save"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-md space-y-3">
      <p className="text-xs mb-2" style={{ color: "var(--pr-text-muted)" }}>
        These preferences are stored, not yet wired to real delivery -- no email, Slack, or Teams
        integration exists in this platform today.
      </p>
      <label className="flex items-center gap-2 text-sm" style={{ color: "var(--pr-text-primary)" }}>
        <input type="checkbox" checked={email} onChange={(e) => setEmail(e.target.checked)} /> Email
      </label>
      <label className="flex items-center gap-2 text-sm" style={{ color: "var(--pr-text-primary)" }}>
        <input type="checkbox" checked={slack} onChange={(e) => setSlack(e.target.checked)} /> Slack
      </label>
      <label className="flex items-center gap-2 text-sm" style={{ color: "var(--pr-text-primary)" }}>
        <input type="checkbox" checked={teams} onChange={(e) => setTeams(e.target.checked)} /> Microsoft Teams
      </label>
      <div>
        <label htmlFor="org-settings-webhook-url" style={fieldLabelStyle()}>Webhook URL</label>
        <input id="org-settings-webhook-url" style={inputStyle()} value={webhookUrl} onChange={(e) => setWebhookUrl(e.target.value)} placeholder="https://..." />
      </div>
      <SaveButton onClick={save} saving={saving} />
      {message && <p role="alert" className="text-xs" style={{ color: "var(--pr-text-muted)" }}>{message}</p>}
    </div>
  );
}

function AuditTab({ settings, onSaved }: { settings: OrganizationSettings; onSaved: (s: OrganizationSettings) => void }) {
  const extra = settings.settings ?? {};
  const [retentionDays, setRetentionDays] = useState(String(extra.audit_retention_days ?? 2555));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      const updated = await organizationApi.updateSettings({
        settings: { audit_retention_days: Number(retentionDays) || 2555 },
      });
      onSaved(updated);
      setMessage("Saved.");
    } catch (e) {
      setMessage(describeApiError(e, "Save"));
    } finally {
      setSaving(false);
    }
  }

  async function exportEvidence() {
    setExporting(true);
    try {
      const records = await organizationApi.exportEvidence();
      const blob = new Blob([JSON.stringify(records, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "evidence-export.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setMessage(describeApiError(e, "Export"));
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="max-w-md space-y-4">
      <div>
        <label htmlFor="org-settings-audit-retention" style={fieldLabelStyle()}>Audit Retention (days)</label>
        <input id="org-settings-audit-retention" type="number" min={1} style={inputStyle()} value={retentionDays} onChange={(e) => setRetentionDays(e.target.value)} />
      </div>
      <SaveButton onClick={save} saving={saving} />
      {message && <p role="alert" className="text-xs" style={{ color: "var(--pr-text-muted)" }}>{message}</p>}

      <div className="pt-2">
        <p className="text-xs mb-2" style={{ color: "var(--pr-text-muted)" }}>
          "Audit Export" and "Evidence Export" are the same underlying ledger in this platform --
          every signed Evidence record IS the audit trail.
        </p>
        <button
          type="button"
          onClick={exportEvidence}
          disabled={exporting}
          className="text-sm font-medium px-4 py-2 rounded-lg"
          style={{ border: "1px solid var(--pr-authority-blue)", color: "var(--pr-authority-blue)" }}
        >
          {exporting ? "Exporting..." : "Export evidence (JSON)"}
        </button>
      </div>
    </div>
  );
}

function OrganisationHealthTab() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  useEffect(() => {
    organizationApi.getHealth().then(setHealth);
  }, []);

  const rows: Array<{ key: keyof HealthStatus; label: string }> = [
    { key: "runtime_authority", label: "Runtime Authority Engine" },
    { key: "evidence_engine", label: "Evidence Engine" },
    { key: "opa", label: "OPA" },
    { key: "compiler", label: "Compiler" },
    { key: "database", label: "Database" },
    { key: "anthropic", label: "Anthropic" },
  ];

  return (
    <div style={{ ...cardStyle, padding: 16, maxWidth: 480 }}>
      <div className="space-y-3">
        {rows.map((row) => (
          <div key={row.key} className="flex items-center justify-between gap-3">
            <span className="text-sm" style={{ color: "var(--pr-text-primary)" }}>{row.label}</span>
            {health ? (
              <Pill label={humanize(health[row.key])} color={HEALTH_COLORS[health[row.key]]} />
            ) : (
              <span className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Checking...</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function AboutTab() {
  const [version, setVersion] = useState<{ version: string; commit: string } | null>(null);
  useEffect(() => {
    const base = import.meta.env.VITE_API_URL ?? "/api";
    fetch(`${base}/version`)
      .then((r) => r.json())
      .then(setVersion)
      .catch(() => setVersion(null));
  }, []);

  return (
    <div style={{ ...cardStyle, padding: 16, maxWidth: 480 }}>
      <dl className="space-y-3 text-sm">
        <div className="flex justify-between">
          <dt style={{ color: "var(--pr-text-muted)" }}>Version</dt>
          <dd style={{ color: "var(--pr-text-primary)" }}>{version?.version ?? "..."}</dd>
        </div>
        <div className="flex justify-between">
          <dt style={{ color: "var(--pr-text-muted)" }}>Build</dt>
          <dd style={{ color: "var(--pr-text-primary)" }} className="font-mono text-xs">{version?.commit ?? "..."}</dd>
        </div>
        <div className="flex justify-between">
          <dt style={{ color: "var(--pr-text-muted)" }}>Deployment</dt>
          <dd style={{ color: "var(--pr-text-primary)" }}>Render + Vercel (Azure staged, not yet live)</dd>
        </div>
        <div className="flex justify-between">
          <dt style={{ color: "var(--pr-text-muted)" }}>Documentation</dt>
          <dd><a href="https://github.com/AI-Securewatch/Pay-Reality-" style={{ color: "var(--pr-authority-blue)" }}>GitHub</a></dd>
        </div>
        <div className="flex justify-between">
          <dt style={{ color: "var(--pr-text-muted)" }}>Support</dt>
          <dd style={{ color: "var(--pr-text-primary)" }}>sean@aisecurewatch.com</dd>
        </div>
        <div className="flex justify-between">
          <dt style={{ color: "var(--pr-text-muted)" }}>Status Page</dt>
          <dd><Link to="/organization?tab=Organisation+Health" style={{ color: "var(--pr-authority-blue)" }}>Organisation Health</Link></dd>
        </div>
      </dl>
    </div>
  );
}

export function OrganizationSettingsPage() {
  const [tab, setTab] = useState<Tab>("General");
  const [settings, setSettings] = useState<OrganizationSettings | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setError(null);
    organizationApi.getSettings().then(setSettings).catch((e) => setError(describeApiError(e, "Load settings")));
  }
  useEffect(load, []);

  return (
    <RequirePermission permission="settings.view">
      <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
        <div className="mb-6">
          <h1 className="mb-2" style={{ color: "var(--pr-text-primary)" }}>Organisation Settings</h1>
          <p style={{ color: "var(--pr-text-muted)", fontSize: 13, maxWidth: 640 }}>
            How this organisation is configured, who has access, and whether the platform is healthy.{" "}
            <Link to="/organization/users" style={{ color: "var(--pr-authority-blue)" }}>Manage users and roles →</Link>
            {" "}
            <Link to="/organization/platform" style={{ color: "var(--pr-authority-blue)" }}>Platform administration →</Link>
          </p>
        </div>

        <div
          role="tablist"
          aria-label="Organisation settings sections"
          className="flex flex-wrap gap-1 mb-6 border-b pb-0"
          style={{ borderColor: "var(--pr-overlay-05)" }}
        >
          {TABS.map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              id={`org-tab-${t}`}
              aria-selected={tab === t}
              aria-controls={`org-tabpanel-${t}`}
              tabIndex={tab === t ? 0 : -1}
              onClick={() => setTab(t)}
              onKeyDown={(e) => {
                if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
                e.preventDefault();
                const idx = TABS.indexOf(t);
                const nextIdx = e.key === "ArrowRight" ? (idx + 1) % TABS.length : (idx - 1 + TABS.length) % TABS.length;
                const next = TABS[nextIdx];
                setTab(next);
                document.getElementById(`org-tab-${next}`)?.focus();
              }}
              className="text-sm px-3 py-2 rounded-t-lg"
              style={{
                color: tab === t ? "var(--pr-text-primary)" : "var(--pr-text-muted)",
                borderBottom: tab === t ? "2px solid var(--pr-authority-blue)" : "2px solid transparent",
              }}
            >
              {t}
            </button>
          ))}
        </div>

        {error && (
          <p role="alert" className="text-xs mb-4" style={{ color: "var(--pr-critical-red)" }}>
            {error} <button type="button" onClick={load} style={{ color: "var(--pr-authority-blue)", textDecoration: "underline" }}>Retry</button>
          </p>
        )}

        {!settings && !error ? (
          <p className="text-sm" style={{ color: "var(--pr-text-muted)" }}>Loading...</p>
        ) : settings ? (
          <div role="tabpanel" id={`org-tabpanel-${tab}`} aria-labelledby={`org-tab-${tab}`}>
            {tab === "General" && <GeneralTab settings={settings} onSaved={setSettings} />}
            {tab === "Organisation Structure" && <OrganisationStructureTab settings={settings} />}
            {tab === "Security" && <SecurityTab settings={settings} onSaved={setSettings} />}
            {tab === "Decision Defaults" && <RuntimeAuthorityTab settings={settings} onSaved={setSettings} />}
            {tab === "Integrations" && <IntegrationsTab />}
            {tab === "Enterprise Systems" && <EnterpriseSystemsTab />}
            {tab === "Notifications" && <NotificationsTab settings={settings} onSaved={setSettings} />}
            {tab === "Audit" && <AuditTab settings={settings} onSaved={setSettings} />}
            {tab === "Organisation Health" && <OrganisationHealthTab />}
            {tab === "About" && <AboutTab />}
          </div>
        ) : null}
      </div>
    </RequirePermission>
  );
}
