import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RuntimePolicy, RuntimePolicyRequest } from "./types";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const PROPOSAL: RuntimePolicyRequest = {
  name: "AI Proposed Rule",
  description: "",
  scope: { principal: "CFO", action: "vendor_payment", agent: null, resource: null },
  conditions: [{ field: "amount", operator: "<=", value: 250000 }],
  effect: "require_human_review",
  constraints: {
    delegated_by: "CFO Delegation", expires: null, evidence_required: true, risk_level: "medium",
    authority_id: null, mandate_id: null, enterprise_system_id: null,
  },
  metadata: { owner: null, created_by: "draft_with_ai", tags: [] },
};

const EXISTING: RuntimePolicy = {
  policy_key: "p1",
  name: "Existing Rule",
  description: "desc",
  version: 3,
  status: "draft",
  scope: { principal: "Old Principal", action: "old_action", agent: null, resource: null },
  conditions: [],
  effect: "deny",
  constraints: {
    delegated_by: "Old Delegate", expires: "2027-01-01T00:00:00Z", evidence_required: true, risk_level: "high",
    authority_id: "auth-123", mandate_id: "mandate-456", enterprise_system_id: "sys-789",
  },
  metadata: { owner: "Old Owner", created_by: "manual", tags: ["existing-tag"] },
} as RuntimePolicy;

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: null, hasPermission: () => true }),
}));
vi.mock("../organization/api", () => ({
  organizationApi: {
    listEnterpriseSystems: () => Promise.resolve([{ id: "sys-789", name: "SAP S/4HANA" }]),
  },
}));
vi.mock("./api", () => ({
  policyStudioApi: {
    get: () => Promise.resolve(EXISTING),
    getVocabulary: () => Promise.resolve({ actions: ["vendor_payment"], condition_fields: ["amount"], trusted_context_prefix: "context." }),
    listPrincipals: () => Promise.resolve([]),
    listAgents: () => Promise.resolve([]),
    create: vi.fn(),
    edit: vi.fn(),
    submitForReview: vi.fn(),
  },
}));
// Isolates this test from DraftWithAIPanel.test.tsx's own coverage of the
// panel's open/close/error/validation UI -- this file is only about
// PolicyWorkspacePage's own merge logic (section 39/40: applying a
// proposal must preserve fields the proposal never touches).
vi.mock("./components/DraftWithAIPanel", () => ({
  DraftWithAIPanel: (props: { onApply: (p: RuntimePolicyRequest) => void }) =>
    createElement("button", { onClick: () => props.onApply(PROPOSAL) }, "MOCK_APPLY_PROPOSAL"),
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
  const { PolicyWorkspacePage } = await import("./PolicyWorkspacePage");
  await act(async () => {
    root.render(
      createElement(
        MemoryRouter,
        { initialEntries: ["/governance/p1"] },
        createElement(Routes, null, createElement(Route, { path: "/governance/:policyKey", element: createElement(PolicyWorkspacePage) }))
      )
    );
    await new Promise((r) => setTimeout(r, 60));
  });
}

describe("PolicyWorkspacePage: applying an AI-proposed change", () => {
  it("updates the fields the proposal actually addresses, and preserves the ones it doesn't", async () => {
    await renderPage();

    const applyStub = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === "MOCK_APPLY_PROPOSAL");
    expect(applyStub).toBeTruthy();
    await act(async () => {
      applyStub!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 20));
    });

    // React-controlled inputs/selects only expose their current value as
    // a live DOM property, never as an HTML attribute -- an attribute
    // selector like input[value=...] silently matches nothing here.
    const inputs = () => Array.from(container.querySelectorAll("input"));
    const selects = () => Array.from(container.querySelectorAll("select"));

    // Fields the proposal actually determines: applied.
    expect(selects().some((s) => s.value === "CFO")).toBe(true);
    expect(selects().some((s) => s.value === "vendor_payment")).toBe(true);
    expect(inputs().some((i) => i.value === "CFO Delegation")).toBe(true);
    expect(selects().some((s) => s.value === "medium")).toBe(true);

    // An existing rule's own name is not silently overwritten by a
    // generic AI-generated one.
    expect(container.textContent).toContain("Existing Rule");
    expect(container.textContent).not.toContain("AI Proposed Rule");

    // Fields the proposal has no way to determine: preserved from the
    // rule as it existed before applying.
    expect(container.textContent).toContain("auth-123");
    expect(container.textContent).toContain("mandate-456");
    expect(selects().some((s) => s.value === "sys-789")).toBe(true);
    expect(inputs().some((i) => i.value === "Old Owner")).toBe(true);
    expect(container.textContent).toContain("existing-tag");
  });
});
