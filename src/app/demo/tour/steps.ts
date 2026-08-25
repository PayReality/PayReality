import { POLICY_VENDOR_PAYMENT_UNDER_50K } from "../fixtures/policies";

export interface TourStep {
  path: string;
  selector: string;
  title: string;
  body: string;
}

// Follows the enterprise story beat for beat: AI reasons -> Runtime
// Authority verifies authority -> enterprise policies evaluated -> ERP
// executes -> Evidence generated -> independent verification. Every
// selector targets an element that already exists in the real app
// (see the data-tour attributes added alongside this file); nothing
// here is a slideshow screen of its own.
export const TOUR_STEPS: TourStep[] = [
  {
    path: "/decisions",
    selector: '[data-tour="intent-form"]',
    title: "1. The AI reasons",
    body: "An Accounts Payable agent decides to act: pay a supplier invoice. It signs the request with its own cryptographic key and submits it as an Intent. Try clicking \"Submit signed intent\" below, then Next.",
  },
  {
    path: "/decisions",
    selector: '[data-tour="decision-outcome"]',
    title: "2. Runtime Authority verifies authority",
    body: "PayReality evaluates the Intent before anything executes, determining whether this agent is authorized to act. It resolves exactly which human delegated authority to this agent, and for how much -- not a role name, a real Authority and Mandate.",
  },
  {
    path: `/governance/${POLICY_VENDOR_PAYMENT_UNDER_50K}`,
    selector: '[data-tour="policy-authority-block"]',
    title: "3. Enterprise policies are evaluated",
    body: "The Intent is checked against this organisation's actual governance rules -- spend limits, delegated-by chains, required evidence -- written once here, evaluated the same way for every decision.",
  },
  {
    path: "/decisions",
    selector: '[data-tour="decision-outcome"]',
    title: "4. The ERP executes",
    body: "Once authorized, the payment proceeds into the enterprise system of record -- here, SAP S/4HANA -- recorded against the same decision, not a separate disconnected log.",
  },
  {
    path: "/evidence",
    selector: '[data-tour="evidence-record"]',
    title: "5. Evidence is generated",
    body: "Every decision produces a cryptographically signed, tamper-evident record: which rule allowed it, under whose authority, and why -- automatically, not as an afterthought.",
  },
  {
    path: "/evidence",
    selector: '[data-tour="verify-signature"]',
    title: "6. Independent verification",
    body: "Anyone can verify that signature independently, right now. Click \"Verify signature\" to confirm this record hasn't been altered.",
  },
];
