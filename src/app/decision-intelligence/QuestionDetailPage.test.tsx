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
let scoreQuestionResult: Question = QUESTION;

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
    scoreQuestion: () => Promise.resolve(scoreQuestionResult),
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
  scoreQuestionResult = QUESTION;
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
// backend: load() is called, unawaited, by several different actions on
// this same page (linking a pattern/case, an answer action, a score
// save), with no guard against one of them resolving late and clobbering
// something newer. Two distinct real failure modes were confirmed via a
// direct DB read after a UI flow that had reported success:
//
//  1. A reviewer starts entering dimension scores while an earlier
//     action's load() (e.g. one kicked off by linking a case moments
//     before) is still in flight. That load() resolving while they are
//     mid-entry used to reset the five score inputs back to blank,
//     discarding what they had just typed before they ever got to click
//     Save -- so the save that followed persisted empty values.
//  2. Even once scores reach the server, handleSaveScores used to trust
//     a separate, unawaited load() to resync the inputs afterward,
//     rather than the save's own response -- a slower, unrelated load()
//     resolving in between could still win that race.
//
// Fixed with two complementary guards: scoresDirtyRef stops load() from
// touching the five score inputs while the reviewer has unsaved local
// edits in them, and handleSaveScores now applies its own
// updateQuestion/scoreQuestion response directly instead of waiting on
// load(). The epoch guard (loadEpochRef) is additional defense in depth,
// ensuring only the most recently issued load() can ever apply at all.
describe("QuestionDetailPage: scoring survives an unrelated, slower background refetch", () => {
  it("does not lose an in-progress, unsaved score edit to an earlier action's load() resolving late", async () => {
    currentAnswer = answerWithAuthor("user-author-x");
    currentUserId = "user-different-reviewer";

    // Simulates a load() kicked off moments earlier by an unrelated
    // action still in flight when the reviewer starts typing a score.
    // Real-world trigger for a second load() beyond the one at mount:
    // useResourceSync's own cross-tab "storage" event listener (the
    // same mechanism a pattern/case link, or another tab, uses) -- fired
    // here directly so this held-open queue item is a genuine in-flight
    // request the component actually issued, not an unconnected promise.
    let resolveEarlierLoad!: (d: QuestionDetail) => void;
    const earlierLoadPromise = new Promise<QuestionDetail>((resolve) => {
      resolveEarlierLoad = resolve;
    });
    getQuestionQueue = [
      { resolve: () => {}, promise: Promise.resolve(DETAIL) }, // mount
      { resolve: resolveEarlierLoad, promise: earlierLoadPromise }, // held open
    ];

    await renderPage();

    await act(async () => {
      window.dispatchEvent(new StorageEvent("storage", { key: "pr:resource-changed:decision-intelligence" }));
      await new Promise((r) => setTimeout(r, 10));
    });

    const reachInput = Array.from(container.querySelectorAll("label"))
      .find((l) => l.textContent?.trim() === "Reach")
      ?.nextElementSibling as HTMLInputElement | undefined;
    expect(reachInput).toBeTruthy();

    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")!.set!;
      setter.call(reachInput, "70");
      reachInput!.dispatchEvent(new Event("input", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 10));
    });
    expect(reachInput!.value).toBe("70");

    // The earlier, unrelated load() now resolves with pre-edit (null)
    // data. It must not blank out the score the reviewer just typed.
    await act(async () => {
      resolveEarlierLoad(DETAIL);
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(reachInput!.value).toBe("70");
  });

  it("shows the save's own result immediately, without depending on a separate load()", async () => {
    currentAnswer = answerWithAuthor("user-author-x");
    currentUserId = "user-different-reviewer";

    const scoredQuestion: Question = {
      ...QUESTION,
      reach_score: 70,
      impact_score: 55,
      risk_score: 40,
      answerability_score: 80,
      decision_sensitivity_score: 35,
      priority_score: 57,
      scoring_version: "v1",
    };

    // The save's own trailing load() is held open -- the assertion below
    // must hold before it ever resolves.
    let resolveTrailingLoad!: (d: QuestionDetail) => void;
    const trailingLoadPromise = new Promise<QuestionDetail>((resolve) => {
      resolveTrailingLoad = resolve;
    });
    getQuestionQueue = [
      { resolve: () => {}, promise: Promise.resolve(DETAIL) }, // mount
      { resolve: resolveTrailingLoad, promise: trailingLoadPromise }, // held open
    ];
    scoreQuestionResult = scoredQuestion;

    await renderPage();

    const saveButton = Array.from(container.querySelectorAll("button")).find((b) => /Save scores/.test(b.textContent ?? ""));
    await act(async () => {
      saveButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(container.textContent).toContain("57.00");
    expect(container.textContent).not.toContain("Not yet assessed");

    // Letting the trailing load() resolve afterward (with consistent,
    // post-save data, as it would for real against this single-database
    // stack) must not disturb anything.
    await act(async () => {
      resolveTrailingLoad({ question: scoredQuestion, patterns: [], case_ids: [] });
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(container.textContent).toContain("57.00");
  });
});
