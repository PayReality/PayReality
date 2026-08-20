import { describe, expect, it } from "vitest";
import { ApiError } from "./apiClient";
import {
  describeApiError,
  describeConditionBusiness,
  describeExplanationUnavailable,
  describeReason,
  formatStatus,
} from "./format";

// This module's own comment records the bug it exists to prevent:
// pages used to show `${action} failed: ${JSON.stringify(e.body)}`
// directly to a user, leaking raw backend payloads. These tests pin
// down that every known error/reason code still resolves to its real
// sentence, not a raw token or the wrong branch.

describe("describeApiError", () => {
  it("prefers an agent-status detail over the generic Operator Key message", () => {
    const err = new ApiError(403, { detail: "agent_revoked" });
    expect(describeApiError(err, "Submit intent")).toBe(
      "Submit intent failed: This agent's certificate has been permanently revoked and can no longer act."
    );
  });

  it("prefers a permission-denied detail over the generic Operator Key message", () => {
    const err = new ApiError(403, { detail: "permission_denied" });
    expect(describeApiError(err, "Resolve decision")).toContain("your role doesn't include this permission");
  });

  it("falls back to the Operator Key message for a plain 401/403 with no recognized detail", () => {
    const err = new ApiError(401, { detail: "something_else" });
    expect(describeApiError(err, "Activate policy")).toBe(
      "Activate policy failed: this action needs the Operator Key set in the sidebar (bottom left). Enter it there and try again."
    );
  });

  it("never leaks the raw error body for an unrecognized non-auth error", () => {
    const err = new ApiError(500, { detail: "unexpected_internal_state", trace: "some/internal/path.py:42" });
    const message = describeApiError(err, "Compile policy");
    expect(message).toBe("Compile policy failed. Please try again, or contact support if this continues.");
    expect(message).not.toContain("trace");
    expect(message).not.toContain("unexpected_internal_state");
  });

  it("gives a network-style message for a non-ApiError failure", () => {
    expect(describeApiError(new TypeError("Failed to fetch"), "Load agents")).toBe(
      "Load agents failed. Check your connection and try again."
    );
  });
});

describe("formatStatus", () => {
  it("humanizes an upper-snake-case enum", () => {
    expect(formatStatus("HUMAN_REVIEW")).toBe("Human review");
  });

  it("humanizes a lower-snake-case enum", () => {
    expect(formatStatus("pending_review")).toBe("Pending review");
  });
});

describe("describeReason", () => {
  it("returns null for no reason rather than a placeholder string", () => {
    expect(describeReason(null)).toBeNull();
    expect(describeReason(undefined)).toBeNull();
  });

  it("translates a known fail-closed reason code to its real sentence", () => {
    expect(describeReason("no_active_policy")).toBe(
      "There's no active rule for this yet, so it was sent to a human to decide."
    );
  });

  it("handles any opa_error variant through the same prefix branch", () => {
    expect(describeReason("opa_error: rego compile failed")).toBe(
      "The policy check itself hit an error, so this was sent to a human to decide."
    );
  });

  it("humanizes rather than drops an unrecognized reason code", () => {
    expect(describeReason("some_future_code")).toBe("Some future code");
  });
});

describe("describeExplanationUnavailable", () => {
  it("has a real sentence for every documented unavailable reason", () => {
    expect(describeExplanationUnavailable("bundle_manifest_not_available")).toContain(
      "predates per-condition explainability"
    );
  });

  it("falls back to a humanized code for an unrecognized reason", () => {
    expect(describeExplanationUnavailable("brand_new_reason_code")).toBe("Brand new reason code");
  });
});

describe("describeConditionBusiness", () => {
  it("phrases a passed amount <= condition as within the limit", () => {
    const message = describeConditionBusiness({
      field: "amount",
      operator: "<=",
      expected_value: 5000,
      actual_value: 1200,
      passed: true,
    });
    expect(message).toBe("Payment amount ($1,200) is within the allowed limit of $5,000.");
  });

  it("phrases a failed amount <= condition as exceeding the limit, not matching it", () => {
    const message = describeConditionBusiness({
      field: "amount",
      operator: "<=",
      expected_value: 5000,
      actual_value: 8000,
      passed: false,
    });
    expect(message).toContain("exceeds the allowed limit");
    expect(message).not.toContain("within the allowed limit");
  });

  it("phrases a passed amount >= condition as meeting the minimum, distinct from the <= branch", () => {
    const message = describeConditionBusiness({
      field: "amount",
      operator: ">=",
      expected_value: 100,
      actual_value: 500,
      passed: true,
    });
    expect(message).toBe("Payment amount ($500) meets the required minimum of $100.");
  });

  it("phrases a failed amount >= condition as below the minimum", () => {
    const message = describeConditionBusiness({
      field: "amount",
      operator: ">=",
      expected_value: 100,
      actual_value: 10,
      passed: false,
    });
    expect(message).toContain("is below the required minimum");
  });

  it("falls back to the generic operator-phrase sentence for a non-amount field", () => {
    const message = describeConditionBusiness({
      field: "currency",
      operator: "==",
      expected_value: "USD",
      actual_value: "EUR",
      passed: false,
    });
    expect(message).toBe("currency was equal to USD (actual: EUR) -- did not match.");
  });

  it("keeps an unrecognized field's raw name verbatim rather than inventing a label", () => {
    const message = describeConditionBusiness({
      field: "vendor_country",
      operator: "==",
      expected_value: "US",
      actual_value: "US",
      passed: true,
    });
    expect(message.startsWith("vendor_country")).toBe(true);
  });
});
