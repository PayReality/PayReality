import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CaseListPage, DecisionRule, EvaluationResult, RuleVersion } from "./types";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const RULE: DecisionRule = {
  id: "rule1",
  organization_id: "org1",
  workflow_id: "wf1",
  name: "Refund approval threshold",
  source_answer_id: "a1",
  current_version_id: "v1",
  status: "draft",
  created_by_user_id: "u1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const VERSION: RuleVersion = {
  id: "v1",
  rule_id: "rule1",
  version: 1,
  schema_json: {
    root_condition: { field: "amount", operator: "lte", value: 1000 },
    action: { decision: "approve", human_review_required: false },
    exceptions: [],
    missing_data_behavior: "route_to_human",
  },
  scope: null,
  created_by_user_id: "u1",
  created_at: "2026-01-01T00:00:00Z",
};

const EMPTY_CASES: CaseListPage = { cases: [], total: 0, limit: 200, offset: 0 };

const TEST_RESULT: EvaluationResult = {
  matched: true,
  decision: "approve",
  human_review_required: false,
  matched_conditions: ["amount lte 1000"],
  unmatched_conditions: [],
  missing_fields: [],
};

const testRule = vi.fn(() => Promise.resolve(TEST_RESULT));

vi.mock("./api", () => ({
  decisionIntelligenceApi: {
    getRule: () => Promise.resolve(RULE),
    listRuleVersions: () => Promise.resolve([VERSION]),
    listCases: () => Promise.resolve(EMPTY_CASES),
    testRule: (...args: unknown[]) => testRule(...args),
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
  const { RuleDetailPage } = await import("./RuleDetailPage");
  await act(async () => {
    root.render(
      createElement(
        MemoryRouter,
        { initialEntries: ["/decision-intelligence/rules/rule1"] },
        createElement(Routes, null, createElement(Route, { path: "/decision-intelligence/rules/:ruleId", element: createElement(RuleDetailPage) }))
      )
    );
    await new Promise((r) => setTimeout(r, 50));
  });
}

describe("RuleDetailPage", () => {
  it("renders the condition tree as readable text, not raw JSON", async () => {
    await renderPage();
    // The field name and a humanized operator phrase should appear;
    // the raw JSON shape ("root_condition", "{") must not.
    expect(container.textContent).toContain("amount");
    expect(container.textContent).toContain("is at most");
    expect(container.textContent).toContain("approve");
    expect(container.textContent).not.toContain("root_condition");
  });

  it("submits the test-rule form and shows the real EvaluationResult", async () => {
    await renderPage();
    const runButton = Array.from(container.querySelectorAll("button")).find((b) => /Run test/.test(b.textContent ?? ""));
    expect(runButton).toBeTruthy();

    await act(async () => {
      runButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(testRule).toHaveBeenCalled();
    expect(container.textContent).toContain("Matched");
    expect(container.textContent).toContain("amount lte 1000");
  });
});
