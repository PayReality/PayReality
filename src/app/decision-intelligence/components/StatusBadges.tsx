import { formatStatus } from "../../live/format";
import { StatusBadge } from "../../components/ui/status-badge";
import type {
  AnswerStatus,
  CaseStatus,
  OutcomeCategory,
  PatternReviewStatus,
  ReplayRunStatus,
  RuleStatus,
  WorkflowStatus,
} from "../types";

// Same left-border-plus-text convention as AgentStatusBadge/PolicyStatusBadge
// (components/ui/status-badge.tsx) -- every DI lifecycle vocabulary reads
// consistently with every other status in the app, never color alone.

const WORKFLOW_COLOR: Record<WorkflowStatus, string> = {
  active: "var(--pr-trust-green)",
  archived: "var(--pr-text-disabled)",
};
export function WorkflowStatusBadge({ status }: { status: WorkflowStatus }) {
  return <StatusBadge color={WORKFLOW_COLOR[status]} label={formatStatus(status)} />;
}

const CASE_COLOR: Record<CaseStatus, string> = {
  open: "var(--pr-authority-blue)",
  resolved: "var(--pr-trust-green)",
  escalated: "var(--pr-warning-amber)",
};
export function CaseStatusBadge({ status }: { status: CaseStatus }) {
  return <StatusBadge color={CASE_COLOR[status]} label={formatStatus(status)} />;
}

const PATTERN_REVIEW_COLOR: Record<PatternReviewStatus, string> = {
  proposed: "var(--pr-text-disabled)",
  reviewed: "var(--pr-authority-blue)",
  confirmed: "var(--pr-trust-green)",
  rejected: "var(--pr-critical-red)",
};
export function PatternReviewStatusBadge({ status }: { status: PatternReviewStatus }) {
  return <StatusBadge color={PATTERN_REVIEW_COLOR[status]} label={formatStatus(status)} />;
}

const ANSWER_COLOR: Record<AnswerStatus, string> = {
  draft: "var(--pr-text-disabled)",
  submitted: "var(--pr-authority-blue)",
  under_review: "var(--pr-authority-blue)",
  approved: "var(--pr-trust-green)",
  rejected: "var(--pr-critical-red)",
  superseded: "var(--pr-text-disabled)",
};
export function AnswerStatusBadge({ status }: { status: AnswerStatus }) {
  return <StatusBadge color={ANSWER_COLOR[status]} label={formatStatus(status)} />;
}

const RULE_COLOR: Record<RuleStatus, string> = {
  draft: "var(--pr-text-disabled)",
  validated: "var(--pr-trust-green)",
};
export function RuleStatusBadge({ status }: { status: RuleStatus }) {
  return <StatusBadge color={RULE_COLOR[status]} label={formatStatus(status)} />;
}

const REPLAY_RUN_COLOR: Record<ReplayRunStatus, string> = {
  pending: "var(--pr-text-disabled)",
  running: "var(--pr-authority-blue)",
  completed: "var(--pr-trust-green)",
  failed: "var(--pr-critical-red)",
};
export function ReplayRunStatusBadge({ status }: { status: ReplayRunStatus }) {
  return <StatusBadge color={REPLAY_RUN_COLOR[status]} label={formatStatus(status)} />;
}

// Replay result categories (replay_executor.py's own fixed vocabulary):
// these need real visual weight distinguishing "agrees" from "disagrees"
// from "needs a human" from "couldn't be evaluated" -- never a flat,
// same-weight list, per the product brief. Label text always carries the
// same "agreement, not correctness" wording used everywhere else in this
// feature; this badge never shortens it to something that could be
// misread as a correctness verdict.
export const OUTCOME_CATEGORY_LABEL: Record<OutcomeCategory, string> = {
  agrees_with_baseline: "Agrees with baseline",
  disagrees_with_baseline: "Disagrees with baseline",
  resolved_automatically: "Resolved automatically",
  requires_human_review: "Requires human review",
  missing_data: "Missing data",
  error: "Evaluation error",
};

const OUTCOME_CATEGORY_COLOR: Record<OutcomeCategory, string> = {
  agrees_with_baseline: "var(--pr-trust-green)",
  disagrees_with_baseline: "var(--pr-critical-red)",
  resolved_automatically: "var(--pr-authority-blue)",
  requires_human_review: "var(--pr-warning-amber)",
  missing_data: "var(--pr-text-disabled)",
  error: "var(--pr-critical-red)",
};

export function OutcomeCategoryBadge({ category }: { category: OutcomeCategory }) {
  return <StatusBadge color={OUTCOME_CATEGORY_COLOR[category]} label={OUTCOME_CATEGORY_LABEL[category]} />;
}

export function outcomeCategoryColor(category: OutcomeCategory): string {
  return OUTCOME_CATEGORY_COLOR[category];
}
