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

// A queue of controllable getQuestion() responses, consumed in call
// order, so a test can resolve two overlapping requests out of order --
// the exact race this file's own `load()` epoch guard exists to survive.
let getQuestionQueue: Array<{ resolve: (d: QuestionDetail) => void; promise: Promise<QuestionDetail> }>;

function queueGetQuestion(): Promise<QuestionDetail> {
  if (getQuestionQueue.length > 0) {
    const next = getQuestionQueue.shift()!;
    return next.promise;
  }
  return Promise.resolve(DETAIL);
}

vi.mock("./api", () => ({
  decisionIntelligenceApi: {
    getQuestion: () => queueGetQuestion(),
    listAnswers: () => Promise.resolve([currentAnswer]),
    listRules: () => Promise.resolve(EMPTY_RULES),
    // Evidence-linking selectors (patterns/cases to link to this question)
    // load the workflow's full lists on mount, same as PatternDetailPage's
    // own case-linking selector already did before this test existed.
    listPatterns: () => Promise.resolve({ patterns: [], total: 0, limit: 200, offset: 0 }),
    listCases: () => Promise.resolve({ cases: [], total: 0, limit: 200, offset: 0 }),
    updateQuestion: () => Promise.resolve(QUESTION),
    scoreQuestion: () => Promise.resolve(QUESTION),
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
  getQuestionQueue = [];
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

// Found while validating Decision Intelligence end to end against a real
// backend: load() is fire-and-forget after every mutation on this page
// (score saves, pattern/case linking, answer actions), with no guarantee
// those GET /questions/{id} requests resolve in the order they were
// issued. A slow, now-stale response from an earlier load() resolving
// after a newer one used to overwrite the dimension-score inputs back to
// whatever they were before the user's latest save, with no error shown
// -- confirmed via a direct DB read after a UI flow that had reported
// success. Fixed with a per-request epoch guard; this locks that down.
describe("QuestionDetailPage: stale background refetch cannot clobber a newer one", () => {
  it("keeps the most recently issued load()'s data even if an earlier one resolves later", async () => {
    currentAnswer = answerWithAuthor("user-author-x");
    currentUserId = "user-different-reviewer";

    // Call #1 (mount): resolves immediately with all scores unset.
    // Call #2 (a later load(), simulating one kicked off by an earlier
    // action still in flight): deliberately held open, to be resolved
    // AFTER call #3.
    // Call #3 (the most recently issued load(), e.g. after a score save):
    // resolves first, with real scores set.
    let resolveCall2!: (d: QuestionDetail) => void;
    const call2Promise = new Promise<QuestionDetail>((resolve) => {
      resolveCall2 = resolve;
    });
    const scoredDetail: QuestionDetail = {
      question: { ...QUESTION, reach_score: 70, impact_score: 55, risk_score: 40, answerability_score: 80, decision_sensitivity_score: 35, priority_score: 57, scoring_version: "v1" },
      patterns: [],
      case_ids: [],
    };

    getQuestionQueue = [
      { resolve: () => {}, promise: Promise.resolve(DETAIL) }, // call #1: mount
      { resolve: resolveCall2, promise: call2Promise }, // call #2: held open
      { resolve: () => {}, promise: Promise.resolve(scoredDetail) }, // call #3: resolves immediately
    ];

    await renderPage();

    // Trigger call #2 (still unset scores) and call #3 (now scored) via
    // the real "Save scores" action, exactly as the real race occurred:
    // one save in flight, a second one issued and resolving first.
    const saveButton = Array.from(container.querySelectorAll("button")).find((b) => /Save scores/.test(b.textContent ?? ""));
    await act(async () => {
      saveButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 10));
    });
    await act(async () => {
      saveButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 10));
    });

    // Now let the STALE call #2 resolve, after the newer call #3 already
    // landed -- this is the exact out-of-order arrival the epoch guard
    // must survive.
    await act(async () => {
      resolveCall2(DETAIL);
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(container.textContent).toContain("57.00");
    expect(container.textContent).not.toContain("Not yet assessed");
  });
});
