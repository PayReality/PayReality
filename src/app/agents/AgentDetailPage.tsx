import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { agentsApi } from "./api";
import { AgentStatusBadge } from "./components/AgentStatusBadge";
import { HealthDot } from "./components/HealthDot";
import { LifecycleTimeline } from "./components/LifecycleTimeline";
import { describeApiError, formatStatus } from "../live/format";
import { generateKeyPair } from "../live/crypto";
import { saveAgentKeyPair } from "../live/agentKeyStore";
import { HelpIcon } from "../help/HelpIcon";
import { useAuth } from "../auth/AuthContext";
import { useResourceSync } from "../services/resourceSync";
import type { AgentDetail } from "./types";
import type { PrincipalAuthorityContext } from "../live/types";
import { Card } from "../components/ui/card";
import { FieldLabel } from "../components/ui/label";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { ConfirmButton } from "../components/ui/confirm-button";
import { DEMO_MODE } from "../demo/config";
import { useNow, formatRelativeTime } from "../demo/liveClock";

const valueStyle: React.CSSProperties = { fontSize: 13, color: "var(--pr-text-primary)" };

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <FieldLabel size={11}>{label}</FieldLabel>
      <div style={valueStyle}>{value || "-"}</div>
    </div>
  );
}

export function AgentDetailPage() {
  const { agentId } = useParams();
  const now = useNow();
  const { user, hasPermission } = useAuth();
  const [detail, setDetail] = useState<AgentDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [verifyResults, setVerifyResults] = useState<Record<string, boolean>>({});
  const [newOwner, setNewOwner] = useState("");
  const [newBusinessUnit, setNewBusinessUnit] = useState("");
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  // Authority-as-a-continuous-object, Stage I.9: the Principal's real
  // organisational placement and active delegations, resolved via the
  // same authority-context lookup every Intent already uses. null until
  // loaded, and stays null (rather than throwing) if the principal has
  // nothing resolved yet.
  const [authorityContext, setAuthorityContext] = useState<PrincipalAuthorityContext | null>(null);

  function load() {
    if (!agentId) return;
    setLoadError(null);
    agentsApi
      .getDetail(agentId)
      .then(setDetail)
      .catch((e) => setLoadError(describeApiError(e, "Loading agent")));
  }

  useEffect(load, [agentId]);
  // Milestone 14: this page was the disclosed Phase 6A gap -- certificate
  // rotation/revocation or a lifecycle change made from another tab (or
  // the Agent Directory) never reached this page while it stayed mounted.
  useResourceSync(["agents", "certificates"], load);

  useEffect(() => {
    if (!detail) return;
    agentsApi
      .getPrincipalAuthorityContext(detail.agent.acting_for_principal_id)
      .then(setAuthorityContext)
      .catch(() => setAuthorityContext(null));
  }, [detail?.agent.acting_for_principal_id]);

  // Only disable when we positively know the signed-in user lacks the
  // permission -- with no session (Operator Key bypass still active),
  // stay permissive rather than guessing (same rule ReviewQueuePage uses).
  function lacksPermission(permission: string): boolean {
    return !!user && !hasPermission(permission);
  }

  async function runAction(fn: () => Promise<unknown>, label: string): Promise<boolean> {
    setMessage(null);
    setPendingAction(label);
    try {
      await fn();
      load();
      return true;
    } catch (e) {
      setMessage(describeApiError(e, label));
      return false;
    } finally {
      setPendingAction(null);
    }
  }

  async function handleRotate() {
    if (!agentId) return;
    const { publicKeyB64, privateKeyB64 } = generateKeyPair();
    const succeeded = await runAction(() => agentsApi.rotate(agentId, `ed25519:base64:${publicKeyB64}`), "Rotate certificate");
    // Only persist the new private key locally if the server actually
    // accepted the rotation -- runAction used to swallow the failure and
    // this ran unconditionally, silently desyncing the stored key from
    // the agent's real active certificate.
    if (succeeded) saveAgentKeyPair(agentId, privateKeyB64, publicKeyB64);
  }

  async function handleVerify(eventId: string) {
    if (!agentId) return;
    try {
      const result = await agentsApi.verifyAuditEvent(agentId, eventId);
      setVerifyResults((prev) => ({ ...prev, [eventId]: result.valid }));
    } catch (e) {
      setMessage(describeApiError(e, "Verify audit event"));
    }
  }

  if (!detail && loadError) {
    return (
      <div className="p-8">
        <Alert severity="error" className="text-sm">
          <div className="flex items-center gap-3">
            <span>{loadError}</span>
            <Button variant="ghost" size="sm" onClick={load}>Retry</Button>
          </div>
        </Alert>
      </div>
    );
  }
  if (!detail) return <div className="p-8" style={{ color: "var(--pr-text-muted)" }}>Loading...</div>;

  const { agent } = detail;
  const activeCert = detail.certificates.find((c) => c.status === "active");

  return (
    <div className="p-8 max-w-4xl" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <Link to="/agents" style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>&lt; Back to Agents</Link>

      <div className="flex items-center justify-between gap-3 mt-2 mb-1">
        <h1 style={{ color: "var(--pr-text-primary)" }}>{agent.name}</h1>
        <AgentStatusBadge status={agent.status} />
      </div>
      <div className="flex items-center gap-3 mb-6">
        <HealthDot health={agent.health} />
        <span style={{ fontSize: 12, color: "var(--pr-text-disabled)", fontFamily: "monospace" }}>{agent.id}</span>
      </div>

      {message && <Alert severity="error" className="text-sm mb-4">{message}</Alert>}

      <div className="flex flex-wrap gap-2 mb-6">
        {(agent.status === "registered" || agent.status === "suspended") && (
          <Button
            variant="tint-success"
            size="sm"
            disabled={!!pendingAction || lacksPermission("agent.activate")}
            onClick={() => runAction(() => agentsApi.activate(agentId!), "Activate")}
          >
            {pendingAction === "Activate" ? "Activating..." : "Activate"}
          </Button>
        )}
        {agent.status === "active" && (
          <ConfirmButton
            size="sm"
            confirmLabel="Confirm suspend"
            disabled={!!pendingAction || lacksPermission("agent.suspend")}
            className="disabled:opacity-40"
            style={{ backgroundColor: "rgba(245,158,11,0.1)", color: "var(--pr-warning-amber)" }}
            onConfirm={() => runAction(() => agentsApi.suspend(agentId!), "Suspend")}
          >
            Suspend
          </ConfirmButton>
        )}
        {(agent.status === "active" || agent.status === "suspended") && (
          <ConfirmButton
            size="sm"
            confirmLabel="Confirm rotate"
            disabled={!!pendingAction || lacksPermission("agent.rotate")}
            className="disabled:opacity-40"
            style={{ backgroundColor: "rgba(77,124,254,0.1)", color: "var(--pr-authority-blue)" }}
            onConfirm={handleRotate}
          >
            Rotate certificate
          </ConfirmButton>
        )}
        {(agent.status === "registered" || agent.status === "active" || agent.status === "suspended") && (
          <>
            <ConfirmButton
              size="sm"
              confirmLabel="Confirm retire"
              disabled={!!pendingAction || lacksPermission("agent.retire")}
              className="disabled:opacity-40"
              style={{ backgroundColor: "var(--pr-overlay-06)", color: "var(--pr-text-secondary)" }}
              onConfirm={() => runAction(() => agentsApi.retire(agentId!), "Retire")}
            >
              Retire
            </ConfirmButton>
            <ConfirmButton
              variant="tint-danger"
              size="sm"
              confirmLabel="Confirm revoke"
              disabled={!!pendingAction || lacksPermission("agent.revoke")}
              onConfirm={() => runAction(() => agentsApi.revoke(agentId!), "Revoke")}
            >
              Revoke
            </ConfirmButton>
          </>
        )}
      </div>

      {/* Core Product Experience Redesign, section 3C: this page is an
          operational authority profile, organized around the five
          questions an operator actually asks about an agent -- who it
          is, whose authority it acts under, what it's authorized to do,
          what it's actually done, and its current lifecycle state --
          rather than an undifferentiated stack of cards. */}
      <p className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: "var(--pr-text-disabled)" }}>
        Who is this
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card style={{ marginBottom: 16 }}>
          <h2 className="text-sm font-medium mb-1" style={{ color: "var(--pr-text-primary)" }}>Identity</h2>
          <p className="mb-3" style={{ fontSize: 12, color: "var(--pr-text-muted)" }}>
            Acting under {detail.principal_name ? <strong style={{ color: "var(--pr-text-secondary)" }}>{detail.principal_name}</strong> : "its principal"}'s delegated authority, the same way a human employee's actions are governed by the role they hold, not by the employee personally.
          </p>
          {authorityContext && (() => {
            const segments = [
              authorityContext.role,
              authorityContext.team,
              authorityContext.department,
              authorityContext.business_unit,
              authorityContext.organization,
            ].filter((s): s is string => !!s);
            return segments.length > 0 ? (
              <p className="mb-3" style={{ fontSize: 13, color: "var(--pr-text-primary)" }}>
                {segments.join(" · ")}
              </p>
            ) : null;
          })()}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Principal" value={detail.principal_name} />
            <Field label="Owner" value={agent.owner} />
            <Field label="Business unit" value={agent.business_unit} />
            <Field label="Environment" value={agent.environment} />
            <Field label="Description" value={agent.description} />
            <Field label="Purpose" value={agent.purpose} />
            <Field label="Model" value={agent.model} />
            <Field label="Version" value={agent.version} />
            <Field label="Runtime" value={agent.runtime} />
            <Field label="Platform" value={agent.platform} />
          </div>
          {agent.tags.length > 0 && (
            <div className="mt-3">
              <FieldLabel size={11}>Tags</FieldLabel>
              <div className="flex flex-wrap gap-1.5 mt-1">
                {agent.tags.map((t) => (
                  <span key={t} style={{ fontSize: 11, padding: "2px 8px", borderRadius: 999, backgroundColor: "var(--pr-overlay-06)", color: "var(--pr-text-secondary)" }}>{t}</span>
                ))}
              </div>
            </div>
          )}
        </Card>

        <Card style={{ marginBottom: 16 }}>
          <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>SDK &amp; heartbeat</h2>
          <div className="grid grid-cols-2 gap-3 mb-4">
            <Field label="SDK version" value={agent.sdk_version} />
            <Field
              label="Last seen"
              value={
                agent.last_seen_at
                  ? DEMO_MODE
                    ? formatRelativeTime(agent.last_seen_at, now)
                    : new Date(agent.last_seen_at).toLocaleString()
                  : null
              }
            />
          </div>
          <p style={{ fontSize: 12, color: "var(--pr-text-muted)" }}>
            Reported by <code style={{ fontFamily: "monospace" }}>agent.heartbeat()</code> in the Python SDK
            (SDK_AGENT_GUIDE.md). No manual update here: this section reflects whatever the agent itself
            last reported.
          </p>

          <h3 className="text-xs font-medium mt-4 mb-2" style={{ color: "var(--pr-text-primary)" }}>Transfer ownership</h3>
          <div className="flex flex-wrap gap-2">
            <input
              value={newOwner}
              onChange={(e) => setNewOwner(e.target.value)}
              placeholder="New owner"
              aria-label="New owner"
              className="px-2 py-1.5 rounded-lg border text-xs flex-1 min-w-0"
              style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
            />
            <input
              value={newBusinessUnit}
              onChange={(e) => setNewBusinessUnit(e.target.value)}
              placeholder="New business unit (optional)"
              aria-label="New business unit"
              className="px-2 py-1.5 rounded-lg border text-xs flex-1 min-w-0"
              style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
            />
            <button
              onClick={async () => {
                const succeeded = await runAction(
                  () => agentsApi.transfer(agentId!, newOwner, newBusinessUnit || undefined),
                  "Transfer"
                );
                if (succeeded) {
                  setNewOwner("");
                  setNewBusinessUnit("");
                }
              }}
              disabled={!newOwner.trim() || !!pendingAction || lacksPermission("agent.manage")}
              className="px-3 py-1.5 rounded-lg text-xs disabled:opacity-40 flex-shrink-0"
              style={{ backgroundColor: "rgba(77,124,254,0.1)", color: "var(--pr-authority-blue)" }}
            >
              {pendingAction === "Transfer" ? "Transferring..." : "Transfer"}
            </button>
          </div>
        </Card>
      </div>

      <p className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: "var(--pr-text-disabled)" }}>
        Whose authority
      </p>
      <Card style={{ marginBottom: 16 }}>
        <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>Active delegations</h2>
        {authorityContext && authorityContext.delegations.length > 0 ? (
          authorityContext.delegations.map((d) => (
            <div key={d.id} className="py-1.5" style={{ borderTop: "1px solid var(--pr-overlay-05)", fontSize: 13 }}>
              <span style={{ color: "var(--pr-text-primary)" }}>{d.operation ?? "Delegation"}</span>
              {d.from_principal_id && (
                <span style={{ color: "var(--pr-text-muted)", fontSize: 12 }}> &middot; from principal {d.from_principal_id}</span>
              )}
            </div>
          ))
        ) : (
          <p style={{ fontSize: 13, color: "var(--pr-text-muted)" }}>
            No active delegations resolved for this principal.
          </p>
        )}
      </Card>

      <p className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: "var(--pr-text-disabled)" }}>
        What can it do
      </p>
      <Card style={{ marginBottom: 16 }}>
        <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>Rules</h2>
        {detail.policies.length === 0 && <p style={{ fontSize: 13, color: "var(--pr-text-muted)" }}>No rules target this agent's principal yet.</p>}
        {detail.policies.map((p) => (
          <div key={p.policy_key} className="py-1.5" style={{ borderTop: "1px solid var(--pr-overlay-05)", fontSize: 13 }}>
            <div className="flex items-center justify-between">
              <Link to={`/governance/${p.policy_key}`} style={{ color: "var(--pr-authority-blue)" }}>{p.name || p.policy_key}</Link>
              <span style={{ color: "var(--pr-text-muted)" }}>v{p.version} &middot; {formatStatus(p.status)}</span>
            </div>
            {/* Product Experience Remediation Milestone 1: what this rule
                actually governs -- previously invisible without opening
                Governance separately. */}
            {(p.action || p.resource) && (
              <div style={{ color: "var(--pr-text-disabled)", fontSize: 11.5 }}>
                {p.action ?? "any action"}
                {p.resource ? ` → ${p.resource}` : ""}
              </div>
            )}
          </div>
        ))}
      </Card>

      <p className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: "var(--pr-text-disabled)" }}>
        What has it done
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card style={{ marginBottom: 16 }}>
          <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>Decision history</h2>
          {detail.recent_decisions.length === 0 && <p style={{ fontSize: 13, color: "var(--pr-text-muted)" }}>No decisions yet.</p>}
          {detail.recent_decisions.map((d) => (
            <div key={d.id} className="py-1.5" style={{ borderTop: "1px solid var(--pr-overlay-05)", fontSize: 13 }}>
              <div className="flex items-center justify-between">
                <span style={{ color: "var(--pr-text-primary)" }}>{formatStatus(d.outcome)}</span>
                <span style={{ fontSize: 11, color: "var(--pr-text-disabled)" }}>{new Date(d.created_at).toLocaleString()}</span>
              </div>
              {/* Product Experience Remediation Milestone 1: what was
                  actually attempted -- previously only outcome/reason,
                  with no action or resource at all. Deliberately no
                  amount/currency: contextual, not universal. */}
              {(d.action || d.resource) && (
                <div style={{ color: "var(--pr-text-disabled)", fontSize: 11.5 }}>
                  {d.action ?? "unknown action"}
                  {d.resource ? ` → ${d.resource}` : ""}
                </div>
              )}
              {d.reason && <div style={{ color: "var(--pr-text-muted)", fontSize: 12 }}>{d.reason}</div>}
            </div>
          ))}
          <Link to="/decisions" style={{ color: "var(--pr-authority-blue)", fontSize: 12, display: "inline-block", marginTop: 8 }}>View all Decisions &rarr;</Link>
        </Card>

        <Card style={{ marginBottom: 16 }}>
          <div className="flex items-center gap-1.5 mb-3">
            <h2 className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>Evidence</h2>
            <HelpIcon articleId="evidence" />
          </div>
          {detail.recent_evidence.length === 0 && <p style={{ fontSize: 13, color: "var(--pr-text-muted)" }}>No evidence yet.</p>}
          {detail.recent_evidence.map((e) => (
            <div key={e.id} className="flex items-center justify-between py-1.5" style={{ borderTop: "1px solid var(--pr-overlay-05)", fontSize: 13 }}>
              <span style={{ color: "var(--pr-text-primary)" }}>{formatStatus(e.status)}</span>
              <span style={{ fontSize: 11, color: "var(--pr-text-disabled)" }}>{new Date(e.created_at).toLocaleString()}</span>
            </div>
          ))}
          <Link to="/evidence" style={{ color: "var(--pr-authority-blue)", fontSize: 12, display: "inline-block", marginTop: 8 }}>View all Evidence &rarr;</Link>
        </Card>
      </div>

      <p className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: "var(--pr-text-disabled)" }}>
        Lifecycle state
      </p>
      <Card style={{ marginBottom: 16 }}>
        <div className="flex items-center gap-1.5 mb-3">
          <h2 className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>Certificates</h2>
          <HelpIcon articleId="agent_certificate" />
        </div>
        <table className="w-full text-xs" style={{ color: "var(--pr-text-primary)" }}>
          <thead>
            <tr style={{ color: "var(--pr-text-muted)", textAlign: "left" }}>
              <th className="pb-2">Status</th>
              <th className="pb-2">Issued</th>
              <th className="pb-2">Activated</th>
              <th className="pb-2">Rotated</th>
              <th className="pb-2">Expires/Revoked</th>
            </tr>
          </thead>
          <tbody>
            {detail.certificates.map((c) => (
              <tr key={c.id} style={{ borderTop: "1px solid var(--pr-overlay-05)" }}>
                <td className="py-2">{formatStatus(c.status)}{c.id === activeCert?.id ? " (current)" : ""}</td>
                <td className="py-2" style={{ color: "var(--pr-text-muted)" }}>{new Date(c.issued_at).toLocaleDateString()}</td>
                <td className="py-2" style={{ color: "var(--pr-text-muted)" }}>{c.activated_at ? new Date(c.activated_at).toLocaleDateString() : "-"}</td>
                <td className="py-2" style={{ color: "var(--pr-text-muted)" }}>{c.rotated_at ? new Date(c.rotated_at).toLocaleDateString() : "-"}</td>
                <td className="py-2" style={{ color: "var(--pr-text-muted)" }}>
                  {(c.expires_at || c.revoked_at) ? new Date((c.expires_at ?? c.revoked_at)!).toLocaleDateString() : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card style={{ marginBottom: 16 }}>
        <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>Lifecycle timeline &amp; audit</h2>
        <LifecycleTimeline events={detail.recent_audit_events} />
        {detail.recent_audit_events.length > 0 && (
          <div className="mt-4">
            <h3 className="text-xs font-medium mb-2" style={{ color: "var(--pr-text-muted)" }}>Verify a signed event</h3>
            {detail.recent_audit_events.slice(0, 5).map((event) => (
              <div key={event.id} className="flex items-center gap-2 py-1" style={{ fontSize: 12 }}>
                <span style={{ color: "var(--pr-text-muted)", fontFamily: "monospace" }}>{event.event_type}</span>
                <button
                  onClick={() => handleVerify(event.id)}
                  className="px-2 py-0.5 rounded"
                  style={{ backgroundColor: "var(--pr-overlay-06)", color: "var(--pr-text-secondary)" }}
                >
                  Verify
                </button>
                {verifyResults[event.id] !== undefined && (
                  <span style={{ color: verifyResults[event.id] ? "var(--pr-trust-green)" : "var(--pr-critical-red)" }}>
                    {verifyResults[event.id] ? "Valid signature" : "INVALID"}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
