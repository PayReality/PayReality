import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AssuranceSummary } from "../types";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const CLEAN_SUMMARY: AssuranceSummary = {
  total_agents: 5,
  active_agents: 5,
  active_policies: 3,
  policies_review_due: 0,
  policies_authority_expired: 0,
  allow_count: 10,
  deny_count: 1,
  human_review_count: 0,
  pending_review_count: 0,
  oldest_pending_review_at: null,
  resolved_review_count: 2,
  evidence_total: 11,
  evidence_verified: 11,
  evidence_pending: 0,
  evidence_rejected: 0,
};

const DIRTY_SUMMARY: AssuranceSummary = {
  ...CLEAN_SUMMARY,
  policies_review_due: 2,
  pending_review_count: 1,
  oldest_pending_review_at: new Date(Date.now() - 2 * 60 * 60 * 1000 - 14 * 60 * 1000).toISOString(),
  evidence_pending: 1,
};

let mockSummary: AssuranceSummary = CLEAN_SUMMARY;
vi.mock("../apiClient", () => ({
  apiClient: { get: () => Promise.resolve(mockSummary) },
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

// Core Product Experience Redesign, section 8: Assurance leads with a
// "needs attention" callout that only ever states what's actually true
// -- a clean org sees a calm confirmation, a dirty one sees the real,
// specific reasons.
describe("LiveAssurance attention states", () => {
  it("shows a calm confirmation when nothing needs attention", async () => {
    mockSummary = CLEAN_SUMMARY;
    const { LiveAssurance } = await import("./LiveAssurance");
    await act(async () => {
      root.render(createElement(MemoryRouter, null, createElement(LiveAssurance)));
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(container.textContent).toContain("Nothing needs attention right now");
  });

  it("surfaces specific, real reasons when something needs attention", async () => {
    mockSummary = DIRTY_SUMMARY;
    const { LiveAssurance } = await import("./LiveAssurance");
    await act(async () => {
      root.render(createElement(MemoryRouter, null, createElement(LiveAssurance)));
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(container.textContent).toContain("Needs attention");
    expect(container.textContent).toContain("2 policies require re-attestation");
    expect(container.textContent).toContain("Oldest pending review waiting 2h 14m");
    // Never an invented score.
    expect(container.textContent).not.toMatch(/trust score|risk score|compliance score/i);
  });
});
