import { AGENT_AP_INVOICE } from "../fixtures/agents";
import { DEMO_SYSTEM_SAP } from "../fixtures/integrations";
import { DECISION_HERO_ADAPTER_REVIEW, DECISION_HERO_ALLOW } from "../fixtures/decisions";

export interface TourStep {
  path: string;
  selector: string;
  title: string;
  body: string;
}

// Demo V2 (Trusted Authority Story): the central, guided narrative.
// DEMO_NARRATIVE.md, WEBSITE_CLAIMS.md, and ENTERPRISE_MESSAGING_GUIDE.md
// are the canonical sources this follows. The three-question model
// (Agent / Trusted Adapter / PayReality) runs through every beat; the
// old six-step generic "AI reasons, ERP executes" story is retired,
// see git history if it's ever needed for reference. Every selector
// below targets a real element already in the product (see the
// data-tour attributes added alongside this file); nothing here is a
// slideshow screen of its own, and nothing here claims PayReality
// observes or proves what an external system actually did.
export const TOUR_STEPS: TourStep[] = [
  {
    path: `/agents/${AGENT_AP_INVOICE}`,
    selector: '[data-tour="agent-trusted-connections"]',
    title: "1. Who's acting",
    body: "Meet the AP Invoice Agent, an AI agent with its own cryptographic identity. It's about to attempt something real in SAP: changing a supplier's bank details. Below is the one trusted connection it's allowed to act through.",
  },
  {
    path: `/organization/integrations/${DEMO_SYSTEM_SAP}`,
    selector: '[data-tour="mapping-row"]',
    title: "2. A Trusted Adapter reports the attempt",
    body: "PayReality doesn't watch SAP itself. A Trusted Adapter (software this organization controls and runs, not PayReality) observes the real operation and reports it: ChangeSupplierBankDetails.",
  },
  {
    path: `/organization/integrations/${DEMO_SYSTEM_SAP}`,
    selector: '[data-tour="mapping-row"]',
    title: "3. An approved Action Mapping establishes what that means",
    body: "A human reviewed and approved this exact mapping ahead of time: ChangeSupplierBankDetails means \"update a supplier's bank details.\" Only pre-approved information like this is ever trusted, never something an agent invents on the spot.",
  },
  {
    path: `/decisions/${DECISION_HERO_ADAPTER_REVIEW}`,
    selector: '[data-tour="decision-integration-provenance"]',
    title: "4. PayReality checks organizational authority",
    body: "Now PayReality asks the one question it exists to answer: has this organization actually authorized the AP Invoice Agent to do this, under these conditions? The Trusted Adapter only established what's being attempted; it never answers that question itself.",
  },
  {
    path: `/decisions/${DECISION_HERO_ADAPTER_REVIEW}`,
    selector: '[data-tour="decision-outcome"]',
    title: "5. The decision: Human Review",
    body: "Changing where a payment goes is exactly the kind of action this organization's policy sends to a human, every time: not a failure, a deliberate control against a classic vendor-fraud pattern.",
  },
  {
    path: `/decisions/${DECISION_HERO_ADAPTER_REVIEW}`,
    selector: '[data-tour="decision-evidence"]',
    title: "6. Every decision leaves proof",
    body: "Whichever way this resolves, it already produced a signed, tamper-evident Evidence record: who attempted it, what was reported, and why PayReality decided what it decided.",
  },
  {
    path: `/decisions/${DECISION_HERO_ADAPTER_REVIEW}/receipt`,
    selector: '[data-tour="receipt-integration-provenance"]',
    title: "7. The Authorization Receipt",
    body: "One packaged, shareable document for this decision: the agent, the system, the trusted connection, the mapping, and the decision itself, everything an auditor would ask for, in one place.",
  },
  {
    path: `/decisions/${DECISION_HERO_ADAPTER_REVIEW}`,
    selector: '[data-tour="replay-operation"]',
    title: "8. Retries don't create new decisions",
    body: "If SAP reported this exact operation again, a network retry, a duplicate webhook, PayReality recognizes it as the same real-world event and returns this exact decision, never a second one. Try clicking below, then Next.",
  },
  {
    path: `/decisions/${DECISION_HERO_ALLOW}`,
    selector: '[data-tour="decision-outcome"]',
    title: "9. Not every action needs review",
    body: "Here, the AP Invoice Agent reported directly, with no Trusted Adapter: a simpler path PayReality still fully supports. Within its delegated authority, the payment is authorized immediately: Allow. PayReality isn't here to block AI; it's here to make sure only what's actually authorized goes through.",
  },
];
