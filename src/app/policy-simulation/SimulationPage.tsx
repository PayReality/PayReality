import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { policySimulationApi } from "./api";
import { policyStudioApi } from "../policy-studio/api";
import type { RuntimePolicy } from "../policy-studio/types";
import type { BatchSimulationResult, Scenario, SimulationInput, SimulationResult } from "./types";
import { Card } from "../components/ui/card";
import { FieldLabel } from "../components/ui/label";
import { Input, getInputStyle } from "../components/ui/input";
import { Button } from "../components/ui/button";
import { Alert } from "../components/ui/alert";
import { describeApiError } from "../live/format";

// Runtime Policy Simulator (Authority Intelligence Program, Phase 4,
// POLICY_SIMULATOR.md): a dry run of Runtime Authority. Everything on
// this page is read-only with respect to Runtime Authority itself --
// there is no button anywhere here that edits, compiles, or deploys a
// policy; that stays Policy Studio's own PublishPage.

const DECISION_STYLE: Record<string, { label: string; color: string; bg: string }> = {
  ALLOW: { label: "Approved", color: "var(--pr-trust-green)", bg: "rgba(34,197,94,0.1)" },
  DENY: { label: "Denied", color: "var(--pr-critical-red)", bg: "rgba(239,68,68,0.1)" },
  HUMAN_REVIEW: { label: "Escalate", color: "var(--pr-warning-amber)", bg: "rgba(245,158,11,0.1)" },
};

function DecisionBadge({ decision }: { decision: string }) {
  const s = DECISION_STYLE[decision] ?? { label: decision, color: "var(--pr-text-primary)", bg: "var(--pr-overlay-05)" };
  return (
    <span
      style={{
        display: "inline-block", fontSize: 20, fontWeight: 700, color: s.color,
        backgroundColor: s.bg, padding: "10px 22px", borderRadius: 10,
      }}
    >
      {s.label}
    </span>
  );
}

function SmallBadge({ ok, trueLabel, falseLabel }: { ok: boolean; trueLabel: string; falseLabel: string }) {
  return (
    <span
      style={{
        fontSize: 11, fontWeight: 600, textTransform: "uppercase", padding: "2px 8px", borderRadius: 99,
        color: ok ? "var(--pr-trust-green)" : "var(--pr-critical-red)",
        backgroundColor: ok ? "rgba(34,197,94,0.1)" : "rgba(239,68,68,0.1)",
      }}
    >
      {ok ? trueLabel : falseLabel}
    </span>
  );
}

const sectionTitle: React.CSSProperties = { fontSize: 13, fontWeight: 600, color: "var(--pr-text-primary)", marginBottom: 10 };

export function PolicySimulationPage() {
  const { policyKey } = useParams();
  const [policy, setPolicy] = useState<RuntimePolicy | null>(null);

  // Domain Generalization Milestone: resource/amount/currency were
  // already properly optional in buildInput() below -- only the
  // pre-filled defaults implied every simulation is financial. Emptied
  // so a security or HR policy isn't previewed against a fabricated
  // procurement scenario by default.
  const [principal, setPrincipal] = useState("");
  const [actingAsAgent, setActingAsAgent] = useState("");
  const [action, setAction] = useState("");
  const [resource, setResource] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("");
  const [contextText, setContextText] = useState("{}");

  const [result, setResult] = useState<SimulationResult | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const [scenarioName, setScenarioName] = useState("");
  const [expectedOutcome, setExpectedOutcome] = useState("ALLOW");
  const [scenarios, setScenarios] = useState<Scenario[] | null>(null);
  const [savingScenario, setSavingScenario] = useState(false);
  const [scenarioRuns, setScenarioRuns] = useState<Record<string, { passed: boolean; actual: string }>>({});

  const [batchResult, setBatchResult] = useState<BatchSimulationResult | null>(null);
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);

  useEffect(() => {
    if (!policyKey) return;
    policyStudioApi.get(policyKey).then((p) => {
      setPolicy(p);
      setPrincipal(p.scope.principal);
      setAction(p.scope.action);
      setResource(p.scope.resource ?? "");
    });
    policySimulationApi.listScenarios(policyKey).then(setScenarios);
  }, [policyKey]);

  function buildInput(): SimulationInput | null {
    let context: Record<string, unknown> = {};
    try {
      context = contextText.trim() ? JSON.parse(contextText) : {};
    } catch {
      setRunError("Additional context is not valid JSON.");
      return null;
    }
    return {
      principal, action, resource: resource || null,
      amount: amount.trim() === "" ? null : Number(amount),
      currency: currency || null, agent_name: actingAsAgent, context,
    };
  }

  async function runSimulation() {
    if (!policyKey) return;
    setRunError(null);
    const input = buildInput();
    if (!input) return;
    setRunning(true);
    setResult(null);
    try {
      const r = await policySimulationApi.simulate(policyKey, input);
      setResult(r);
    } catch (e) {
      setRunError(describeApiError(e, "Run simulation"));
    } finally {
      setRunning(false);
    }
  }

  async function saveScenario() {
    if (!policyKey || !scenarioName.trim()) return;
    const input = buildInput();
    if (!input) return;
    setSavingScenario(true);
    try {
      await policySimulationApi.createScenario(policyKey, { name: scenarioName.trim(), input, expected_outcome: expectedOutcome });
      setScenarioName("");
      policySimulationApi.listScenarios(policyKey).then(setScenarios);
    } catch (e) {
      setRunError(describeApiError(e, "Save scenario"));
    } finally {
      setSavingScenario(false);
    }
  }

  async function runSavedScenario(scenarioId: string) {
    try {
      const r = await policySimulationApi.runScenario(scenarioId);
      setScenarioRuns((prev) => ({ ...prev, [scenarioId]: { passed: r.passed, actual: r.actual_outcome } }));
    } catch (e) {
      setRunError(describeApiError(e, "Run scenario"));
    }
  }

  async function runBatch(file: File) {
    if (!policyKey) return;
    setBatchError(null);
    setBatchRunning(true);
    setBatchResult(null);
    try {
      const r = await policySimulationApi.batchSimulate(policyKey, file);
      setBatchResult(r);
    } catch (e) {
      setBatchError(describeApiError(e, "Batch simulation"));
    } finally {
      setBatchRunning(false);
    }
  }

  if (!policy) return <div className="p-8" style={{ color: "var(--pr-text-muted)" }}>Loading...</div>;

  return (
    <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <Link to={`/governance/${policyKey}`} style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>
        &lt; Back
      </Link>
      <div className="flex items-center gap-3 mt-2 mb-1">
        <h1 style={{ color: "var(--pr-text-primary)" }}>Simulation</h1>
        <span style={{ color: "var(--pr-text-muted)" }}>{policy.name} (v{policy.version})</span>
      </div>
      <p style={{ color: "var(--pr-text-muted)", fontSize: 12, marginBottom: 24, maxWidth: 720 }}>
        A dry run of Runtime Authority: this executes the exact same OPA evaluation production uses,
        isolated from it entirely. It never modifies this policy or any other, and nothing simulated
        here is ever persisted as a real Decision or Evidence record.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* LEFT: Simulation Inputs */}
        <div>
          <Card>
            <div style={sectionTitle}>Simulation Inputs</div>
            <FieldLabel>Principal (acting as)</FieldLabel>
            <Input value={principal} onChange={(e) => setPrincipal(e.target.value)} style={{ marginBottom: 12, width: "100%" }} />
            <FieldLabel>Acting agent (display only)</FieldLabel>
            <Input value={actingAsAgent} onChange={(e) => setActingAsAgent(e.target.value)} style={{ marginBottom: 12, width: "100%" }} />
            <FieldLabel>Action</FieldLabel>
            <Input value={action} onChange={(e) => setAction(e.target.value)} style={{ marginBottom: 12, width: "100%" }} />
            <FieldLabel>Resource (optional)</FieldLabel>
            <Input value={resource} onChange={(e) => setResource(e.target.value)} placeholder="e.g. invoice:INV-4821 or account:USR-829" style={{ marginBottom: 12, width: "100%" }} />
            <div className="grid grid-cols-2 gap-3">
              <div>
                <FieldLabel>Amount (optional)</FieldLabel>
                <Input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Only for a financial policy" style={{ width: "100%" }} />
              </div>
              <div>
                <FieldLabel>Currency (optional)</FieldLabel>
                <Input value={currency} onChange={(e) => setCurrency(e.target.value)} placeholder="e.g. USD" style={{ width: "100%" }} />
              </div>
            </div>
            <div style={{ marginTop: 12 }}>
              <FieldLabel>Additional context (Runtime Authority Context -- department, region, date, etc.)</FieldLabel>
              <textarea
                value={contextText}
                onChange={(e) => setContextText(e.target.value)}
                rows={6}
                style={{ ...getInputStyle("hover"), width: "100%", fontFamily: "monospace", fontSize: 12 }}
              />
            </div>
            {runError && <Alert severity="error" style={{ marginTop: 10 }}>{runError}</Alert>}
            <Button onClick={runSimulation} pending={running} style={{ marginTop: 14, width: "100%" }}>
              {running ? "Running simulation..." : "Run Simulation"}
            </Button>
          </Card>

          {/* Test Scenarios */}
          <Card style={{ marginTop: 16 }}>
            <div style={sectionTitle}>Test Scenarios</div>
            <div className="flex gap-2 mb-3">
              <Input
                placeholder="Scenario name (e.g. Procurement Approval Under Limit)"
                value={scenarioName}
                onChange={(e) => setScenarioName(e.target.value)}
                style={{ flex: 1 }}
              />
              <select value={expectedOutcome} onChange={(e) => setExpectedOutcome(e.target.value)} style={getInputStyle("hover")}>
                <option value="ALLOW">Expect: Approve</option>
                <option value="DENY">Expect: Deny</option>
                <option value="HUMAN_REVIEW">Expect: Escalate</option>
              </select>
              <Button size="sm" onClick={saveScenario} pending={savingScenario}>Save</Button>
            </div>
            {scenarios === null ? (
              <p style={{ color: "var(--pr-text-muted)", fontSize: 12 }}>Loading...</p>
            ) : scenarios.length === 0 ? (
              <p style={{ color: "var(--pr-text-muted)", fontSize: 12 }}>No saved scenarios for this policy yet.</p>
            ) : (
              scenarios.map((s) => {
                const run = scenarioRuns[s.id];
                return (
                  <div key={s.id} className="flex items-center justify-between gap-3" style={{ padding: "8px 0", borderTop: "1px solid var(--pr-overlay-05)" }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 13, color: "var(--pr-text-primary)", wordBreak: "break-word" }}>{s.name}</div>
                      <div style={{ fontSize: 11, color: "var(--pr-text-muted)" }}>
                        Expected: {DECISION_STYLE[s.expected_outcome]?.label ?? s.expected_outcome}
                        {run && <> &middot; Actual: {DECISION_STYLE[run.actual]?.label ?? run.actual}</>}
                      </div>
                    </div>
                    <div className="flex items-center gap-2" style={{ flexShrink: 0 }}>
                      {run && <SmallBadge ok={run.passed} trueLabel="PASS" falseLabel="FAIL" />}
                      <Button size="sm" variant="ghost" onClick={() => runSavedScenario(s.id)}>Run</Button>
                    </div>
                  </div>
                );
              })
            )}
          </Card>

          {/* Batch Simulation */}
          <Card style={{ marginTop: 16 }}>
            <div style={sectionTitle}>Batch Simulation</div>
            <p style={{ fontSize: 12, color: "var(--pr-text-muted)", marginBottom: 10 }}>
              Upload a CSV of historical actions (columns: principal, action, resource, amount,
              currency, plus any other column as context) to see the impact of this policy version
              before deploying it. No row is ever persisted.
            </p>
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => e.target.files?.[0] && runBatch(e.target.files[0])}
              style={{ fontSize: 12, color: "var(--pr-text-secondary)" }}
            />
            {batchRunning && <p style={{ fontSize: 12, color: "var(--pr-text-muted)", marginTop: 8 }}>Replaying batch...</p>}
            {batchError && <Alert severity="error" style={{ marginTop: 8 }}>{batchError}</Alert>}
            {batchResult && (
              <div style={{ marginTop: 12 }}>
                <div className="grid grid-cols-4 gap-2 mb-3">
                  {[
                    ["Total", batchResult.total, "var(--pr-text-primary)"],
                    ["Approved", batchResult.allowed, "var(--pr-trust-green)"],
                    ["Escalated", batchResult.escalated, "var(--pr-warning-amber)"],
                    ["Denied", batchResult.denied, "var(--pr-critical-red)"],
                  ].map(([label, value, color]) => (
                    <div key={label as string} style={{ textAlign: "center" }}>
                      <div style={{ fontSize: 18, fontWeight: 700, color: color as string }}>{value}</div>
                      <div style={{ fontSize: 10, color: "var(--pr-text-muted)" }}>{label as string}</div>
                    </div>
                  ))}
                </div>
                {batchResult.errors > 0 && (
                  <p style={{ fontSize: 12, color: "var(--pr-critical-red)" }}>{batchResult.errors} row(s) could not be evaluated.</p>
                )}
                <details style={{ fontSize: 12 }}>
                  <summary style={{ color: "var(--pr-authority-blue)", cursor: "pointer" }}>
                    Sample rows {batchResult.sample_truncated ? "(first 50 of the full batch)" : ""}
                  </summary>
                  <div style={{ marginTop: 8, maxHeight: 240, overflowY: "auto" }}>
                    {batchResult.sample_rows.map((r) => (
                      <div key={r.row_number} className="flex items-center justify-between gap-3" style={{ padding: "4px 0", borderTop: "1px solid var(--pr-overlay-05)" }}>
                        <span style={{ color: "var(--pr-text-secondary)" }}>#{r.row_number} {r.principal} &middot; {r.action}</span>
                        <span style={{ flexShrink: 0, color: r.error ? "var(--pr-critical-red)" : DECISION_STYLE[r.decision ?? ""]?.color }}>
                          {r.error ?? DECISION_STYLE[r.decision ?? ""]?.label ?? r.decision}
                        </span>
                      </div>
                    ))}
                  </div>
                </details>
              </div>
            )}
          </Card>
        </div>

        {/* RIGHT: Runtime Decision / Rule Evaluation / Authority Trace / Evidence Preview */}
        <div>
          {!result ? (
            <Card style={{ textAlign: "center", padding: 48 }}>
              <p style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>
                Run a simulation to see the Runtime Decision, rule-by-rule evaluation, authority
                trace, and evidence preview here.
              </p>
            </Card>
          ) : (
            <>
              <Card style={{ textAlign: "center", marginBottom: 16 }}>
                <div style={{ fontSize: 11, color: "var(--pr-text-muted)", textTransform: "uppercase", marginBottom: 10 }}>
                  Runtime Decision
                </div>
                <DecisionBadge decision={result.decision} />
                {(result.review_reason || result.deny_reason) && (
                  <p style={{ fontSize: 12, color: "var(--pr-text-muted)", marginTop: 10 }}>
                    {result.review_reason ?? result.deny_reason}
                  </p>
                )}
                <div style={{ fontSize: 11, color: "var(--pr-text-muted)", marginTop: 12 }}>
                  Runtime Policy &middot; Version {result.policy_version} &middot; Generated {new Date(result.generated_at).toLocaleString()}
                </div>
                <div style={{ fontSize: 10, color: "var(--pr-text-muted)", marginTop: 4, fontFamily: "monospace", wordBreak: "break-all" }}>
                  SHA256 {result.policy_bundle_hash}
                </div>
              </Card>

              <Card style={{ marginBottom: 16 }}>
                <div style={sectionTitle}>Decision Explanation</div>
                {result.rules.map((r, i) => (
                  <div key={r.policy_id} style={{ padding: "10px 0", borderTop: i > 0 ? "1px solid var(--pr-overlay-05)" : undefined }}>
                    <div className="flex items-center justify-between gap-3">
                      <span style={{ fontSize: 13, color: "var(--pr-text-primary)", fontWeight: 500 }}>
                        Rule {i + 1} &middot; {r.policy_name}
                      </span>
                      <span style={{ flexShrink: 0 }}><SmallBadge ok={r.matched} trueLabel="PASSED" falseLabel="FAILED" /></span>
                    </div>
                    <p style={{ fontSize: 12, color: "var(--pr-text-muted)", marginTop: 2 }}>{r.summary}</p>
                    {r.conditions.map((c, ci) => (
                      <div key={ci} className="flex items-center justify-between" style={{ fontSize: 11, color: "var(--pr-text-secondary)", marginTop: 4, paddingLeft: 12 }}>
                        <span>{c.field} {c.operator} {JSON.stringify(c.expected_value)}</span>
                        <span style={{ color: c.passed ? "var(--pr-trust-green)" : "var(--pr-critical-red)" }}>
                          actual: {JSON.stringify(c.actual_value)}
                        </span>
                      </div>
                    ))}
                  </div>
                ))}
              </Card>

              <Card style={{ marginBottom: 16 }}>
                <div style={sectionTitle}>Authority Trace</div>
                {result.authority_trace.map((step, i) => (
                  <div key={i}>
                    <div style={{ fontSize: 13, color: "var(--pr-text-primary)" }}>{step.label}</div>
                    {step.detail && <div style={{ fontSize: 11, color: "var(--pr-text-muted)" }}>{step.detail}</div>}
                    {i < result.authority_trace.length - 1 && (
                      <div style={{ color: "var(--pr-text-muted)", padding: "2px 0" }}>&darr;</div>
                    )}
                  </div>
                ))}
              </Card>

              <Card>
                <div className="flex items-center justify-between" style={sectionTitle}>
                  <span>Evidence Preview</span>
                  <span style={{ fontSize: 10, color: "var(--pr-warning-amber)", textTransform: "uppercase" }}>Preview -- not persisted</span>
                </div>
                {[
                  ["Decision", DECISION_STYLE[result.evidence_preview.decision]?.label ?? result.evidence_preview.decision],
                  ["Policy Version", result.evidence_preview.policy_version],
                  ["Principal", result.evidence_preview.principal],
                  ["Action", result.evidence_preview.action],
                  ["Resource", result.evidence_preview.resource ?? "--"],
                  ["Evaluation Time", new Date(result.evidence_preview.evaluated_at).toLocaleString()],
                ].map(([label, value]) => (
                  <div key={label as string} className="flex items-center justify-between" style={{ fontSize: 12, padding: "3px 0" }}>
                    <span style={{ color: "var(--pr-text-muted)" }}>{label as string}</span>
                    <span style={{ color: "var(--pr-text-primary)" }}>{value as string}</span>
                  </div>
                ))}
                <div style={{ fontSize: 10, color: "var(--pr-text-muted)", marginTop: 8, fontFamily: "monospace", wordBreak: "break-all" }}>
                  Receipt Hash: {result.evidence_preview.receipt_hash}
                </div>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
