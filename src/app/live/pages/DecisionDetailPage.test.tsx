import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../../demo/config", () => ({ DEMO_MODE: true }));
vi.mock("../../auth/AuthContext", () => ({
  useAuth: () => ({ user: { id: "u1", name: "Test User", email: "t@example.com" }, hasPermission: () => true }),
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

// Core Product Experience Redesign, section 4C: the causal-narrative
// Decision Detail page renders the decision's outcome plus its
// supporting sections for a real demo decision id.
describe("DecisionDetailPage (demo mode)", () => {
  it("renders the outcome and causal sections for a real decision", async () => {
    const { DECISION_HERO_ALLOW } = await import("../../demo/fixtures/decisions");
    const { DecisionDetailPage } = await import("./DecisionDetailPage");
    await act(async () => {
      root.render(
        createElement(
          MemoryRouter,
          { initialEntries: [`/decisions/${DECISION_HERO_ALLOW}`] },
          createElement(
            Routes,
            null,
            createElement(Route, { path: "/decisions/:decisionId", element: createElement(DecisionDetailPage) })
          )
        )
      );
      await new Promise((r) => setTimeout(r, 80));
    });

    expect(container.textContent).toContain("Allow");
    expect(container.textContent).toContain("Authority");
    expect(container.textContent).toContain("Policy");
    expect(container.textContent).toContain("Capability authorization");
    expect(container.textContent).toContain("Evidence");

    // Issue #4 (Authorization Receipts): reachable from Decision Detail.
    const receiptLink = container.querySelector(`a[href="/decisions/${DECISION_HERO_ALLOW}/receipt"]`);
    expect(receiptLink).not.toBeNull();
  });

  it("never shows integration provenance for an Agent-direct decision", async () => {
    const { DECISION_HERO_ALLOW } = await import("../../demo/fixtures/decisions");
    const { DecisionDetailPage } = await import("./DecisionDetailPage");
    await act(async () => {
      root.render(
        createElement(
          MemoryRouter,
          { initialEntries: [`/decisions/${DECISION_HERO_ALLOW}`] },
          createElement(Routes, null, createElement(Route, { path: "/decisions/:decisionId", element: createElement(DecisionDetailPage) }))
        )
      );
      await new Promise((r) => setTimeout(r, 80));
    });

    expect(container.textContent).not.toContain("Reported through a trusted connection");
  });
});

// Trusted Integration Architecture, Phase 4 (section 28): Adapter-
// mediated Decision provenance, isolated from the shared demo fixture
// set (mocking decisionsApi.get directly) so this doesn't perturb any
// other page's decision counts/filters.
describe("DecisionDetailPage integration provenance (mocked Adapter-mediated decision)", () => {
  it("shows system, trusted connection, external action, environment, and external operation id", async () => {
    vi.resetModules();
    const { AGENT_AP_INVOICE } = await import("../../demo/fixtures/agents");
    const { DEMO_SYSTEM_SAP, DEMO_TRUSTED_CONNECTION_SAP } = await import("../../demo/fixtures/integrations");
    vi.doMock("../decisionsApi", () => ({
      decisionsApi: {
        get: () => Promise.resolve({
          id: "decision-adapter-test", status: "RESOLVED", outcome: "ALLOW", reason: "Within approved mapping.",
          agent_id: AGENT_AP_INVOICE, action: "vendor_payment", resource: "supplier:123", amount: 9800, currency: "USD",
          created_at: new Date().toISOString(), evaluated_mandates: [], evaluated_mandate_ids: [],
          enterprise_system_id: null, enterprise_system_name: null, policy_version: null, policy_bundle_hash: null,
          authority_version: null, resolution: null, source: "runtime", principal_name: "David Okonkwo",
          evidence_id: "evidence-adapter-test", facts_evaluated: null, matched_policy_freshness: null, capability: null,
          correlation_id: null,
          integration: {
            integration_identity_id: DEMO_TRUSTED_CONNECTION_SAP, enforcement_binding_id: "connection-sap-demo",
            integration_contract_version_id: "mapping-sap-approved-demo", integration_contract_content_hash: "sha256:demo",
            integration_id: DEMO_SYSTEM_SAP, environment: "production", source_operation: "ChangeSupplierBankDetails",
            external_operation_id: "OP-92819",
          },
        }),
      },
    }));

    const { DecisionDetailPage } = await import("./DecisionDetailPage");
    await act(async () => {
      root.render(
        createElement(
          MemoryRouter,
          { initialEntries: ["/decisions/decision-adapter-test"] },
          createElement(Routes, null, createElement(Route, { path: "/decisions/:decisionId", element: createElement(DecisionDetailPage) }))
        )
      );
      await new Promise((r) => setTimeout(r, 150));
    });

    expect(container.textContent).toContain("Reported through a trusted connection");
    expect(container.textContent).toContain("SAP S/4HANA");
    expect(container.textContent).toContain("SAP Procurement Adapter");
    expect(container.textContent).toContain("ChangeSupplierBankDetails");
    expect(container.textContent).toContain("OP-92819");
    expect(container.textContent).toMatch(/not proof the external system actually executed it/);

    vi.doUnmock("../decisionsApi");
  });
});
