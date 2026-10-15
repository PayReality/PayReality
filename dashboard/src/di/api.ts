import { apiClient } from "../lib/apiClient";
import { triggerBrowserDownload } from "../lib/download";
import type {
  AcceptSuggestionResult,
  Answer,
  AnswerDisposition,
  Case,
  CaseLink,
  CaseLinkKind,
  CaseListPage,
  ColumnMappingTarget,
  DecisionRule,
  DiscoveryRunDetail,
  DiscoveryRunListPage,
  DiscoverySuggestion,
  EvaluationResult,
  ImportJob,
  ImportJobListPage,
  OrganizationOverview,
  Pattern,
  PatternListPage,
  Question,
  QuestionDetail,
  QuestionListPage,
  ReplayCaseResultListPage,
  ReplayRun,
  ReplayRunListPage,
  RuleListPage,
  RuleSchema,
  RuleVersion,
  ScoringConfig,
  ScoringWeights,
  Workflow,
  WorkflowListPage,
  WorkflowOverview,
} from "./types";

const BASE = "/v1/decision-intelligence";

function query(params: Record<string, string | number | undefined>): string {
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") usp.set(key, String(value));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

// One plain object, methods prefixed by resource -- every one of the 45
// backend routes (server/app/routers/decision_intelligence/*.py) lives
// under this same prefix.
export const decisionIntelligenceApi = {
  // -- Workflows --------------------------------------------------------
  listWorkflows: (params: { status?: string; limit?: number; offset?: number } = {}) =>
    apiClient.get<WorkflowListPage>(`${BASE}/workflows${query(params)}`),
  getWorkflow: (workflowId: string) => apiClient.get<Workflow>(`${BASE}/workflows/${workflowId}`),
  createWorkflow: (body: { name: string; description?: string; business_context?: string; owner_user_id?: string }) =>
    apiClient.post<Workflow>(`${BASE}/workflows`, body),
  updateWorkflow: (
    workflowId: string,
    body: Partial<{ name: string; description: string; business_context: string; owner_user_id: string; status: string }>,
  ) => apiClient.patch<Workflow>(`${BASE}/workflows/${workflowId}`, body),
  getWorkflowOverview: (workflowId: string) => apiClient.get<WorkflowOverview>(`${BASE}/workflows/${workflowId}/overview`),

  // -- Cases --------------------------------------------------------------
  // `q`: real server-side search (Feature: server-side case search),
  // case-insensitive substring match against external_ref and facts
  // (cases.py's own docstring) -- never a client-side filter of an
  // already-loaded page.
  listCases: (params: { workflow_id?: string; status?: string; q?: string; limit?: number; offset?: number } = {}) =>
    apiClient.get<CaseListPage>(`${BASE}/cases${query(params)}`),
  getCase: (caseId: string) => apiClient.get<Case>(`${BASE}/cases/${caseId}`),
  createCase: (body: {
    workflow_id: string;
    facts?: Record<string, unknown>;
    external_ref?: string;
    evidence_refs?: unknown[];
    ai_recommendation?: Record<string, unknown>;
    human_decision?: Record<string, unknown>;
    escalation_reason?: string;
    outcome?: string;
    outcome_evidence?: string;
  }) => apiClient.post<Case>(`${BASE}/cases`, body),
  updateCase: (
    caseId: string,
    body: Partial<{
      facts: Record<string, unknown>;
      evidence_refs: unknown[];
      ai_recommendation: Record<string, unknown>;
      human_decision: Record<string, unknown>;
      escalation_reason: string;
      outcome: string;
      outcome_evidence: string;
      status: string;
    }>,
  ) => apiClient.patch<Case>(`${BASE}/cases/${caseId}`, body),

  // -- Patterns -------------------------------------------------------------
  listPatterns: (params: { workflow_id?: string; review_status?: string; limit?: number; offset?: number } = {}) =>
    apiClient.get<PatternListPage>(`${BASE}/patterns${query(params)}`),
  getPattern: (patternId: string) => apiClient.get<Pattern>(`${BASE}/patterns/${patternId}`),
  createPattern: (body: {
    workflow_id: string;
    name: string;
    description: string;
    category: string;
    proposed_explanation: string;
    alternative_explanations?: unknown[];
    confidence?: string;
  }) => apiClient.post<Pattern>(`${BASE}/patterns`, body),
  updatePattern: (
    patternId: string,
    body: Partial<{
      name: string;
      description: string;
      category: string;
      proposed_explanation: string;
      alternative_explanations: unknown[];
      confidence: string;
      review_status: string;
    }>,
  ) => apiClient.patch<Pattern>(`${BASE}/patterns/${patternId}`, body),
  // Pattern's own linked Cases (evidence) -- see patterns.py's own note.
  listPatternCases: (patternId: string) => apiClient.get<string[]>(`${BASE}/patterns/${patternId}/cases`),
  // Same linked cases, WITH why each is linked (kind/reason) -- what a
  // reviewer needs to tell supporting evidence apart from a model-inferred
  // potentially-affected case.
  listPatternCaseLinks: (patternId: string) => apiClient.get<CaseLink[]>(`${BASE}/patterns/${patternId}/case-links`),
  linkPatternCase: (patternId: string, caseId: string, body: { kind?: CaseLinkKind; reason?: string } = {}) =>
    apiClient.post<{ linked: boolean }>(`${BASE}/patterns/${patternId}/cases`, { case_id: caseId, ...body }),
  unlinkPatternCase: (patternId: string, caseId: string) =>
    apiClient.delete<void>(`${BASE}/patterns/${patternId}/cases/${caseId}`),
  // Corrects an existing link's relevance category (e.g. demoting a
  // model-inferred "potentially_affected" case to "excluded" after actually
  // checking it) -- preserves the original link/audit history.
  relinkPatternCaseKind: (patternId: string, caseId: string, body: { new_kind: CaseLinkKind; reason?: string }) =>
    apiClient.patch<CaseLink>(`${BASE}/patterns/${patternId}/cases/${caseId}`, body),

  // -- Priority Questions --------------------------------------------------
  listQuestions: (params: { workflow_id?: string; status?: string; sort_by?: string; limit?: number; offset?: number } = {}) =>
    apiClient.get<QuestionListPage>(`${BASE}/questions${query(params)}`),
  getQuestion: (questionId: string) => apiClient.get<QuestionDetail>(`${BASE}/questions/${questionId}`),
  createQuestion: (body: { workflow_id: string; title: string; description?: string; owner_user_id?: string }) =>
    apiClient.post<Question>(`${BASE}/questions`, body),
  updateQuestion: (
    questionId: string,
    body: Partial<{
      title: string;
      description: string;
      owner_user_id: string;
      reach_score: number;
      impact_score: number;
      risk_score: number;
      answerability_score: number;
      decision_sensitivity_score: number;
    }>,
  ) => apiClient.patch<Question>(`${BASE}/questions/${questionId}`, body),
  scoreQuestion: (questionId: string) => apiClient.post<Question>(`${BASE}/questions/${questionId}/score`),
  submitQuestionForReview: (questionId: string) => apiClient.post<Question>(`${BASE}/questions/${questionId}/submit`),
  markQuestionReadyForReview: (questionId: string) =>
    apiClient.post<Question>(`${BASE}/questions/${questionId}/ready-for-review`),
  approveQuestionForOperationalUse: (questionId: string) =>
    apiClient.post<Question>(`${BASE}/questions/${questionId}/approve-for-operational-use`),
  linkQuestionPattern: (questionId: string, patternId: string) =>
    apiClient.post<{ linked: boolean }>(`${BASE}/questions/${questionId}/patterns`, { pattern_id: patternId }),
  unlinkQuestionPattern: (questionId: string, patternId: string) =>
    apiClient.delete<void>(`${BASE}/questions/${questionId}/patterns/${patternId}`),
  linkQuestionCase: (questionId: string, caseId: string, body: { kind?: CaseLinkKind; reason?: string } = {}) =>
    apiClient.post<{ linked: boolean }>(`${BASE}/questions/${questionId}/cases`, { case_id: caseId, ...body }),
  unlinkQuestionCase: (questionId: string, caseId: string) =>
    apiClient.delete<void>(`${BASE}/questions/${questionId}/cases/${caseId}`),
  // Corrects an existing link's relevance category -- same shape/reasoning
  // as relinkPatternCaseKind above.
  relinkQuestionCaseKind: (questionId: string, caseId: string, body: { new_kind: CaseLinkKind; reason?: string }) =>
    apiClient.patch<CaseLink>(`${BASE}/questions/${questionId}/cases/${caseId}`, body),
  // A reviewer's mandatory-reason override of priority_score -- `score:
  // null` clears a previous override and returns to the computed score
  // (the reason still explains why it's being cleared).
  setQuestionPriorityOverride: (questionId: string, body: { score: number | null; reason: string }) =>
    apiClient.post<Question>(`${BASE}/questions/${questionId}/priority-override`, body),

  // -- Answers (nested under a question for create/list, standalone for
  //    every lifecycle transition -- mirrors answers.py's own two routers) --
  listAnswers: (questionId: string) => apiClient.get<Answer[]>(`${BASE}/questions/${questionId}/answers`),
  createDraftAnswer: (
    questionId: string,
    body: {
      content: string;
      evidence_refs?: unknown[];
      scope?: string;
      conditions_exceptions?: string;
      effective_date?: string;
      review_date?: string;
    },
  ) => apiClient.post<Answer>(`${BASE}/questions/${questionId}/answers`, body),
  getAnswer: (answerId: string) => apiClient.get<Answer>(`${BASE}/answers/${answerId}`),
  submitAnswer: (answerId: string) => apiClient.post<Answer>(`${BASE}/answers/${answerId}/submit`),
  // BREAKING: now requires a body -- `disposition` is the approving
  // expert's own mandatory concluding judgement (di_answer_service's fixed
  // ANSWER_DISPOSITIONS vocabulary); the backend 422s without it.
  approveAnswer: (answerId: string, body: { disposition: AnswerDisposition; disposition_notes?: string }) =>
    apiClient.post<Answer>(`${BASE}/answers/${answerId}/approve`, body),
  rejectAnswer: (answerId: string, reason?: string) => apiClient.post<Answer>(`${BASE}/answers/${answerId}/reject`, { reason }),
  supersedeAnswer: (
    answerId: string,
    body: {
      content: string;
      evidence_refs?: unknown[];
      scope?: string;
      conditions_exceptions?: string;
      effective_date?: string;
      review_date?: string;
    },
  ) => apiClient.post<Answer>(`${BASE}/answers/${answerId}/supersede`, body),

  // -- Decision Rules ---------------------------------------------------
  listRules: (params: { workflow_id?: string; status?: string; limit?: number; offset?: number } = {}) =>
    apiClient.get<RuleListPage>(`${BASE}/rules${query(params)}`),
  getRule: (ruleId: string) => apiClient.get<DecisionRule>(`${BASE}/rules/${ruleId}`),
  createRule: (body: { workflow_id: string; name: string; source_answer_id: string; schema_json: RuleSchema }) =>
    apiClient.post<DecisionRule>(`${BASE}/rules`, body),
  listRuleVersions: (ruleId: string) => apiClient.get<RuleVersion[]>(`${BASE}/rules/${ruleId}/versions`),
  createRuleVersion: (ruleId: string, body: { schema_json: RuleSchema; scope?: string }) =>
    apiClient.post<RuleVersion>(`${BASE}/rules/${ruleId}/versions`, body),
  validateRule: (ruleId: string) => apiClient.post<DecisionRule>(`${BASE}/rules/${ruleId}/validate`),
  // Never persists anything server-side (rules.py's own docstring).
  testRule: (ruleId: string, body: { case_facts?: Record<string, unknown>; case_id?: string }) =>
    apiClient.post<EvaluationResult>(`${BASE}/rules/${ruleId}/test`, body),

  // -- Replays ----------------------------------------------------------
  listReplays: (params: { workflow_id?: string; limit?: number; offset?: number } = {}) =>
    apiClient.get<ReplayRunListPage>(`${BASE}/replays${query(params)}`),
  getReplay: (replayRunId: string) => apiClient.get<ReplayRun>(`${BASE}/replays/${replayRunId}`),
  // Runs synchronously -- the response already carries the completed
  // run's summary (replays.py's own docstring).
  createReplay: (body: { workflow_id: string; rule_version_id: string; case_ids?: string[]; filter_status?: string }) =>
    apiClient.post<ReplayRun>(`${BASE}/replays`, body),
  listReplayResults: (replayRunId: string, params: { limit?: number; offset?: number } = {}) =>
    apiClient.get<ReplayCaseResultListPage>(`${BASE}/replays/${replayRunId}/results${query(params)}`),

  // -- CSV case import (imports.py) ---------------------------------------
  // Real multipart upload: `column_mapping` is JSON-encoded into a form
  // field (not a nested JSON body -- imports.py's own docstring on why
  // multipart can't carry a structured object any other way).
  createImportJob: (workflowId: string, file: File, columnMapping: Record<string, ColumnMappingTarget>) => {
    const form = new FormData();
    form.set("file", file);
    form.set("workflow_id", workflowId);
    form.set("column_mapping", JSON.stringify(columnMapping));
    return apiClient.postForm<ImportJob>(`${BASE}/imports`, form);
  },
  listImportJobs: (params: { workflow_id?: string; limit?: number; offset?: number } = {}) =>
    apiClient.get<ImportJobListPage>(`${BASE}/imports${query(params)}`),
  getImportJob: (jobId: string) => apiClient.get<ImportJob>(`${BASE}/imports/${jobId}`),

  // -- Cross-workflow reports and real exports (reports.py) ---------------
  getOrganizationOverview: () => apiClient.get<OrganizationOverview>(`${BASE}/reports/organization-overview`),
  // Both exports below trigger a real browser file save from the
  // backend's own `text/csv` + `Content-Disposition: attachment`
  // response -- never a JSON payload rendered as text.
  exportPriorityQuestionsCsv: async (params: { workflow_id?: string } = {}) => {
    const { blob, filename } = await apiClient.downloadGet(`${BASE}/reports/questions/export${query(params)}`);
    triggerBrowserDownload(blob, filename ?? "priority_questions.csv");
  },
  exportReplayResultsCsv: async (replayRunId: string) => {
    const { blob, filename } = await apiClient.downloadGet(`${BASE}/reports/replays/${replayRunId}/export`);
    triggerBrowserDownload(blob, filename ?? `replay_${replayRunId}_results.csv`);
  },

  // -- Settings: configurable scoring weights (scoring_config.py) ---------
  getScoringConfig: () => apiClient.get<ScoringConfig>(`${BASE}/scoring-config`),
  updateScoringConfig: (weights: ScoringWeights) =>
    apiClient.put<ScoringConfig>(`${BASE}/scoring-config`, { weights }),

  // -- AI-assisted discovery (discovery.py) --------------------------------
  // Runs synchronously -- the response already carries the completed (or
  // failed) run's own suggestions (discovery.py's own docstring).
  runDiscovery: (workflowId: string) =>
    apiClient.post<DiscoveryRunDetail>(`${BASE}/workflows/${workflowId}/discover`),
  listDiscoveryRuns: (workflowId: string, params: { limit?: number; offset?: number } = {}) =>
    apiClient.get<DiscoveryRunListPage>(`${BASE}/workflows/${workflowId}/discovery-runs${query(params)}`),
  getDiscoveryRun: (workflowId: string, runId: string) =>
    apiClient.get<DiscoveryRunDetail>(`${BASE}/workflows/${workflowId}/discovery-runs/${runId}`),
  acceptSuggestion: (suggestionId: string) =>
    apiClient.post<AcceptSuggestionResult>(`${BASE}/discovery-suggestions/${suggestionId}/accept`),
  dismissSuggestion: (suggestionId: string) =>
    apiClient.post<DiscoverySuggestion>(`${BASE}/discovery-suggestions/${suggestionId}/dismiss`),
};
