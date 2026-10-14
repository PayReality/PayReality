import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../components/ui/toast";
import type { Question, QuestionListPage } from "./types";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

// Core differentiator: a question whose dimensions haven't all been
// judged yet must show priority_score as "Needs scoring," never a
// silent zero/blank -- and one that HAS been scored must show the real
// number. See scoring.py's own hard contract (compute_priority_score
// returns None, never a substituted default, if any input is None).
const UNSCORED: Question = {
  id: "q-unscored",
  organization_id: "org1",
  workflow_id: "wf1",
  title: "What threshold triggers manual review?",
  description: null,
  status: "proposed",
  reach_score: null,
  impact_score: null,
  risk_score: null,
  answerability_score: null,
  decision_sensitivity_score: null,
  priority_score: null,
  scoring_version: null,
  owner_user_id: null,
  created_by_user_id: "u1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const SCORED: Question = {
  ...UNSCORED,
  id: "q-scored",
  title: "Which vendor categories need dual approval?",
  status: "awaiting_answer",
  reach_score: 80,
  impact_score: 70,
  risk_score: 60,
  answerability_score: 50,
  decision_sensitivity_score: 90,
  priority_score: 72.5,
  scoring_version: "v1",
};

const LIST_PAGE: QuestionListPage = { questions: [UNSCORED, SCORED], total: 2, limit: 50, offset: 0 };

vi.mock("./api", () => ({
  decisionIntelligenceApi: {
    listQuestions: () => Promise.resolve(LIST_PAGE),
  },
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
  const { QuestionsPage } = await import("./QuestionsPage");
  await act(async () => {
    root.render(
      createElement(
        MemoryRouter,
        { initialEntries: ["/decision-intelligence/workflows/wf1/questions"] },
        createElement(
          ToastProvider,
          null,
          createElement(
            Routes,
            null,
            createElement(Route, {
              path: "/decision-intelligence/workflows/:workflowId/questions",
              element: createElement(QuestionsPage),
            })
          )
        )
      )
    );
    await new Promise((r) => setTimeout(r, 50));
  });
}

describe("QuestionsPage", () => {
  it("renders a null priority_score as 'Needs scoring', never a silent zero", async () => {
    await renderPage();
    expect(container.textContent).toContain("Needs scoring");
    // The unscored question's title should still render even with no score.
    expect(container.textContent).toContain("What threshold triggers manual review?");
  });

  it("renders a real computed priority_score for a fully-judged question", async () => {
    await renderPage();
    expect(container.textContent).toContain("72.5");
    expect(container.textContent).toContain("Which vendor categories need dual approval?");
  });

  it("renders a status badge/stepper reflecting each question's real lifecycle status", async () => {
    await renderPage();
    // QuestionStatusStepper renders the formatted status label alongside the dots.
    expect(container.textContent).toContain("Proposed");
    expect(container.textContent).toContain("Awaiting answer");
  });
});
