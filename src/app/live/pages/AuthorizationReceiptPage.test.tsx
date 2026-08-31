import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../../demo/config", () => ({ DEMO_MODE: true }));

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

function renderAt(path: string, Component: () => JSX.Element) {
  return act(async () => {
    root.render(
      createElement(
        MemoryRouter,
        { initialEntries: [path] },
        createElement(Routes, null, createElement(Route, { path: "/decisions/:decisionId/receipt", element: createElement(Component) }))
      )
    );
    await new Promise((r) => setTimeout(r, 80));
  });
}

// Issue #4 (Authorization Receipts): the stable, named artifact reachable
// from Decision Detail -- renders the assembled decision/authority/
// facts/evidence/verification view for a real demo decision id.
describe("AuthorizationReceiptPage (demo mode)", () => {
  it("renders the receipt for an ALLOW decision, verified", async () => {
    const { DECISION_HERO_ALLOW } = await import("../../demo/fixtures/decisions");
    const { AuthorizationReceiptPage } = await import("./AuthorizationReceiptPage");
    await renderAt(`/decisions/${DECISION_HERO_ALLOW}/receipt`, AuthorizationReceiptPage);

    expect(container.textContent).toContain("Authorization Receipt");
    expect(container.textContent).toContain("Allow");
    expect(container.textContent).toContain("Signature verified");
    expect(container.textContent).toContain("Governing authority");
    expect(container.textContent).toContain("Trusted enterprise facts");
  });

  it("expands technical verification details on request, showing the underlying evidence identity", async () => {
    const { DECISION_HERO_ALLOW } = await import("../../demo/fixtures/decisions");
    const { AuthorizationReceiptPage } = await import("./AuthorizationReceiptPage");
    await renderAt(`/decisions/${DECISION_HERO_ALLOW}/receipt`, AuthorizationReceiptPage);

    expect(container.textContent).not.toContain("Signing key ID");

    const toggle = Array.from(container.querySelectorAll("button")).find((b) => /Technical verification details/.test(b.textContent ?? ""));
    expect(toggle).toBeTruthy();
    await act(async () => {
      toggle!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 30));
    });

    expect(container.textContent).toContain("Signing key ID");
    expect(container.textContent).toContain("Evidence ID");
  });

  it("never renders a claim that consumption means the downstream action executed", async () => {
    const { DECISION_HERO_ALLOW } = await import("../../demo/fixtures/decisions");
    const { AuthorizationReceiptPage } = await import("./AuthorizationReceiptPage");
    await renderAt(`/decisions/${DECISION_HERO_ALLOW}/receipt`, AuthorizationReceiptPage);

    const text = container.textContent ?? "";
    expect(text).not.toMatch(/action (actually )?executed/i);
    if (text.includes("Capability authorization")) {
      expect(text).toContain("not confirmation that the");
    }
  });
});

// Trusted Integration Architecture, Phase 4 (section 29): the Receipt's
// own "Reported through a trusted connection" card, isolated from the
// shared demo fixture set the same way DecisionDetailPage's own
// equivalent test is.
describe("AuthorizationReceiptPage integration provenance (mocked Adapter-mediated receipt)", () => {
  it("shows reported-through / system / mapping / environment / external operation, and never claims execution", async () => {
    vi.resetModules();
    const { DEMO_SYSTEM_SAP, DEMO_TRUSTED_CONNECTION_SAP, DEMO_MAPPING_SAP_APPROVED } = await import("../../demo/fixtures/integrations");
    vi.doMock("../decisionsApi", () => ({
      decisionsApi: {
        getReceipt: () => Promise.resolve({
          receipt_id: "evidence-adapter-test", evidence_id: "evidence-adapter-test", generated_at: new Date().toISOString(),
          decision: { decision_id: "decision-adapter-test", outcome: "ALLOW", created_at: new Date().toISOString(), source: "runtime" },
          actor: { agent_id: "agent-ap-invoice", agent_name: "AP Invoice Agent", principal_id: null, principal_name: "David Okonkwo" },
          request: { action: "vendor_payment", resource: "supplier:123", amount: 9800, currency: "USD", context: {}, correlation_id: null },
          authority: { policy_id: null, bundle_hash: null, bundle_version: null, compiled_at: null, activated_at: null, retired_at: null, authority_version: null, policies: [] },
          facts: [], human_review: null, capability: null,
          integration: {
            integration_identity_id: DEMO_TRUSTED_CONNECTION_SAP, enforcement_binding_id: "connection-sap-demo",
            integration_contract_version_id: DEMO_MAPPING_SAP_APPROVED, integration_contract_content_hash: "sha256:demo",
            integration_id: DEMO_SYSTEM_SAP, environment: "production", source_operation: "ChangeSupplierBankDetails",
            external_operation_id: "OP-92819",
          },
          evidence: { evidence_id: "evidence-adapter-test", key_id: "key-1", signature: "sig", previous_hash: null, payload_hash: "hash", status: "VERIFIED", created_at: new Date().toISOString() },
          verification: { signature_valid: true, key_id: "key-1", algorithm: "ed25519", verified_at: new Date().toISOString() },
        }),
      },
    }));

    const { AuthorizationReceiptPage } = await import("./AuthorizationReceiptPage");
    await act(async () => {
      root.render(
        createElement(
          MemoryRouter,
          { initialEntries: ["/decisions/decision-adapter-test/receipt"] },
          createElement(Routes, null, createElement(Route, { path: "/decisions/:decisionId/receipt", element: createElement(AuthorizationReceiptPage) }))
        )
      );
      await new Promise((r) => setTimeout(r, 150));
    });

    expect(container.textContent).toContain("Reported through a trusted connection");
    expect(container.textContent).toContain("SAP Procurement Adapter trusted connection");
    expect(container.textContent).toContain("SAP S/4HANA");
    expect(container.textContent).toContain("ChangeSupplierBankDetails");
    expect(container.textContent).toContain("Vendor Payment");
    expect(container.textContent).toContain("OP-92819");
    expect(container.textContent).not.toMatch(/action (actually )?executed/i);

    vi.doUnmock("../decisionsApi");
  });
});
