import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../components/ui/toast";
import type { Answer, Question, QuestionDetail, RuleListPage } from "./types";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const QUESTION: Question = {
  id: "q1",
  organization_id: "org1",
  workflow_id: "wf1",
  title: "What refund threshold needs manual review?",
  description: "Recurring uncertainty across escalated refund cases.",
  status: "answer_submitted",
  reach_score: null,
  impact_score: null,
  risk_score: null,
  answerability_score: null,
  decision_sensitivity_score: null,
  priority_score: null,
  scoring_version: null,
  owner_user_id: null,
  created_by_user_id: "user-author",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const DETAIL: QuestionDetail = { question: QUESTION, patterns: [], case_ids: [] };

function answerWithAuthor(authorId: string): Answer {
  return {
    id: "a1",
    question_id: "q1",
    content: "Refunds under $1,000 are pre-approved; above that, a human reviews.",
    evidence_refs: null,
    scope: null,
    conditions_exceptions: null,
    effective_date: null,
    review_date: null,
    version: 1,
    previous_version_id: null,
    author_user_id: authorId,
    approver_user_id: null,
    status: "submitted",
    submitted_at: "2026-01-02T00:00:00Z",
    decided_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
  };
}

const EMPTY_RULES: RuleListPage = { rules: [], total: 0, limit: 200, offset: 0 };

let currentAnswer: Answer;
let currentUserId: string;

vi.mock("./api", () => ({
  decisionIntelligenceApi: {
    getQuestion: () => Promise.resolve(DETAIL),
    listAnswers: () => Promise.resolve([currentAnswer]),
    listRules: () => Promise.resolve(EMPTY_RULES),
  },
}));
vi.mock("../organization/api", () => ({
  usersApi: { list: () => Promise.resolve([]) },
}));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: { id: currentUserId, name: "Test User" }, hasPermission: () => true }),
}));

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => {
    root.unmount();
  });
  container.remove();
  vi.restoreAllMocks();
});

async function renderPage() {
  const { QuestionDetailPage } = await import("./QuestionDetailPage");
  await act(async () => {
    root.render(
      createElement(
        MemoryRouter,
        { initialEntries: ["/decision-intelligence/workflows/wf1/questions/q1"] },
        createElement(
          ToastProvider,
          null,
          createElement(
            Routes,
            null,
            createElement(Route, {
              path: "/decision-intelligence/workflows/:workflowId/questions/:questionId",
              element: createElement(QuestionDetailPage),
            })
          )
        )
      )
    );
    await new Promise((r) => setTimeout(r, 50));
  });
}

// Separation of duties (di_answer_service.py's own hard rule, enforced
// in code not just RBAC): the user who authored an answer can never
// also approve or reject it. This must be a visible UI constraint, not
// just a backend 400 a user discovers by clicking and failing.
describe("QuestionDetailPage: approver cannot equal author", () => {
  it("disables Approve/Reject and explains why when the signed-in user authored the answer", async () => {
    currentAnswer = answerWithAuthor("user-same");
    currentUserId = "user-same";
    await renderPage();

    const approveButton = Array.from(container.querySelectorAll("button")).find((b) => /Approve/.test(b.textContent ?? ""));
    const rejectButton = Array.from(container.querySelectorAll("button")).find((b) => /Reject/.test(b.textContent ?? ""));
    expect(approveButton?.hasAttribute("disabled")).toBe(true);
    expect(rejectButton?.hasAttribute("disabled")).toBe(true);
    expect(container.textContent).toContain("you can't also approve or reject it");
  });

  it("leaves Approve/Reject enabled for a reviewer who did not author the answer", async () => {
    currentAnswer = answerWithAuthor("user-author-x");
    currentUserId = "user-different-reviewer";
    await renderPage();

    const approveButton = Array.from(container.querySelectorAll("button")).find((b) => /Approve/.test(b.textContent ?? ""));
    const rejectButton = Array.from(container.querySelectorAll("button")).find((b) => /Reject/.test(b.textContent ?? ""));
    expect(approveButton?.hasAttribute("disabled")).toBe(false);
    expect(rejectButton?.hasAttribute("disabled")).toBe(false);
    expect(container.textContent).not.toContain("you can't also approve or reject it");
  });
});
