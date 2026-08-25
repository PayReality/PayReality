import { useEffect, useId, useState } from "react";
import { policyStudioApi } from "../api";
import type { LiveAgent, LivePrincipal } from "../../live/types";
import type { Scope } from "../types";
import { FieldLabel } from "../../components/ui/label";

const inputStyle: React.CSSProperties = {
  backgroundColor: "var(--pr-bg-hover)",
  border: "1px solid var(--pr-overlay-10)",
  color: "var(--pr-text-primary)",
  borderRadius: 6,
  padding: "6px 8px",
  fontSize: 13,
  width: "100%",
};

// Action is a dropdown fetched from the live vocabulary endpoint, never
// a second hardcoded copy of KNOWN_SCOPES in this file: the exact drift
// bug DOMAIN_REFACTOR_PLAN.md's item 5 already named for the existing
// Runtime Decisions page.
export function ScopeFields({ scope, onChange }: { scope: Scope; onChange: (next: Scope) => void }) {
  const [actions, setActions] = useState<string[]>([]);
  const [principals, setPrincipals] = useState<LivePrincipal[]>([]);
  const [agents, setAgents] = useState<LiveAgent[]>([]);
  const formId = useId();

  useEffect(() => {
    policyStudioApi
      .getVocabulary()
      .then((v) => setActions(v.actions))
      .catch(() => setActions([]));
    policyStudioApi
      .listPrincipals()
      .then(setPrincipals)
      .catch(() => setPrincipals([]));
    policyStudioApi
      .listAgents()
      .then(setAgents)
      .catch(() => setAgents([]));
  }, []);

  return (
    <div className="grid grid-cols-2 gap-4">
      <div>
        <FieldLabel htmlFor={`${formId}-principal`}>Who this applies to</FieldLabel>
        <select
          id={`${formId}-principal`}
          style={inputStyle}
          value={scope.principal}
          onChange={(e) => onChange({ ...scope, principal: e.target.value })}
        >
          <option value="">Select a principal...</option>
          {principals.map((p) => (
            <option key={p.id} value={p.name}>{p.name}</option>
          ))}
          {scope.principal && !principals.some((p) => p.name === scope.principal) && (
            <option value={scope.principal}>{scope.principal} (not in the current list)</option>
          )}
        </select>
      </div>
      <div>
        <FieldLabel htmlFor={`${formId}-action`}>Action</FieldLabel>
        <select
          id={`${formId}-action`}
          style={inputStyle}
          value={scope.action}
          onChange={(e) => onChange({ ...scope, action: e.target.value })}
        >
          <option value="">Select an action</option>
          {actions.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
      </div>
      <div>
        <FieldLabel htmlFor={`${formId}-agent`}>Agent (optional)</FieldLabel>
        <select
          id={`${formId}-agent`}
          style={inputStyle}
          value={scope.agent ?? ""}
          onChange={(e) => onChange({ ...scope, agent: e.target.value || null })}
        >
          <option value="">Any agent for this principal</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
          {scope.agent && !agents.some((a) => a.id === scope.agent) && (
            <option value={scope.agent}>{scope.agent} (not in the current list)</option>
          )}
        </select>
      </div>
      <div>
        <FieldLabel htmlFor={`${formId}-resource`}>Resource (optional)</FieldLabel>
        <input
          id={`${formId}-resource`}
          style={inputStyle}
          value={scope.resource ?? ""}
          onChange={(e) => onChange({ ...scope, resource: e.target.value || null })}
        />
      </div>
    </div>
  );
}
