import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { FlaskConical } from "lucide-react";
import { decisionIntelligenceApi } from "./api";
import { RuleStatusBadge } from "./components/StatusBadges";
import { RuleSchemaView } from "./components/ConditionTree";
import { describeApiError } from "../live/format";
import { useResourceSync } from "../services/resourceSync";
import type { Case, DecisionRule, EvaluationResult, RuleSchema, RuleVersion } from "./types";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Select } from "../components/ui/select";
import { ConfirmButton } from "../components/ui/confirm-button";
import { PageHeader } from "../components/ui/page-header";
import { Skeleton } from "../components/ui/skeleton";
import { NextStepGuidance } from "../help/NextStepGuidance";

export function RuleDetailPage() {
  const { ruleId } = useParams();
  const navigate = useNavigate();

  const [rule, setRule] = useState<DecisionRule | null>(null);
  const [versions, setVersions] = useState<RuleVersion[]>([]);
  const [cases, setCases] = useState<Case[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);

  const [testMode, setTestMode] = useState<"case" | "facts">("facts");
  const [testCaseId, setTestCaseId] = useState("");
  const [testFactsJson, setTestFactsJson] = useState("{}");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<EvaluationResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);

  const [showVersionForm, setShowVersionForm] = useState(false);
  const [versionSchemaJson, setVersionSchemaJson] = useState("");
  const [versionScope, setVersionScope] = useState("");
  const [creatingVersion, setCreatingVersion] = useState(false);
  const [versionError, setVersionError] = useState<string | null>(null);

  function load() {
    if (!ruleId) return;
    setLoadError(null);
    Promise.all([decisionIntelligenceApi.getRule(ruleId), decisionIntelligenceApi.listRuleVersions(ruleId)])
      .then(([r, vs]) => {
        setRule(r);
        setVersions(vs);
      })
      .catch((e) => setLoadError(describeApiError(e, "Loading rule")));
  }

  useEffect(load, [ruleId]);
  useResourceSync(["decision-intelligence"], load);

  useEffect(() => {
    if (!rule) return;
    decisionIntelligenceApi.listCases({ workflow_id: rule.workflow_id, limit: 200 }).then((p) => setCases(p.cases)).catch(() => {});
  }, [rule?.workflow_id]);

  const currentVersion = versions.find((v) => v.id === rule?.current_version_id) ?? null;

  async function handleValidate() {
    if (!rule) return;
    setValidating(true);
    setMessage(null);
    try {
      const updated = await decisionIntelligenceApi.validateRule(rule.id);
      setRule(updated);
    } catch (e) {
      setMessage(describeApiError(e, "Validate rule"));
    } finally {
      setValidating(false);
    }
  }

  async function handleTest() {
    if (!rule) return;
    setTesting(true);
    setTestError(null);
    setTestResult(null);
    try {
      if (testMode === "case") {
        if (!testCaseId) {
          setTestError("Select a case to test against.");
          return;
        }
        const result = await decisionIntelligenceApi.testRule(rule.id, { case_id: testCaseId });
        setTestResult(result);
      } else {
        let facts: Record<string, unknown>;
        try {
          facts = JSON.parse(testFactsJson);
        } catch {
          setTestError("Facts must be valid JSON.");
          return;
        }
        const result = await decisionIntelligenceApi.testRule(rule.id, { case_facts: facts });
        setTestResult(result);
      }
    } catch (e) {
      setTestError(describeApiError(e, "Test rule"));
    } finally {
      setTesting(false);
    }
  }

  async function handleCreateVersion() {
    if (!rule) return;
    let schema: RuleSchema;
    try {
      schema = JSON.parse(versionSchemaJson);
    } catch {
      setVersionError("Schema must be valid JSON.");
      return;
    }
    setCreatingVersion(true);
    setVersionError(null);
    try {
      await decisionIntelligenceApi.createRuleVersion(rule.id, { schema_json: schema, scope: versionScope || undefined });
      setShowVersionForm(false);
      setVersionSchemaJson("");
      setVersionScope("");
      load();
    } catch (e) {
      setVersionError(describeApiError(e, "Create rule version"));
    } finally {
      setCreatingVersion(false);
    }
  }

  if (!rule && loadError) {
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

  if (!rule) {
    return (
      <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
        <Skeleton height={16} width={160} style={{ marginBottom: 24 }} />
        <Skeleton height={28} width="40%" style={{ marginBottom: 16 }} />
        <Skeleton height={160} style={{ marginBottom: 16 }} />
        <Skeleton height={160} />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-4xl" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <Link to={`/decision-intelligence/workflows/${rule.workflow_id}`} style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>
        &lt; Back to workflow
      </Link>
      <PageHeader
        title={rule.name}
        status={<RuleStatusBadge status={rule.status} />}
        secondaryAction={
          rule.status === "draft" && (
            <ConfirmButton size="sm" confirmLabel="Confirm validate" disabled={validating} onConfirm={handleValidate}>
              {validating ? "Validating..." : "Validate rule"}
            </ConfirmButton>
          )
        }
      />

      {message && <Alert severity="error" className="text-sm mb-4">{message}</Alert>}

      {rule.status === "validated" && (
        <NextStepGuidance
          message="This rule is validated. Run a Replay against real historical cases to see how often it would have agreed or disagreed with the human decisions already recorded -- agreement is not the same claim as correctness."
          actionLabel="Configure a replay"
          actionPath={`/decision-intelligence/replays/new?workflowId=${rule.workflow_id}&ruleVersionId=${rule.current_version_id ?? ""}&ruleId=${rule.id}`}
        />
      )}

      <Card className="mb-6 mt-6">
        <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>
          Current version (v{currentVersion?.version ?? "?"})
        </h2>
        {currentVersion ? (
          <RuleSchemaView schema={currentVersion.schema_json} />
        ) : (
          <p style={{ fontSize: 13, color: "var(--pr-text-disabled)", fontStyle: "italic" }}>This rule has no version yet.</p>
        )}
      </Card>

      <Card className="mb-6">
        <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>Test this rule</h2>
        <p className="mb-3" style={{ fontSize: 12, color: "var(--pr-text-disabled)" }}>
          Never persists anything -- shows what the rule's current version would decide, using the same interpreter the real replay executor uses.
        </p>
        <div className="flex items-center gap-2 mb-3">
          <label className="flex items-center gap-1.5 text-xs" style={{ color: "var(--pr-text-muted)" }}>
            <input type="radio" checked={testMode === "facts"} onChange={() => setTestMode("facts")} /> Hand-entered facts
          </label>
          <label className="flex items-center gap-1.5 text-xs" style={{ color: "var(--pr-text-muted)" }}>
            <input type="radio" checked={testMode === "case"} onChange={() => setTestMode("case")} /> An existing case
          </label>
        </div>
        {testMode === "facts" ? (
          <textarea
            value={testFactsJson}
            onChange={(e) => setTestFactsJson(e.target.value)}
            rows={4}
            className="w-full px-3 py-2 rounded-lg border text-sm font-mono mb-3"
            style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
          />
        ) : (
          <Select
            value={testCaseId}
            onChange={(e) => setTestCaseId(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border text-sm mb-3"
            style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
          >
            <option value="">Select a case...</option>
            {cases.map((c) => (
              <option key={c.id} value={c.id}>{c.external_ref || c.id.slice(0, 8)}</option>
            ))}
          </Select>
        )}
        <Button size="sm" onClick={handleTest} disabled={testing} pending={testing}>
          {testing ? "Testing..." : "Run test"}
        </Button>
        {testError && <Alert severity="error" className="text-sm mt-3">{testError}</Alert>}
        {testResult && (
          <div className="mt-4 p-3 rounded-lg" style={{ backgroundColor: "var(--pr-overlay-04)" }}>
            <div className="flex items-center gap-2 mb-2">
              <span style={{ fontSize: 13, fontWeight: 600, color: testResult.matched ? "var(--pr-trust-green)" : "var(--pr-text-muted)" }}>
                {testResult.matched ? "Matched" : "Did not match"}
              </span>
              {testResult.decision && <span style={{ fontSize: 13, color: "var(--pr-text-primary)" }}>Decision: <strong>{testResult.decision}</strong></span>}
              {testResult.human_review_required && <span style={{ fontSize: 12, color: "var(--pr-warning-amber)" }}>Human review required</span>}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
              <div>
                <p className="font-medium mb-1" style={{ color: "var(--pr-trust-green)" }}>Matched conditions</p>
                {testResult.matched_conditions.length === 0 ? <p style={{ color: "var(--pr-text-disabled)" }}>None</p> : testResult.matched_conditions.map((c, i) => <p key={i} style={{ color: "var(--pr-text-secondary)" }}>{c}</p>)}
              </div>
              <div>
                <p className="font-medium mb-1" style={{ color: "var(--pr-text-muted)" }}>Unmatched conditions</p>
                {testResult.unmatched_conditions.length === 0 ? <p style={{ color: "var(--pr-text-disabled)" }}>None</p> : testResult.unmatched_conditions.map((c, i) => <p key={i} style={{ color: "var(--pr-text-secondary)" }}>{c}</p>)}
              </div>
              <div>
                <p className="font-medium mb-1" style={{ color: "var(--pr-warning-amber)" }}>Missing fields</p>
                {testResult.missing_fields.length === 0 ? <p style={{ color: "var(--pr-text-disabled)" }}>None</p> : testResult.missing_fields.map((c, i) => <p key={i} style={{ color: "var(--pr-text-secondary)" }}>{c}</p>)}
              </div>
            </div>
          </div>
        )}
      </Card>

      <Card className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>Version history</h2>
          {!showVersionForm && (
            <Button size="sm" variant="ghost" onClick={() => { setVersionSchemaJson(currentVersion ? JSON.stringify(currentVersion.schema_json, null, 2) : ""); setShowVersionForm(true); }}>
              New version
            </Button>
          )}
        </div>
        {showVersionForm && (
          <div className="mb-4 p-3 rounded-lg" style={{ backgroundColor: "var(--pr-overlay-04)" }}>
            <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Schema JSON</label>
            <textarea
              value={versionSchemaJson}
              onChange={(e) => setVersionSchemaJson(e.target.value)}
              rows={8}
              className="w-full px-3 py-2 rounded-lg border text-xs font-mono mb-2"
              style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
            />
            <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Scope (optional)</label>
            <input
              value={versionScope}
              onChange={(e) => setVersionScope(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border text-sm mb-3"
              style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
            />
            <div className="flex items-center gap-2">
              <Button size="sm" onClick={handleCreateVersion} disabled={creatingVersion} pending={creatingVersion}>{creatingVersion ? "Creating..." : "Create version"}</Button>
              <Button size="sm" variant="ghost" onClick={() => setShowVersionForm(false)}>Cancel</Button>
            </div>
            {versionError && <Alert severity="error" className="text-sm mt-3">{versionError}</Alert>}
          </div>
        )}
        {versions
          .slice()
          .sort((a, b) => b.version - a.version)
          .map((v) => (
            <div key={v.id} className="flex items-center justify-between py-1.5" style={{ borderTop: "1px solid var(--pr-overlay-05)", fontSize: 13 }}>
              <span style={{ color: "var(--pr-text-primary)" }}>
                v{v.version} {v.id === rule.current_version_id && <span style={{ color: "var(--pr-authority-blue)" }}>(current)</span>}
              </span>
              <span style={{ color: "var(--pr-text-muted)", fontSize: 12 }}>{new Date(v.created_at).toLocaleDateString()}</span>
            </div>
          ))}
      </Card>

      {rule.status === "validated" && (
        <div className="flex items-center gap-1.5" style={{ fontSize: 12, color: "var(--pr-text-disabled)" }}>
          <FlaskConical className="w-3.5 h-3.5" />
          <Link
            to={`/decision-intelligence/replays/new?workflowId=${rule.workflow_id}&ruleVersionId=${rule.current_version_id ?? ""}&ruleId=${rule.id}`}
            style={{ color: "var(--pr-authority-blue)" }}
          >
            Configure a new replay for this rule &rarr;
          </Link>
        </div>
      )}
    </div>
  );
}
