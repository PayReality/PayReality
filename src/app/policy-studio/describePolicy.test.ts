import { describe, expect, it } from "vitest";
import { describePolicy } from "./describePolicy";
import type { Constraints, Metadata, RuntimePolicyRequest, Scope } from "./types";

// describePolicy renders the one plain-English sentence a reviewer
// actually reads when deciding whether to approve a rule
// (PAYREALITY_UX_REVIEW.md section 13) -- it's generated FROM the real
// scope/conditions/effect, so a bug here misrepresents what a rule
// actually does to the human approving it, not just how it's displayed.

const EMPTY_CONSTRAINTS: Constraints = {
  delegated_by: null,
  expires: null,
  evidence_required: false,
  risk_level: null,
  authority_id: null,
  mandate_id: null,
  enterprise_system_id: null,
};

const EMPTY_METADATA: Metadata = { owner: null, created_by: null, tags: [] };

function policy(scope: Partial<Scope>, overrides: Partial<RuntimePolicyRequest> = {}): RuntimePolicyRequest {
  return {
    name: "Test policy",
    scope: { principal: "", action: "", agent: null, resource: null, ...scope },
    conditions: [],
    effect: "allow",
    constraints: EMPTY_CONSTRAINTS,
    metadata: EMPTY_METADATA,
    ...overrides,
  };
}

describe("describePolicy", () => {
  it("describes a bare scope with no conditions", () => {
    const sentence = describePolicy(policy({ principal: "AP-Invoice-Agent", action: "submit_payment" }));
    expect(sentence).toBe("When AP-Invoice-Agent tries to submit_payment → Allowed.");
  });

  it("marks an unset principal/action rather than rendering an empty string", () => {
    const sentence = describePolicy(policy({}));
    expect(sentence).toContain("(no principal set)");
    expect(sentence).toContain("(no action set)");
  });

  it("appends resource and agent-restriction clauses only when set", () => {
    const sentence = describePolicy(
      policy({
        principal: "AP-Invoice-Agent",
        action: "submit_payment",
        resource: "vendor_invoice",
        agent: "agent-123",
      })
    );
    expect(sentence).toBe(
      "When AP-Invoice-Agent tries to submit_payment involving vendor_invoice (only agent agent-123) → Allowed."
    );
  });

  it("joins multiple conditions with 'and', each translated through OPERATOR_LABEL", () => {
    const sentence = describePolicy(
      policy(
        { principal: "AP-Invoice-Agent", action: "submit_payment" },
        {
          conditions: [
            { field: "amount", operator: "<=", value: 5000 },
            { field: "currency", operator: "==", value: "USD" },
          ],
        }
      )
    );
    expect(sentence).toBe(
      "When AP-Invoice-Agent tries to submit_payment, and amount is at most 5000, and currency is USD, → Allowed."
    );
  });

  it("renders an 'exists' condition without a value clause", () => {
    const sentence = describePolicy(
      policy(
        { principal: "AP-Invoice-Agent", action: "submit_payment" },
        { conditions: [{ field: "approval_reference", operator: "exists", value: true }] }
      )
    );
    expect(sentence).toContain("approval_reference is present,");
  });

  it("joins an 'in' condition's array value with commas, not [object Object]", () => {
    const sentence = describePolicy(
      policy(
        { principal: "AP-Invoice-Agent", action: "submit_payment" },
        { conditions: [{ field: "country", operator: "in", value: ["US", "CA"] }] }
      )
    );
    expect(sentence).toContain("country is one of US, CA");
  });

  it("uses 'Not allowed', not 'Approve', for a deny effect (Approve is reserved for approving the rule itself)", () => {
    const sentence = describePolicy(
      policy({ principal: "AP-Invoice-Agent", action: "submit_payment" }, { effect: "deny" })
    );
    expect(sentence).toContain("→ Not allowed.");
    expect(sentence).not.toContain("Approve");
  });

  it("labels require_human_review with the canonical Decision language 'Needs human approval'", () => {
    const sentence = describePolicy(
      policy({ principal: "AP-Invoice-Agent", action: "submit_payment" }, { effect: "require_human_review" })
    );
    expect(sentence).toContain("→ Needs human approval.");
  });
});
