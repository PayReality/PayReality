import { useEffect, useId, useState } from "react";
import { Link, useParams } from "react-router";
import { HelpCircle, Plus } from "lucide-react";
import { decisionIntelligenceApi } from "./api";
import { QuestionStatusStepper } from "./components/QuestionStatusStepper";
import { PriorityScoreCell } from "./components/ScoreDisplay";
import { describeApiError } from "../live/format";
import { useResourceSync } from "../services/resourceSync";
import type { Question, QuestionStatus } from "./types";
import { QUESTION_STATUS_ORDER } from "./types";
import { QUESTION_STATUS_LABEL } from "./components/QuestionStatusStepper";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Select } from "../components/ui/select";
import { SkeletonRows } from "../components/ui/skeleton";
import { PageHeader } from "../components/ui/page-header";
import { EmptyState } from "../components/ui/empty-state";
import { useToast } from "../components/ui/toast";
import { NextStepGuidance } from "../help/NextStepGuidance";
import { Table, TableHead, TableBody, TableRow, TableHeaderCell, TableCell } from "../components/ui/table";

const PAGE_SIZE = 50;

// This is the core differentiator page: which question, if answered,
// resolves the most uncertainty. Sortable by priority_score (the
// backend's own fixed v1 weighting, scoring.py) and filterable by the
// question's 10-value lifecycle status.
export function QuestionsPage() {
  const formId = useId();
  const { workflowId } = useParams();
  const { notify } = useToast();
  const [questions, setQuestions] = useState<Question[] | null>(null);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [sortBy, setSortBy] = useState<"priority_score" | "created_at">("priority_score");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [scoringId, setScoringId] = useState<string | null>(null);

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [justCreatedId, setJustCreatedId] = useState<string | null>(null);

  function load() {
    if (!workflowId) return;
    setLoadError(null);
    decisionIntelligenceApi
      .listQuestions({ workflow_id: workflowId, status: statusFilter || undefined, sort_by: sortBy, limit: PAGE_SIZE })
      .then((page) => {
        setQuestions(page.questions);
        setTotal(page.total);
      })
      .catch((e) => setLoadError(describeApiError(e, "Loading priority questions")));
  }

  useEffect(load, [workflowId, statusFilter, sortBy]);
  useResourceSync(["decision-intelligence"], load);

  async function handleCreate() {
    if (!workflowId || !title.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const created = await decisionIntelligenceApi.createQuestion({ workflow_id: workflowId, title, description: description || undefined });
      setTitle("");
      setDescription("");
      setShowCreateForm(false);
      setJustCreatedId(created.id);
      load();
    } catch (e) {
      setCreateError(describeApiError(e, "Create question"));
    } finally {
      setCreating(false);
    }
  }

  async function handleScore(questionId: string) {
    setScoringId(questionId);
    try {
      await decisionIntelligenceApi.scoreQuestion(questionId);
      load();
    } catch (e) {
      notify(describeApiError(e, "Score question"), "error");
    } finally {
      setScoringId(null);
    }
  }

  return (
    <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <Link to={`/decision-intelligence/workflows/${workflowId}`} style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>
        &lt; Back to workflow
      </Link>
      <PageHeader
        title="Priority questions"
        description="Which question, if answered, resolves the most uncertainty across this workflow's cases -- ranked by a fixed, versioned formula over five human-judged dimensions, never a fabricated score."
        primaryAction={
          <Button onClick={() => setShowCreateForm((s) => !s)}>
            <Plus className="w-4 h-4 mr-1.5 inline" /> New question
          </Button>
        }
      />

      {justCreatedId && (
        <NextStepGuidance
          message="This question has no dimension scores yet -- reach, impact, risk, answerability, and decision sensitivity all need a human judgement before a priority score can be computed."
          actionLabel="Open the question"
          actionPath={`/decision-intelligence/workflows/${workflowId}/questions/${justCreatedId}`}
        />
      )}

      {showCreateForm && (
        <Card padding={20} className="mb-6 mt-4">
          <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>New priority question</h2>
          <div className="grid grid-cols-1 gap-3 mb-3">
            <div>
              <label htmlFor={`${formId}-title`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Title</label>
              <input
                id={`${formId}-title`}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="What refund threshold should trigger manual review?"
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
            </div>
            <div>
              <label htmlFor={`${formId}-description`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                Description <span style={{ fontWeight: 400, color: "var(--pr-text-disabled)" }}>(optional)</span>
              </label>
              <textarea
                id={`${formId}-description`}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={handleCreate} disabled={creating || !title.trim()} pending={creating}>{creating ? "Creating..." : "Create question"}</Button>
            <Button variant="ghost" onClick={() => setShowCreateForm(false)}>Cancel</Button>
          </div>
          {createError && <Alert severity="error" className="text-sm mt-3">{createError}</Alert>}
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-3 mb-3">
        <Select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as "priority_score" | "created_at")}
          aria-label="Sort by"
          className="px-3 py-2 rounded-lg border text-sm"
          style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
        >
          <option value="priority_score">Sort by priority score</option>
          <option value="created_at">Sort by newest</option>
        </Select>
        <Select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="Filter by status"
          className="px-3 py-2 rounded-lg border text-sm"
          style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
        >
          <option value="">All statuses</option>
          {QUESTION_STATUS_ORDER.map((s: QuestionStatus) => (
            <option key={s} value={s}>{QUESTION_STATUS_LABEL[s]}</option>
          ))}
        </Select>
      </div>

      {loadError && (
        <Alert severity="warning" style={{ marginBottom: 16 }}>
          <div className="flex items-center gap-3">
            <span>{loadError}</span>
            <Button variant="ghost" size="sm" onClick={load}>Retry</Button>
          </div>
        </Alert>
      )}

      <Card padding={0} style={{ overflow: "hidden" }}>
        <div className="overflow-x-auto">
          <Table>
            <TableHead>
              <TableRow style={{ color: "var(--pr-text-muted)", textAlign: "left", fontSize: 12, borderTop: "none", borderBottom: "1px solid var(--pr-overlay-05)" }}>
                <TableHeaderCell>Title</TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
                <TableHeaderCell>Priority score</TableHeaderCell>
                <TableHeaderCell>Actions</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {!questions && (
                <TableRow>
                  <TableCell colSpan={4} truncate={false}><SkeletonRows count={5} height={20} /></TableCell>
                </TableRow>
              )}
              {questions?.map((q) => (
                <TableRow
                  key={q.id}
                  className="transition-colors"
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--pr-bg-hover)")}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
                >
                  <TableCell truncate={false}>
                    <Link to={`/decision-intelligence/workflows/${workflowId}/questions/${q.id}`} style={{ color: "var(--pr-authority-blue)" }}>
                      {q.title}
                    </Link>
                  </TableCell>
                  <TableCell truncate={false}><QuestionStatusStepper status={q.status} /></TableCell>
                  <TableCell truncate={false}><PriorityScoreCell value={q.priority_score} scoringVersion={q.scoring_version} /></TableCell>
                  <TableCell truncate={false}>
                    <button
                      onClick={() => handleScore(q.id)}
                      disabled={scoringId === q.id}
                      className="text-xs px-2.5 py-1 rounded-md disabled:opacity-40"
                      style={{ backgroundColor: "var(--pr-overlay-06)", color: "var(--pr-text-secondary)" }}
                      title="Recompute priority_score from this question's current five dimension scores"
                    >
                      {scoringId === q.id ? "Scoring..." : "(Re)score"}
                    </button>
                  </TableCell>
                </TableRow>
              ))}
              {questions?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} truncate={false}>
                    <EmptyState
                      icon={HelpCircle}
                      title={statusFilter ? "No questions match this filter" : "No priority questions yet"}
                      description={statusFilter ? "Try a different status." : "Propose the first question this workflow needs answered."}
                    />
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </Card>

      <div className="mt-3" style={{ fontSize: 12, color: "var(--pr-text-muted)" }}>
        {total} question{total === 1 ? "" : "s"} total
      </div>
    </div>
  );
}
