import { useState } from "react";
import { KeyRound } from "lucide-react";
import { getOperatorKey, setOperatorKey } from "../operatorKey";
import { getOrganizationId, setOrganizationId } from "../organizationId";
import { useAuth } from "../../auth/AuthContext";

// The backend requires this key for policy review/compile/activate and
// decision-resolution calls (app/security.py::verify_operator_key). Real
// per-user login and RBAC now exist (RBAC.md, Phase 10), but this shared
// operator key remains a separate, full-bypass credential for those same
// actions -- not a placeholder, and not yet superseded.
//
// Milestone 3 (Enterprise Surface Isolation): the Operator Key became
// platform-admin-only in Milestone 2 -- it no longer belongs to any one
// organization, so every request it makes must now also name a target
// organization explicitly. That id has no discovery UI of its own yet
// (see MILESTONE_3_ENTERPRISE_SURFACE_ISOLATION_SUMMARY.md's Remaining
// Risks); GET /v1/organizations (Operator-Key-gated) is the way to find
// one today.
// The single most confusing failure mode this field can put someone in:
// require_permission checks the Operator Key first, unconditionally, and
// it wins over a real, valid session if both are present at once, by
// design (see app/security.py). A signed-in person who also has a key
// saved here (from testing, or from following a docs example) has every
// request silently routed as "the operator," not as themselves, with no
// visible sign why things stopped working. This surfaced for real: a
// logged-in user's every page failed with a generic "couldn't reach the
// backend" message, and the actual cause (an Operator Key present with no
// Organization Id) took a live network-tab inspection to find. The two
// warnings below exist so the next person sees the cause immediately,
// in this field, instead of guessing from unrelated error toasts.
export function OperatorKeyField() {
  const { user } = useAuth();
  const [value, setValue] = useState(getOperatorKey());
  const [saved, setSaved] = useState(false);
  const [orgValue, setOrgValue] = useState(getOrganizationId());
  const [orgSaved, setOrgSaved] = useState(false);

  const keySet = value.trim().length > 0;
  const missingOrgId = keySet && orgValue.trim().length === 0;
  const overridesSession = keySet && user !== null;

  function handleClear() {
    setValue("");
    setOperatorKey("");
    setSaved(false);
  }

  return (
    <div
      className="px-3 py-2.5 rounded-xl mt-2"
      style={{ backgroundColor: "var(--pr-overlay-03)", border: "1px solid var(--pr-overlay-04)" }}
    >
      <div className="flex items-center justify-between gap-1.5 mb-1.5">
        <div className="flex items-center gap-1.5">
          <KeyRound className="w-3 h-3" style={{ color: "var(--pr-text-disabled)" }} />
          <span className="text-[11px] font-medium" style={{ color: "var(--pr-text-secondary)" }}>
            Operator Key
          </span>
        </div>
        {keySet && (
          <button
            type="button"
            onClick={handleClear}
            className="text-[10px] underline"
            style={{ color: "var(--pr-text-muted)" }}
          >
            Clear
          </button>
        )}
      </div>
      <div className="flex items-center gap-1.5">
        <input
          type="password"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setSaved(false);
          }}
          onBlur={() => {
            setOperatorKey(value);
            setSaved(true);
          }}
          placeholder="Required to approve/activate"
          className="w-full text-[11px] px-2 py-1 rounded-md"
          style={{
            backgroundColor: "var(--pr-input-bg)",
            color: "var(--pr-text-primary)",
            border: "1px solid var(--pr-overlay-06)",
          }}
        />
      </div>
      {saved && !overridesSession && (
        <p className="text-[10px] mt-1" style={{ color: "var(--pr-trust-green)" }}>
          Saved to this browser
        </p>
      )}
      {overridesSession && (
        <p className="text-[10px] mt-1" style={{ color: "var(--pr-warning-amber)" }}>
          You're signed in, but this key overrides your session on every request, not just
          policy actions. Click Clear above to act as yourself instead.
        </p>
      )}
      <div className="flex items-center gap-1.5 mt-2">
        <input
          type="text"
          value={orgValue}
          onChange={(e) => {
            setOrgValue(e.target.value);
            setOrgSaved(false);
          }}
          onBlur={() => {
            setOrganizationId(orgValue);
            setOrgSaved(true);
          }}
          placeholder="Organization ID (required with the key above)"
          className="w-full text-[11px] px-2 py-1 rounded-md"
          style={{
            backgroundColor: "var(--pr-input-bg)",
            color: "var(--pr-text-primary)",
            border: "1px solid var(--pr-overlay-06)",
          }}
        />
      </div>
      {orgSaved && !missingOrgId && (
        <p className="text-[10px] mt-1" style={{ color: "var(--pr-trust-green)" }}>
          Saved to this browser
        </p>
      )}
      {missingOrgId && (
        <p className="text-[10px] mt-1" style={{ color: "var(--pr-critical-red)" }}>
          An Operator Key is set with no Organization Id. Every request will fail (400) until
          one is entered here.
        </p>
      )}
    </div>
  );
}
