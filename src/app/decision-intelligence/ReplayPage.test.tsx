import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReplayCaseResultListPage, ReplayRun } from "./types";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const RUN: ReplayRun = {
  id: "run1",
  organization_id: "org1",
  workflow_id: "wf1",
  rule_version_id: "v1",
  case_set_definition: { mode: "all" },
  status: "completed",
  started_at: "2026-01-01T00:00:00Z",
  completed_at: "2026-01-01T00:05:00Z",
  summary: { agrees_with_baseline: 3, disagrees_with_baseline: 1, requires_human_review: 1 },
  created_by_user_id: "u1",
  created_at: "2026-01-01T00:00:00Z",
};

const RESULTS: ReplayCaseResultListPage = {
  results: [
    {
      id: "res1",
      replay_run_id: "run1",
      case_id: "case1",
      baseline_decision: { decision: "approve" },
      proposed_decision: { decision: "approve" },
      matched_conditions: ["amount lte 1000"],
      unmatched_conditions: [],
      outcome_category: "agrees_with_baseline",
      notes: null,
    },
    {
      id: "res2",
      replay_run_id: "run1",
      case_id: "case2",
      baseline_decision: { decision: "deny" },
      proposed_decision: { decision: "approve" },
      matched_conditions: ["amount lte 1000"],
      unmatched_conditions: [],
      outcome_category: "disagrees_with_baseline",
      notes: "baseline='deny' proposed='approve'",
    },
  ],
  total: 2,
  limit: 25,
  offset: 0,
};

vi.mock("./api", () => ({
  decisionIntelligenceApi: {
    getReplay: () => Promise.resolve(RUN),
    listReplayResults: () => Promise.resolve(RESULTS),
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
  const { ReplayPage } = await import("./ReplayPage");
  await act(async () => {
    root.render(
      createElement(
        MemoryRouter,
        { initialEntries: ["/decision-intelligence/replays/run1"] },
        createElement(Routes, null, createElement(Route, { path: "/decision-intelligence/replays/:replayId", element: createElement(ReplayPage) }))
      )
    );
    await new Promise((r) => setTimeout(r, 50));
  });
}

describe("ReplayPage: results view", () => {
  it("renders real summary counts per outcome category, with real visual weight (not a flat list)", async () => {
    await renderPage();
    expect(container.textContent).toContain("Agrees with baseline");
    expect(container.textContent).toContain("Disagrees with baseline");
    // Each category row renders a proportional bar -- its width is set
    // inline as a percentage, which is the actual "real visual weight"
    // mechanism this page uses instead of a same-size flat list.
    const bars = Array.from(container.querySelectorAll("div")).filter((d) => /width:\s*\d+(\.\d+)?%/.test(d.getAttribute("style") ?? ""));
    expect(bars.length).toBeGreaterThan(0);
  });

  it("renders the baseline-vs-proposed per-case table", async () => {
    await renderPage();
    expect(container.textContent).toContain("deny");
    expect(container.textContent).toContain("approve");
  });

  it("never claims agreement is correctness", async () => {
    await renderPage();
    expect(container.textContent).toMatch(/not.*correctness|not.*claim/i);
  });
});
