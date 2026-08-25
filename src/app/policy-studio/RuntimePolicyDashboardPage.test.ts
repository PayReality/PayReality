import { describe, expect, it } from "vitest";
import { isAuthorityExpired } from "./RuntimePolicyDashboardPage";

// Milestone 17.1 Part B: the one piece of logic this page's own
// "review due != authority expired" distinction actually depends on --
// a review-due policy must never be reported as expired just because
// its re-attestation reminder passed, and an explicitly expired
// authority must never be hidden by that same reminder logic.

describe("isAuthorityExpired", () => {
  it("is false when authority_expires_at is not set at all (review-due only, never expired)", () => {
    expect(isAuthorityExpired(null)).toBe(false);
  });

  it("is false when authority_expires_at is set but still in the future", () => {
    const future = new Date(Date.now() + 1000 * 60 * 60).toISOString();
    expect(isAuthorityExpired(future)).toBe(false);
  });

  it("is true when authority_expires_at has genuinely passed", () => {
    const past = new Date(Date.now() - 1000 * 60 * 60).toISOString();
    expect(isAuthorityExpired(past)).toBe(true);
  });

  it("accepts an injectable 'now' so the result never depends on the real clock", () => {
    const fixedPoint = new Date("2026-06-01T00:00:00Z").getTime();
    const justBefore = "2026-05-31T23:59:59Z";
    const justAfter = "2026-06-01T00:00:01Z";
    expect(isAuthorityExpired(justBefore, fixedPoint)).toBe(true);
    expect(isAuthorityExpired(justAfter, fixedPoint)).toBe(false);
  });
});
