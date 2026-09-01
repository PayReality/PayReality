import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RuntimePolicyRequest } from "../types";
import type { DraftResponse } from "../draftingApi";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const draftMock = vi.fn<[string, RuntimePolicyRequest | null], Promise<DraftResponse>>();
const explainMock = vi.fn<[RuntimePolicyRequest, string, string | undefined], Promise<string>>();

vi.mock("../draftingApi", () => ({
  policyDraftingApi: {
    draft: (...args: [string, RuntimePolicyRequest | null]) => draftMock(...args),
    explain: (...args: [RuntimePolicyRequest, string, string | undefined]) => explainMock(...args),
  },
}));

let container: HTMLDivElement;
let root: Root;

const EMPTY_DRAFT: RuntimePolicyRequest = {
  name: "",
  description: "",
  scope: { principal: "", action: "", agent: null, resource: null },
  conditions: [],
  effect: "require_human_review",
  constraints: { delegated_by: null, expires: null, evidence_required: true, risk_level: null, authority_id: null, mandate_id: null, enterprise_system_id: null },
  metadata: { owner: null, created_by: null, tags: [] },
};

const VALID_PROPOSAL: RuntimePolicyRequest = {
  ...EMPTY_DRAFT,
  name: "CFO vendor payment limit",
  scope: { principal: "CFO", action: "vendor_payment", agent: null, resource: null },
  conditions: [{ field: "amount", operator: "<=", value: 250000 }],
  effect: "require_human_review",
  metadata: { owner: null, created_by: "draft_with_ai", tags: [] },
};

function baseResponse(overrides: Partial<DraftResponse> = {}): DraftResponse {
  return {
    proposal: null,
    clarifying_question: null,
    unknown_entities: [],
    requires_additional_policies: false,
    additional_policies_note: null,
    confidence: null,
    missing_fields: [],
    ...overrides,
  };
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  draftMock.mockReset();
  explainMock.mockReset();
});

afterEach(() => {
  act(() => {
    root.unmount();
  });
  container.remove();
  vi.restoreAllMocks();
});

async function renderPanel(onApply = vi.fn()) {
  const { DraftWithAIPanel } = await import("./DraftWithAIPanel");
  const onOpenChange = vi.fn();
  await act(async () => {
    root.render(
      createElement(DraftWithAIPanel, {
        open: true,
        onOpenChange,
        currentDraft: EMPTY_DRAFT,
        deterministicSummary: "This rule has no conditions yet.",
        hasContent: false,
        onApply,
      })
    );
    await new Promise((r) => setTimeout(r, 20));
  });
  return { onOpenChange, onApply };
}

// Radix Sheet portals to document.body, same reason IntegrationsListPage's
// own tests never query Sheet content from the local container.
function findByText(tag: string, text: string | RegExp) {
  return Array.from(document.body.querySelectorAll(tag)).find((el) =>
    typeof text === "string" ? el.textContent === text : text.test(el.textContent ?? "")
  );
}

async function typeInstruction(text: string) {
  const textarea = document.body.querySelector("textarea") as HTMLTextAreaElement;
  const setValue = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")!.set!;
  await act(async () => {
    setValue.call(textarea, text);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function clickSend() {
  const button = findByText("button", /^(Draft|Thinking\.\.\.)$/) as HTMLButtonElement;
  await act(async () => {
    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 20));
  });
}

// Product Experience V3.2, Part C: the same three invariants the backend
// unit tests establish (section 31/36/37) must also hold in the one place
// a human can actually act on a proposal -- this panel.
describe("DraftWithAIPanel", () => {
  it("requires an explicit Apply click before a valid proposal reaches the caller", async () => {
    draftMock.mockResolvedValue(baseResponse({ proposal: VALID_PROPOSAL }));
    const { onApply } = await renderPanel();

    await typeInstruction("Only allow the CFO to create vendor payments up to R250,000.");
    await clickSend();

    expect(onApply).not.toHaveBeenCalled();
    const applyButton = findByText("button", "Apply proposal") as HTMLButtonElement;
    expect(applyButton).toBeTruthy();
    expect(applyButton.disabled).toBe(false);

    await act(async () => {
      applyButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onApply).toHaveBeenCalledWith(VALID_PROPOSAL);
  });

  it("cannot apply a proposal that references an unknown entity", async () => {
    draftMock.mockResolvedValue(
      baseResponse({ unknown_entities: [{ field: "principal", value: "Regional VP Sales" }] })
    );
    const { onApply } = await renderPanel();

    await typeInstruction("Let the Regional VP Sales approve large payments.");
    await clickSend();

    expect(document.body.textContent).toContain("Regional VP Sales");
    expect(document.body.textContent).toContain("not a registered principal");
    expect(findByText("button", "Apply proposal")).toBeUndefined();
    expect(onApply).not.toHaveBeenCalled();
  });

  it("cannot apply anything while the model has asked a clarifying question", async () => {
    draftMock.mockResolvedValue(baseResponse({ clarifying_question: "Which principal(s) count as senior?" }));
    const { onApply } = await renderPanel();

    await typeInstruction("Let senior people approve large transactions.");
    await clickSend();

    expect(document.body.textContent).toContain("Which principal(s) count as senior?");
    expect(findByText("button", "Apply proposal")).toBeUndefined();
    expect(onApply).not.toHaveBeenCalled();
  });

  it("leaves the current rule untouched and offers retry when the request fails", async () => {
    draftMock.mockRejectedValue(new Error("network"));
    const { onApply } = await renderPanel();

    await typeInstruction("Only allow the CFO to create vendor payments up to R250,000.");
    await clickSend();

    expect(document.body.textContent).toMatch(/unchanged/i);
    expect(onApply).not.toHaveBeenCalled();
    const sendAgain = findByText("button", /^Draft$/) as HTMLButtonElement;
    expect(sendAgain).toBeTruthy();
    expect(sendAgain.disabled).toBe(false);
  });
});
