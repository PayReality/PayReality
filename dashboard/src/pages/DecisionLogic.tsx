import { useEffect, useState } from "react"
import { Badge, Button, EmptyPanel, ErrorNote, PageTitle } from "../components/ui"
import { decisionIntelligenceApi } from "../di/api"
import type { Answer, Case, DecisionRule, EvaluationResult, Question, RuleVersion } from "../di/types"
import { useFetch, errorMessage } from "../lib/useAsync"
import type { Page } from "../types"
import { useAuth } from "../auth/AuthContext"

const DEFAULT_SCHEMA = JSON.stringify(
  {
    root_condition: { field: "amount", operator: "lte", value: 500 },
    action: { decision: "approve", human_review_required: false },
    exceptions: [],
    missing_data_behavior: "route_to_human",
  },
  null,
  2,
)

interface ApprovedAnswerOption {
  answer: Answer
  question: Question
}

export function DecisionLogic({ workflowId, setPage }: { workflowId: string | null; setPage: (p: Page) => void }) {
  const { hasPermission } = useAuth()
  const [selectedRuleId, setSelectedRuleId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const { data: rulesPage, loading, error, reload } = useFetch(
    () => (workflowId ? decisionIntelligenceApi.listRules({ workflow_id: workflowId, limit: 200 }) : Promise.resolve(null)),
    [workflowId],
  )
  const rules = rulesPage?.rules ?? []

  useEffect(() => {
    if (rules.length > 0 && (!selectedRuleId || !rules.some((r) => r.id === selectedRuleId))) {
      setSelectedRuleId(rules[0].id)
    }
    if (rules.length === 0) setSelectedRuleId(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rules.map((r) => r.id).join(",")])

  const [approvedAnswers, setApprovedAnswers] = useState<ApprovedAnswerOption[] | null>(null)
  useEffect(() => {
    if (!creating || !workflowId) return
    let cancelled = false
    decisionIntelligenceApi.listQuestions({ workflow_id: workflowId, limit: 200 }).then(async (page) => {
      const options: ApprovedAnswerOption[] = []
      for (const question of page.questions) {
        const answers = await decisionIntelligenceApi.listAnswers(question.id).catch(() => [])
        const approved = answers.find((a) => a.status === "approved")
        if (approved) options.push({ answer: approved, question })
      }
      if (!cancelled) setApprovedAnswers(options)
    })
    return () => {
      cancelled = true
    }
  }, [creating, workflowId])

  if (!workflowId) {
    return (
      <>
        <PageTitle title="Decision Logic" description="Translate authorised answers into explicit, inspectable conditions." />
        <EmptyPanel title="No workflow selected" body="Choose or create a workflow first." />
      </>
    )
  }

  return (
    <>
      <PageTitle
        title="Decision Logic"
        description="Translate authorised answers into explicit, inspectable conditions while keeping exceptions and human judgement visible."
        actions={
          <>
            {hasPermission("di_rule.manage") && (
              <Button kind="primary" onClick={() => setCreating(!creating)}>
                {creating ? "Cancel" : "New rule"}
              </Button>
            )}
            <Button kind="primary" onClick={() => setPage("Testing & Replay")}>
              Configure replay
            </Button>
          </>
        }
      />
      {error && <ErrorNote message={error} />}
      {creating && (
        <CreateRuleForm
          workflowId={workflowId}
          options={approvedAnswers}
          onCreated={(rule) => {
            setCreating(false)
            reload()
            setSelectedRuleId(rule.id)
          }}
        />
      )}
      <div className="logic-layout">
        <section className="panel logic-list">
          <div className="panel-heading">
            <div>
              <h2>Logic sets</h2>
              <p>{loading ? "Loading…" : `${rules.length} rule${rules.length === 1 ? "" : "s"}`}</p>
            </div>
          </div>
          {rules.map((r) => (
            <button className={`logic-item ${selectedRuleId === r.id ? "active" : ""}`} key={r.id} onClick={() => setSelectedRuleId(r.id)}>
              <div>
                <strong>{r.name}</strong>
                <span>Rule {r.id.slice(0, 8)}</span>
              </div>
              <Badge tone={r.status === "validated" ? "success" : "warning"}>{r.status}</Badge>
            </button>
          ))}
          {!loading && rules.length === 0 && (
            <div style={{ padding: 20, color: "var(--muted)", fontSize: 11 }}>
              No decision rules yet. Create one from an approved answer.
            </div>
          )}
        </section>
        {selectedRuleId && <RuleEditor ruleId={selectedRuleId} workflowId={workflowId} onRuleChanged={reload} setPage={setPage} />}
      </div>
    </>
  )
}

function CreateRuleForm({
  workflowId,
  options,
  onCreated,
}: {
  workflowId: string
  options: ApprovedAnswerOption[] | null
  onCreated: (rule: DecisionRule) => void
}) {
  const [name, setName] = useState("")
  const [answerId, setAnswerId] = useState("")
  const [schemaText, setSchemaText] = useState(DEFAULT_SCHEMA)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function submit() {
    if (!name.trim() || !answerId) return
    setSubmitting(true)
    setError(null)
    try {
      let schema_json
      try {
        schema_json = JSON.parse(schemaText)
      } catch {
        throw new Error("Schema must be valid JSON.")
      }
      const rule = await decisionIntelligenceApi.createRule({ workflow_id: workflowId, name: name.trim(), source_answer_id: answerId, schema_json })
      onCreated(rule)
    } catch (err) {
      setError(err instanceof Error ? err.message : errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="panel" style={{ marginBottom: 16 }}>
      <div className="form-body">
        <label>
          Rule name *
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Shared settlement authority" />
        </label>
        <label>
          Source answer (must be approved) *
          {options === null ? (
            <span style={{ fontSize: 11, color: "var(--muted)" }}>Loading approved answers…</span>
          ) : options.length === 0 ? (
            <span style={{ fontSize: 11, color: "var(--muted)" }}>
              No approved answers exist yet in this workflow. Approve an answer on the Questions page first.
            </span>
          ) : (
            <select value={answerId} onChange={(e) => setAnswerId(e.target.value)}>
              <option value="" disabled>
                Choose an approved answer…
              </option>
              {options.map(({ answer, question }) => (
                <option key={answer.id} value={answer.id}>
                  {question.title} (v{answer.version})
                </option>
              ))}
            </select>
          )}
        </label>
        <label>
          Rule schema (JSON) *
          <textarea value={schemaText} onChange={(e) => setSchemaText(e.target.value)} rows={8} style={{ fontFamily: "monospace", fontSize: 11 }} />
        </label>
        {error && <ErrorNote message={error} />}
        <Button kind="primary" onClick={submit} disabled={submitting || !name.trim() || !answerId}>
          {submitting ? "Creating…" : "Create rule"}
        </Button>
      </div>
    </section>
  )
}

function RuleEditor({
  ruleId,
  workflowId,
  onRuleChanged,
  setPage,
}: {
  ruleId: string
  workflowId: string
  onRuleChanged: () => void
  setPage: (p: Page) => void
}) {
  const { hasPermission } = useAuth()
  const rule = useFetch(() => decisionIntelligenceApi.getRule(ruleId), [ruleId])
  const versions = useFetch<RuleVersion[]>(() => decisionIntelligenceApi.listRuleVersions(ruleId), [ruleId])
  const [schemaText, setSchemaText] = useState("")
  const [versionError, setVersionError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [testResult, setTestResult] = useState<EvaluationResult | null>(null)
  const [testError, setTestError] = useState<string | null>(null)
  const [testCaseId, setTestCaseId] = useState("")
  const casesFetch = useFetch<Case[]>(
    () => decisionIntelligenceApi.listCases({ workflow_id: workflowId, limit: 200 }).then((p) => p.cases),
    [workflowId],
  )

  const current = versions.data?.find((v) => v.id === rule.data?.current_version_id) ?? versions.data?.[versions.data.length - 1]

  useEffect(() => {
    setSchemaText(current ? JSON.stringify(current.schema_json, null, 2) : DEFAULT_SCHEMA)
    setTestResult(null)
    setTestError(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id])

  async function saveNewVersion() {
    setBusy(true)
    setVersionError(null)
    try {
      let schema_json
      try {
        schema_json = JSON.parse(schemaText)
      } catch {
        throw new Error("Schema must be valid JSON.")
      }
      await decisionIntelligenceApi.createRuleVersion(ruleId, { schema_json })
      versions.reload()
      rule.reload()
      onRuleChanged()
    } catch (err) {
      setVersionError(err instanceof Error ? err.message : errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function runTest() {
    setTestError(null)
    setTestResult(null)
    try {
      const result = await decisionIntelligenceApi.testRule(ruleId, testCaseId ? { case_id: testCaseId } : {})
      setTestResult(result)
    } catch (err) {
      setTestError(errorMessage(err))
    }
  }

  async function validate() {
    setBusy(true)
    setVersionError(null)
    try {
      await decisionIntelligenceApi.validateRule(ruleId)
      rule.reload()
      onRuleChanged()
    } catch (err) {
      setVersionError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (!rule.data) return <section className="panel logic-editor" style={{ padding: 30 }}>Loading…</section>

  return (
    <section className="panel logic-editor">
      <div className="logic-header">
        <div>
          <div className="eyebrow">{rule.data.status === "validated" ? "Validated logic" : "Draft logic · Not yet validated"}</div>
          <h2>{rule.data.name}</h2>
          <p>Derived from an approved answer. Saving a schema change creates a new, immutable version.</p>
        </div>
        {hasPermission("di_rule.manage") && (
          <Button onClick={validate} disabled={busy}>
            Validate rule
          </Button>
        )}
      </div>
      <div className="source-answer">
        <span>Source answer</span>
        <strong>{rule.data.source_answer_id}</strong>
        <Button kind="ghost" onClick={() => setPage("Questions")}>
          Open questions
        </Button>
      </div>
      {hasPermission("di_rule.manage") && (
        <div className="rule-stack">
          <label style={{ display: "block", marginBottom: 8, fontSize: 10, fontWeight: 600, color: "var(--text-2)" }}>
            Condition tree (JSON -- root_condition / action / exceptions / missing_data_behavior)
          </label>
          <textarea
            value={schemaText}
            onChange={(e) => setSchemaText(e.target.value)}
            rows={10}
            style={{ width: "100%", fontFamily: "monospace", fontSize: 11, border: "1px solid var(--border-strong)", borderRadius: 7, padding: 10 }}
          />
          {versionError && <ErrorNote message={versionError} />}
          <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
            <Button icon="plus" onClick={saveNewVersion} disabled={busy}>
              Save as new version
            </Button>
          </div>
        </div>
      )}
      <div className="rule-stack">
        <label style={{ display: "block", marginBottom: 8, fontSize: 10, fontWeight: 600, color: "var(--text-2)" }}>
          Test this rule against a real case, before validating
        </label>
        <div className="rule-row" style={{ gridTemplateColumns: "1fr 120px" }}>
          <select value={testCaseId} onChange={(e) => setTestCaseId(e.target.value)}>
            <option value="">Choose a case…</option>
            {(casesFetch.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.external_ref ?? c.id.slice(0, 8)}
              </option>
            ))}
          </select>
          <Button onClick={runTest} disabled={!testCaseId}>
            Test this rule
          </Button>
        </div>
        {testError && <ErrorNote message={testError} />}
        {testResult && (
          <div className="outcomes">
            <div>
              <span>RESULT</span>
              <strong>{testResult.matched ? `Matched -> ${testResult.decision}` : "Did not match"}</strong>
              <p>{testResult.human_review_required ? "Flagged for human review." : "No human review required by this rule."}</p>
            </div>
            <div className="exception">
              <span>DETAIL</span>
              <strong>{testResult.missing_fields.length > 0 ? "Missing fields" : "All referenced fields present"}</strong>
              <p>{testResult.missing_fields.join(", ") || "—"}</p>
            </div>
          </div>
        )}
      </div>
      <div className="version-note">
        <Badge tone="info">{versions.data?.length ?? 0} version(s)</Badge>
        <div>
          <strong>Version history</strong>
          <span>{(versions.data ?? []).map((v) => `v${v.version}`).join(", ") || "none yet"}</span>
        </div>
      </div>
    </section>
  )
}
