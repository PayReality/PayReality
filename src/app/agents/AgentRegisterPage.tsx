import { useEffect, useId, useState } from "react";
import { Link, useNavigate } from "react-router";
import { Plus, Info } from "lucide-react";
import { agentsApi } from "./api";
import { useAuth } from "../auth/AuthContext";
import { generateKeyPair } from "../live/crypto";
import { saveAgentKeyPair } from "../live/agentKeyStore";
import { describeApiError } from "../live/format";
import type { LivePrincipal } from "../live/types";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { PageHeader } from "../components/ui/page-header";

// Core Product Experience Redesign, section 3A: Agent Registry --
// the registration/machine-identity workflow, split out of the Agents
// inventory page (AgentDirectoryPage.tsx) it used to sit at the top of,
// unconditionally, ahead of the inventory itself. This is exactly what
// registration actually does today: creates an Agent row in "registered"
// status (not yet operational) and stores a locally-generated Ed25519
// keypair in this browser -- no certificate issuance ceremony, no
// server-side key generation, no authority assignment happens here.
// Activation, and any authority a policy grants this agent's principal,
// are separate, later steps -- this page doesn't imply otherwise.
export function AgentRegisterPage() {
  const formId = useId();
  const navigate = useNavigate();
  const { user, hasPermission } = useAuth();
  const canActivate = !user || hasPermission("agent.activate");
  const [principals, setPrincipals] = useState<LivePrincipal[]>([]);
  const [name, setName] = useState("");
  const [principalId, setPrincipalId] = useState("");
  const [newPrincipalName, setNewPrincipalName] = useState("");
  const [creatingPrincipal, setCreatingPrincipal] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [registeredName, setRegisteredName] = useState<string | null>(null);
  const [registeredId, setRegisteredId] = useState<string | null>(null);

  useEffect(() => {
    agentsApi
      .listPrincipals()
      .then(setPrincipals)
      .catch((e) => setMessage(describeApiError(e, "Loading principals")));
  }, []);

  async function handleCreatePrincipal() {
    if (!newPrincipalName.trim()) return;
    setCreatingPrincipal(true);
    try {
      const principal = await agentsApi.createPrincipal(newPrincipalName);
      setPrincipals((prev) => [...prev, principal]);
      setPrincipalId(principal.id);
      setNewPrincipalName("");
    } catch (e) {
      setMessage(describeApiError(e, "Create principal"));
    } finally {
      setCreatingPrincipal(false);
    }
  }

  async function handleRegister() {
    if (!name.trim() || !principalId) {
      setMessage("Agent identity and acting principal are both required.");
      return;
    }
    setRegistering(true);
    setMessage(null);
    try {
      const { publicKeyB64, privateKeyB64 } = generateKeyPair();
      const agent = await agentsApi.register({
        name,
        acting_for_principal_id: principalId,
        public_key: `ed25519:base64:${publicKeyB64}`,
      });
      saveAgentKeyPair(agent.id, privateKeyB64, publicKeyB64);
      setRegisteredName(agent.name);
      setRegisteredId(agent.id);
    } catch (e) {
      setMessage(describeApiError(e, "Registration"));
    } finally {
      setRegistering(false);
    }
  }

  if (registeredName && registeredId) {
    return (
      <div className="p-8 max-w-xl mx-auto" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
        <Card padding={24}>
          <p className="text-sm font-semibold mb-2" style={{ color: "var(--pr-trust-green)" }}>Agent registered</p>
          <p className="text-sm mb-4" style={{ color: "var(--pr-text-secondary)" }}>
            "{registeredName}" now exists in "Registered" status -- not yet operational. It needs to be
            activated before it can sign requests and be checked against your rules
            {canActivate ? "." : ", which requires the agent.activate permission your signed-in role doesn't carry."}
          </p>
          <div className="flex gap-2">
            <Button onClick={() => navigate(`/agents/${registeredId}`)}>
              {canActivate ? "Go to agent & activate" : "Go to agent"}
            </Button>
            <Button variant="ghost" onClick={() => { setRegisteredName(null); setRegisteredId(null); setName(""); }}>
              Register another
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-xl mx-auto" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <Link to="/agents" style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>&lt; Back to Agents</Link>
      <PageHeader
        title="Register an agent"
        description="Gives an AI agent an identity, a signing keypair generated in this browser, and the principal whose delegated authority it will act under. It won't be operational until you activate it."
      />

      <div
        className="flex items-start gap-2 p-3 rounded-lg mb-6"
        style={{ backgroundColor: "var(--pr-overlay-05)" }}
      >
        <Info className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: "var(--pr-text-muted)" }} />
        <p className="text-sm" style={{ color: "var(--pr-text-secondary)" }}>
          This creates an identity, not authority. What this agent is actually allowed to do is
          decided separately, in Governance, once it's active.
        </p>
      </div>

      <Card padding={24}>
        <div className="grid grid-cols-1 gap-4 mb-4">
          <div>
            <label htmlFor={`${formId}-name`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
              Agent name
            </label>
            <input
              id={`${formId}-name`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="AP-Automation-Agent"
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
            />
          </div>
          <div>
            <label htmlFor={`${formId}-principal`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
              Acting for principal <span style={{ fontWeight: 400, color: "var(--pr-text-disabled)" }}>(whose delegated authority it acts under)</span>
            </label>
            <select
              id={`${formId}-principal`}
              value={principalId}
              onChange={(e) => setPrincipalId(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
            >
              <option value="">Select a principal...</option>
              {principals.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex items-end gap-2 mb-4">
          <div className="flex-1">
            <label htmlFor={`${formId}-new-principal`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
              Or create a new principal
            </label>
            <input
              id={`${formId}-new-principal`}
              value={newPrincipalName}
              onChange={(e) => setNewPrincipalName(e.target.value)}
              placeholder="Regional Controller (EMEA)"
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
            />
          </div>
          <button
            onClick={handleCreatePrincipal}
            disabled={creatingPrincipal || !newPrincipalName.trim()}
            className="px-4 py-2 rounded-lg text-sm border disabled:opacity-40"
            style={{ borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-secondary)" }}
          >
            {creatingPrincipal ? "Creating..." : "Create"}
          </button>
        </div>

        <button
          onClick={handleRegister}
          disabled={registering}
          className="px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2 disabled:opacity-40"
          style={{ backgroundColor: "var(--pr-authority-blue)", color: "#fff" }}
        >
          <Plus className="w-4 h-4" /> {registering ? "Registering..." : "Register agent"}
        </button>

        {message && <Alert severity="neutral" className="text-sm mt-4">{message}</Alert>}
      </Card>
    </div>
  );
}
