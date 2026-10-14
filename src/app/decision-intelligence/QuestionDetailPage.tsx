import { useEffect, useId, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { decisionIntelligenceApi } from "./api";
import { AnswerStatusBadge } from "./components/StatusBadges";
import { QuestionStatusStepper } from "./components/QuestionStatusStepper";
import { ScoreDisplay } from "./components/ScoreDisplay";
import { describeApiError } from "../live/format";
import { useAuth } from "../auth/AuthContext";
import { usersApi } from "../organization/api";
import { useResourceSync } from "../services/resourceSync";
import type { Answer, DecisionRule, QuestionDetail, RuleSchema } from "./types";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { ConfirmButton } from "../components/ui/confirm-button";
import { PageHeader } from "../components/ui/page-header";
import { EmptyState } from "../components/ui/empty-state";
import { Skeleton } from "../components/ui/skeleton";
import { useToast } from "../components/ui/toast";
import { ListTree, FileCheck, ScrollText } from "lucide-react";

const DEFAULT_RULE_SCHEMA = `{
  "root_condition": { "field": "amount", "operator": "lte", "value": 1000 },
  "action": { "decision": "approve", "human_review_required": false },
  "exceptions": [],
  "missing_data_behavior": "route_to_human"
}`;

export function QuestionDetailPage() {
  const { workflowId, questionId } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { notify } = useToast();
  const formId = useId();

  const [detail, setDetail] = useState<QuestionDetail | null>(null);
  const [answers, setAnswers] = useState<Answer[] | null>(null);
  const [rules, setRules] = useState<DecisionRule[]>([]);
  const [userNames, setUserNames] = useState<Record<string, string>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  // Dimension-score editing (scoring.py: five independently-judged 0-100
  // inputs; each stays blank/untouched here rather than defaulting to 0,
  // so saving never overwrites a dimension the reviewer didn't mean to
  // touch -- updateQuestion only sends fields that are actually set).
  const [reach, setReach] = useState("");
  const [impact, setImpact] = useState("");
  const [risk, setRisk] = useState("");
  const [answerability, setAnswerability] = useState("");
  const [decisionSensitivity, setDecisionSensitivity] = useState("");
  const [savingScores, setSavingScores] = useState(false);

  const [showDraftForm, setShowDraftForm] = useState(false);
  const [draftContent, setDraftContent] = useState("");
  const [draftScope, setDraftScope] = useState("");
  const [creatingDraft, setCreatingDraft] = useState(false);

  const [showRuleForm, setShowRuleForm] = useState(false);
  const [ruleName, setRuleName] = useState("");
  const [ruleSchemaJson, setRuleSchemaJson] = useState(DEFAULT_RULE_SCHEMA);
  const [creatingRule, setCreatingRule] = useState(false);
  const [ruleError, setRuleError] = useState<string | null>(null);

  const [supersedingAnswerId, setSupersedingAnswerId] = useState<string | null>(null);
  const [supersedeContent, setSupersedeContent] = useState("");

  function load() {
    if (!questionId) return;
    setLoadError(null);
    decisionIntelligenceApi
      .getQuestion(questionId)
      .then((d) => {
        setDetail(d);
        setReach(d.question.reach_score?.toString() ?? "");
        setImpact(d.question.impact_score?.toString() ?? "");
        setRisk(d.question.risk_score?.toString() ?? "");
        setAnswerability(d.question.answerability_score?.toString() ?? "");
        setDecisionSensitivity(d.question.decision_sensitivity_score?.toString() ?? "");
      })
      .catch((e) => setLoadError(describeApiError(e, "Loading question")));
  }

  function loadAnswers() {
    if (!questionId) return;
    decisionIntelligenceApi.listAnswers(questionId).then(setAnswers).catch(() => setAnswers([]));
  }

  useEffect(load, [questionId]);
  useEffect(loadAnswers, [questionId]);
  useResourceSync(["decision-intelligence"], () => { load(); loadAnswers(); });

  useEffect(() => {
    usersApi.list().then((users) => setUserNames(Object.fromEntries(users.map((u) => [u.id, u.name])))).catch(() => {});
  }, []);

  useEffect(() => {
    if (!workflowId) return;
    decisionIntelligenceApi.listRules({ workflow_id: workflowId, limit: 200 }).then((p) => setRules(p.rules)).catch(() => {});
  }, [workflowId]);

  const approvedAnswer = useMemo(() => answers?.find((a) => a.status === "approved") ?? null, [answers]);
  const ruleForApprovedAnswer = useMemo(
    () => (approvedAnswer ? rules.find((r) => r.source_answer_id === approvedAnswer.id) ?? null : null),
    [rules, approvedAnswer]
  );
  const hasActiveDraft = useMemo(
    () => (answers ?? []).some((a) => a.status === "draft" || a.status === "submitted" || a.status === "under_review"),
    [answers]
  );

  async function handleSaveScores() {
    if (!questionId) return;
    setSavingScores(true);
    setMessage(null);
    try {
      await decisionIntelligenceApi.updateQuestion(questionId, {
        reach_score: reach === "" ? undefined : Number(reach),
        impact_score: impact === "" ? undefined : Number(impact),
        risk_score: risk === "" ? undefined : Number(risk),
        answerability_score: answerability === "" ? undefined : Number(answerability),
        decision_sensitivity_score: decisionSensitivity === "" ? undefined : Number(decisionSensitivity),
      });
      await decisionIntelligenceApi.scoreQuestion(questionId);
      load();
    } catch (e) {
      setMessage(describeApiError(e, "Save scores"));
    } finally {
      setSavingScores(false);
    }
  }

  async function runTransition(label: string, fn: () => Promise<unknown>) {
    setPending(label);
    setMessage(null);
    try {
      await fn();
      load();
    } catch (e) {
      setMessage(describeApiError(e, label));
    } finally {
      setPending(null);
    }
  }

  async function handleCreateDraft() {
    if (!questionId || !draftContent.trim()) return;
    setCreatingDraft(true);
    setMessage(null);
    try {
      await decisionIntelligenceApi.createDraftAnswer(questionId, { content: draftContent, scope: draftScope || undefined });
      setDraftContent("");
      setDraftScope("");
      setShowDraftForm(false);
      loadAnswers();
      load();
    } catch (e) {
      setMessage(describeApiError(e, "Create draft answer"));
    } finally {
      setCreatingDraft(false);
    }
  }

  async function handleAnswerAction(answerId: string, action: "submit" | "approve" | "reject") {
    setPending(action + answerId);
    setMessage(null);
    try {
      if (action === "submit") await decisionIntelligenceApi.submitAnswer(answerId);
      if (action === "approve") await decisionIntelligenceApi.approveAnswer(answerId);
      if (action === "reject") await decisionIntelligenceApi.rejectAnswer(answerId);
      loadAnswers();
      load();
    } catch (e) {
      notify(describeApiError(e, action === "submit" ? "Submit answer" : action === "approve" ? "Approve answer" : "Reject answer"), "error");
    } finally {
      setPending(null);
    }
  }

  async function handleSupersede(answerId: string) {
    if (!supersedeContent.trim()) return;
    setPending("supersede" + answerId);
    setMessage(null);
    try {
      await decisionIntelligenceApi.supersedeAnswer(answerId, { content: supersedeContent });
      setSupersedingAnswerId(null);
      setSupersedeContent("");
      loadAnswers();
      load();
    } catch (e) {
      setMessage(describeApiError(e, "Supersede answer"));
    } finally {
      setPending(null);
    }
  }

  async function handleCreateRule() {
    if (!workflowId || !approvedAnswer || !ruleName.trim()) return;
    let schema: RuleSchema;
    try {
      schema = JSON.parse(ruleSchemaJson);
    } catch {
      setRuleError("Schema must be valid JSON.");
      return;
    }
    setCreatingRule(true);
    setRuleError(null);
    try {
      const rule = await decisionIntelligenceApi.createRule({
        workflow_id: workflowId,
        name: ruleName,
        source_answer_id: approvedAnswer.id,
        schema_json: schema,
      });
      navigate(`/decision-intelligence/rules/${rule.id}`);
    } catch (e) {
      setRuleError(describeApiError(e, "Create decision rule"));
    } finally {
      setCreatingRule(false);
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

  if (!detail) {
    return (
      <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
        <Skeleton height={16} width={160} style={{ marginBottom: 24 }} />
        <Skeleton height={28} width="50%" style={{ marginBottom: 16 }} />
        <Skeleton height={100} style={{ marginBottom: 16 }} />
        <Skeleton height={160} />
      </div>
    );
  }

  const { question, patterns, case_ids } = detail;

  return (
    <div className="p-8 max-w-4xl" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <Link to={`/decision-intelligence/workflows/${workflowId}/questions`} style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>
        &lt; Back to Priority questions
      </Link>
      <PageHeader title={question.title} description={question.description ?? undefined} />

      <div className="mb-6">
        <QuestionStatusStepper status={question.status} />
      </div>

      {message && <Alert severity="error" className="text-sm mb-4">{message}</Alert>}

      <Card className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>Priority scoring</h2>
          <span style={{ fontSize: 12, color: "var(--pr-text-muted)" }}>
            Priority score: {question.priority_score === null ? <em style={{ color: "var(--pr-text-disabled)" }}>Not yet assessed</em> : <strong>{question.priority_score.toFixed(2)}</strong>}
          </span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-4">
          <ScoreDisplay label="Reach" value={question.reach_score} />
          <ScoreDisplay label="Impact" value={question.impact_score} />
          <ScoreDisplay label="Risk" value={question.risk_score} />
          <ScoreDisplay label="Answerability" value={question.answerability_score} />
          <ScoreDisplay label="Decision sensitivity" value={question.decision_sensitivity_score} />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-3">
          {[
            { label: "Reach", value: reach, set: setReach },
            { label: "Impact", value: impact, set: setImpact },
            { label: "Risk", value: risk, set: setRisk },
            { label: "Answerability", value: answerability, set: setAnswerability },
            { label: "Decision sensitivity", value: decisionSensitivity, set: setDecisionSensitivity },
          ].map((f) => (
            <div key={f.label}>
              <label className="block text-xs mb-1" style={{ color: "var(--pr-text-muted)" }}>{f.label}</label>
              <input
                type="number"
                min={0}
                max={100}
                value={f.value}
                onChange={(e) => f.set(e.target.value)}
                placeholder="0-100"
                className="w-full px-2 py-1.5 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
            </div>
          ))}
        </div>
        <Button size="sm" onClick={handleSaveScores} disabled={savingScores} pending={savingScores}>
          {savingScores ? "Saving..." : "Save scores & recompute priority"}
        </Button>
      </Card>

      <div className="flex flex-wrap gap-2 mb-6">
        {(question.status === "proposed" || question.status === "in_analysis") && (
          <Button size="sm" disabled={!!pending} pending={pending === "Submit for review"} onClick={() => runTransition("Submit for review", () => decisionIntelligenceApi.submitQuestionForReview(question.id))}>
            Submit for review
          </Button>
        )}
        {question.status === "replay_completed" && (
          <Button size="sm" disabled={!!pending} pending={pending === "Mark ready for review"} onClick={() => runTransition("Mark ready for review", () => decisionIntelligenceApi.markQuestionReadyForReview(question.id))}>
            Mark ready for review
          </Button>
        )}
        {question.status === "ready_for_review" && (
          <ConfirmButton size="sm" variant="tint-success" confirmLabel="Confirm approval" disabled={!!pending} onConfirm={() => runTransition("Approve for operational use", () => decisionIntelligenceApi.approveQuestionForOperationalUse(question.id))}>
            Approve for operational use
          </ConfirmButton>
        )}
      </div>

      <Card className="mb-6">
        <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>Evidence behind this question</h2>
        <p className="text-xs font-medium mb-2" style={{ color: "var(--pr-text-muted)" }}>Linked patterns ({patterns.length})</p>
        {patterns.length === 0 ? (
          <p style={{ fontSize: 13, color: "var(--pr-text-disabled)", fontStyle: "italic" }}>No patterns linked yet.</p>
        ) : (
          <div className="flex flex-col gap-1 mb-3">
            {patterns.map((p) => (
              <Link key={p.id} to={`/decision-intelligence/workflows/${workflowId}/patterns/${p.id}`} style={{ color: "var(--pr-authority-blue)", fontSize: 13 }}>
                {p.name}
              </Link>
            ))}
          </div>
        )}
        <p className="text-xs font-medium mb-2" style={{ color: "var(--pr-text-muted)" }}>Linked cases ({case_ids.length})</p>
        {case_ids.length === 0 ? (
          <p style={{ fontSize: 13, color: "var(--pr-text-disabled)", fontStyle: "italic" }}>No cases linked yet.</p>
        ) : (
          <div className="flex flex-col gap-1">
            {case_ids.map((id) => (
              <Link key={id} to={`/decision-intelligence/workflows/${workflowId}/cases/${id}`} style={{ color: "var(--pr-authority-blue)", fontSize: 13 }}>
                {id.slice(0, 8)}
              </Link>
            ))}
          </div>
        )}
      </Card>

      <Card className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>Answer lifecycle</h2>
          {!hasActiveDraft && !showDraftForm && (
            <Button size="sm" variant="ghost" onClick={() => setShowDraftForm(true)}>Draft an answer</Button>
          )}
        </div>

        {showDraftForm && (
          <div className="mb-4 p-3 rounded-lg" style={{ backgroundColor: "var(--pr-overlay-04)" }}>
            <label htmlFor={`${formId}-draft-content`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Answer content</label>
            <textarea
              id={`${formId}-draft-content`}
              value={draftContent}
              onChange={(e) => setDraftContent(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 rounded-lg border text-sm mb-2"
              style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
            />
            <label htmlFor={`${formId}-draft-scope`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
              Scope <span style={{ fontWeight: 400, color: "var(--pr-text-disabled)" }}>(optional)</span>
            </label>
            <input
              id={`${formId}-draft-scope`}
              value={draftScope}
              onChange={(e) => setDraftScope(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border text-sm mb-3"
              style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
            />
            <div className="flex items-center gap-2">
              <Button size="sm" onClick={handleCreateDraft} disabled={creatingDraft || !draftContent.trim()} pending={creatingDraft}>
                {creatingDraft ? "Creating..." : "Save draft"}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setShowDraftForm(false)}>Cancel</Button>
            </div>
          </div>
        )}

        {answers === null && <p style={{ fontSize: 13, color: "var(--pr-text-muted)" }}>Loading answers...</p>}
        {answers?.length === 0 && !showDraftForm && (
          <EmptyState icon={FileCheck} title="No answer drafted yet" description="An authoritative answer needs to be drafted, submitted, and approved by someone other than its author." />
        )}
        {answers?.map((a) => {
          const isAuthor = !!user && user.id === a.author_user_id;
          const canDecide = a.status === "submitted" || a.status === "under_review";
          return (
            <div key={a.id} className="py-3" style={{ borderTop: "1px solid var(--pr-overlay-05)" }}>
              <div className="flex items-center justify-between mb-1">
                <span style={{ fontSize: 13, fontWeight: 600, color: "var(--pr-text-primary)" }}>Version {a.version}</span>
                <AnswerStatusBadge status={a.status} />
              </div>
              <p style={{ fontSize: 13, color: "var(--pr-text-secondary)" }}>{a.content}</p>
              <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2" style={{ fontSize: 11.5, color: "var(--pr-text-disabled)" }}>
                <span>Authored by {userNames[a.author_user_id] ?? a.author_user_id.slice(0, 8)}</span>
                {a.approver_user_id && <span>Decided by {userNames[a.approver_user_id] ?? a.approver_user_id.slice(0, 8)}</span>}
                {a.submitted_at && <span>Submitted {new Date(a.submitted_at).toLocaleDateString()}</span>}
                {a.decided_at && <span>Decided {new Date(a.decided_at).toLocaleDateString()}</span>}
              </div>

              <div className="flex flex-wrap items-center gap-2 mt-3">
                {a.status === "draft" && (
                  <Button size="sm" disabled={pending === "submit" + a.id} pending={pending === "submit" + a.id} onClick={() => handleAnswerAction(a.id, "submit")}>
                    Submit for approval
                  </Button>
                )}
                {canDecide && (
                  <>
                    <ConfirmButton
                      size="sm"
                      variant="tint-success"
                      confirmLabel="Confirm approve"
                      disabled={isAuthor || pending === "approve" + a.id}
                      onConfirm={() => handleAnswerAction(a.id, "approve")}
                    >
                      Approve
                    </ConfirmButton>
                    <ConfirmButton
                      size="sm"
                      variant="tint-danger"
                      confirmLabel="Confirm reject"
                      disabled={isAuthor || pending === "reject" + a.id}
                      onConfirm={() => handleAnswerAction(a.id, "reject")}
                    >
                      Reject
                    </ConfirmButton>
                    {isAuthor && (
                      <span style={{ fontSize: 12, color: "var(--pr-warning-amber)" }}>
                        You authored this answer, so you can't also approve or reject it -- separation of duties requires a different reviewer.
                      </span>
                    )}
                  </>
                )}
                {a.status === "approved" && supersedingAnswerId !== a.id && (
                  <Button size="sm" variant="ghost" onClick={() => setSupersedingAnswerId(a.id)}>Supersede with a new version</Button>
                )}
              </div>

              {supersedingAnswerId === a.id && (
                <div className="mt-3 p-3 rounded-lg" style={{ backgroundColor: "var(--pr-overlay-04)" }}>
                  <textarea
                    value={supersedeContent}
                    onChange={(e) => setSupersedeContent(e.target.value)}
                    rows={3}
                    placeholder="New answer content"
                    className="w-full px-3 py-2 rounded-lg border text-sm mb-2"
                    style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
                  />
                  <div className="flex items-center gap-2">
                    <Button size="sm" disabled={!supersedeContent.trim() || pending === "supersede" + a.id} pending={pending === "supersede" + a.id} onClick={() => handleSupersede(a.id)}>
                      Create new version
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setSupersedingAnswerId(null)}>Cancel</Button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </Card>

      {approvedAnswer && (
        <Card>
          <div className="flex items-center gap-1.5 mb-3">
            <ScrollText className="w-4 h-4" style={{ color: "var(--pr-authority-blue)" }} />
            <h2 className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>Decision rule</h2>
          </div>
          {ruleForApprovedAnswer ? (
            <Link to={`/decision-intelligence/rules/${ruleForApprovedAnswer.id}`} style={{ color: "var(--pr-authority-blue)", fontSize: 13 }}>
              View "{ruleForApprovedAnswer.name}" &rarr;
            </Link>
          ) : showRuleForm ? (
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Rule name</label>
              <input
                value={ruleName}
                onChange={(e) => setRuleName(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border text-sm mb-3"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                Condition tree (JSON) <span style={{ fontWeight: 400, color: "var(--pr-text-disabled)" }}>-- edit, test, and version it further from the rule's own page once created</span>
              </label>
              <textarea
                value={ruleSchemaJson}
                onChange={(e) => setRuleSchemaJson(e.target.value)}
                rows={8}
                className="w-full px-3 py-2 rounded-lg border text-xs font-mono mb-3"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
              <div className="flex items-center gap-2">
                <Button size="sm" onClick={handleCreateRule} disabled={creatingRule || !ruleName.trim()} pending={creatingRule}>
                  {creatingRule ? "Creating..." : "Create decision rule"}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setShowRuleForm(false)}>Cancel</Button>
              </div>
              {ruleError && <Alert severity="error" className="text-sm mt-3">{ruleError}</Alert>}
            </div>
          ) : (
            <div>
              <p className="mb-3" style={{ fontSize: 13, color: "var(--pr-text-secondary)" }}>
                This question has an approved answer (version {approvedAnswer.version}). It can now become an inspectable, versioned decision rule.
              </p>
              <Button size="sm" onClick={() => setShowRuleForm(true)}>
                <ListTree className="w-3.5 h-3.5 mr-1.5 inline" /> Create decision rule from this answer
              </Button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
